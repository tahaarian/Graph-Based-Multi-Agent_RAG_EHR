"""
build_graph.py  –  OMOP CDM  →  Neo4j Temporal Knowledge Graph

Pipeline:
  0. Schema: constraints + indexes
  1b. Build source-code → standard concept_id map (SNOMED/RxNorm → OMOP)
  1. Collect referenced concept_ids (pre-scan, memory-efficient)
  2. Load Concept nodes  (only referenced ~thousands, not full 1.3M)
  3. Load Patient nodes  (person.csv)
  4. Load clinical-event nodes + Patient -[:HAS_*]-> Event edges
  5. MAPS_TO edges       (Event -[:MAPS_TO]-> Concept)
  6. NEXT_EVENT chain    (per patient, cross-domain, ordered by date)

Usage:
    python scripts/build_graph.py
    python scripts/build_graph.py --wipe
    python scripts/build_graph.py --skip-chain
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(r"E:\projects\taha\RAG papers\my paper and project\Graph-Based-Multi-Agent_RAG_EHR")
VOCAB_DIR = Path(r"E:\projects\taha\RAG papers\my paper and project\vocab")
OMOP_DIR  = BASE_DIR / "data" / "processed" / "omop_cdm"

# ─── Neo4j credentials ────────────────────────────────────────────────────────
def _load_env(base: Path) -> None:
    for name in (".env", ".env.example"):
        p = base / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            break

_load_env(BASE_DIR)
NEO4J_URI  = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "password")

BATCH = 500

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / "build_graph.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── OMOP table definitions ───────────────────────────────────────────────────
TABLE_CONFIG: list[dict] = [
    dict(
        file        = "condition_occurrence.csv",
        label       = "Condition",
        id_col      = "condition_occurrence_id",
        node_id     = "occurrence_id",
        person_col  = "person_id",
        concept_col = "condition_concept_id",
        source_col  = "condition_source_value",
        rel         = "HAS_CONDITION",
        date_col    = "condition_start_date",
        end_col     = "condition_end_date",
        extra_cols  = ["condition_type_concept_id", "stop_reason"],
    ),
    dict(
        file        = "drug_exposure.csv",
        label       = "DrugExposure",
        id_col      = "drug_exposure_id",
        node_id     = "exposure_id",
        person_col  = "person_id",
        concept_col = "drug_concept_id",
        source_col  = "drug_source_value",
        rel         = "HAS_DRUG_EXPOSURE",
        date_col    = "drug_exposure_start_date",
        end_col     = "drug_exposure_end_date",
        extra_cols  = ["quantity", "days_supply", "route_concept_id",
                       "drug_type_concept_id"],
    ),
    dict(
        file        = "procedure_occurrence.csv",
        label       = "Procedure",
        id_col      = "procedure_occurrence_id",
        node_id     = "occurrence_id",
        person_col  = "person_id",
        concept_col = "procedure_concept_id",
        source_col  = "procedure_source_value",
        rel         = "HAS_PROCEDURE",
        date_col    = "procedure_date",
        end_col     = None,
        extra_cols  = ["procedure_type_concept_id", "modifier_concept_id"],
    ),
    dict(
        file        = "measurement.csv",
        label       = "Measurement",
        id_col      = "measurement_id",
        node_id     = "measurement_id",
        person_col  = "person_id",
        concept_col = "measurement_concept_id",
        source_col  = "measurement_source_value",
        rel         = "HAS_MEASUREMENT",
        date_col    = "measurement_date",
        end_col     = None,
        extra_cols  = ["value_as_number", "value_as_string",
                       "unit_concept_id", "range_low", "range_high",
                       "measurement_type_concept_id"],
    ),
    dict(
        file        = "observation.csv",
        label       = "Observation",
        id_col      = "observation_id",
        node_id     = "observation_id",
        person_col  = "person_id",
        concept_col = "observation_concept_id",
        source_col  = "observation_source_value",
        rel         = "HAS_OBSERVATION",
        date_col    = "observation_date",
        end_col     = None,
        extra_cols  = ["value_as_number", "value_as_string",
                       "value_as_concept_id", "observation_type_concept_id"],
    ),
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def detect_delimiter(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        sample = f.read(4096)
    return "\t" if sample.count("\t") > sample.count(",") else ","


def _val(row: dict, col: str) -> str | None:
    if col not in row:
        return None
    v = row[col].strip()
    return v or None


def _int(row: dict, col: str) -> int | None:
    v = _val(row, col)
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _float(row: dict, col: str) -> float | None:
    v = _val(row, col)
    if not v:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def iter_csv(path: Path):
    delim = detect_delimiter(path)
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        yield from csv.DictReader(f, delimiter=delim)


def flush(session, cypher: str, rows: list) -> None:
    """Send rows to Neo4j in BATCH-sized UNWIND chunks."""
    for i in range(0, len(rows), BATCH):
        session.run(cypher, rows=rows[i : i + BATCH])


# ─── Step 0: Schema ───────────────────────────────────────────────────────────

def create_schema(driver) -> None:
    log.info("=== Step 0: Schema ===")
    constraints = [
        ("Patient",      "person_id"),
        ("Concept",      "concept_id"),
        ("Condition",    "occurrence_id"),
        ("DrugExposure", "exposure_id"),
        ("Procedure",    "occurrence_id"),
        ("Measurement",  "measurement_id"),
        ("Observation",  "observation_id"),
    ]
    with driver.session() as s:
        for label, prop in constraints:
            try:
                s.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
                log.info("  ✓ constraint %s.%s", label, prop)
            except Neo4jError as exc:
                log.warning("  ! constraint %s.%s – %s", label, prop, exc.message)

        for label in ("Condition", "DrugExposure", "Procedure",
                      "Measurement", "Observation"):
            s.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.date)")

        s.run("CREATE INDEX IF NOT EXISTS FOR (n:Patient) ON (n.birth_year)")
        s.run("CREATE INDEX IF NOT EXISTS FOR (n:Concept)  ON (n.domain_id)")
        s.run("CREATE INDEX IF NOT EXISTS FOR (n:Concept)  ON (n.vocabulary_id)")
    log.info("Schema ready.\n")


# ─── Step 1b: Build source-code → standard concept_id map ────────────────────

def build_source_map() -> dict[str, int]:
    concept_path = VOCAB_DIR / "CONCEPT.csv"
    rel_path     = VOCAB_DIR / "CONCEPT_RELATIONSHIP.csv"

    if not concept_path.exists():
        log.warning("  CONCEPT.csv not found – source mapping unavailable")
        return {}

    code_to_cid:  dict[str, int] = {}
    standard_ids: set[int]       = set()

    log.info("  Reading CONCEPT.csv for source map …")
    delim = detect_delimiter(concept_path)
    with open(concept_path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f, delimiter=delim):
            try:
                cid = int(row.get("concept_id", "").strip())
            except ValueError:
                continue
            code  = (row.get("concept_code")     or "").strip()
            vocab = (row.get("vocabulary_id")    or "").strip()
            std   = (row.get("standard_concept") or "").strip()

            if code:
                code_to_cid[code]              = cid  # bare:      "314529007"
                code_to_cid[f"{vocab}:{code}"] = cid  # qualified: "SNOMED:314529007"

            if std == "S":
                standard_ids.add(cid)

    log.info("    code_to_cid: %d  |  standard: %d", len(code_to_cid), len(standard_ids))

    maps_to: dict[int, int] = {}

    if rel_path.exists():
        log.info("  Reading CONCEPT_RELATIONSHIP.csv for Maps-to chain …")
        delim2 = detect_delimiter(rel_path)
        with open(rel_path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f, delimiter=delim2):
                if (row.get("relationship_id") or "").strip() != "Maps to":
                    continue
                try:
                    c1 = int(row.get("concept_id_1", "").strip())
                    c2 = int(row.get("concept_id_2", "").strip())
                except ValueError:
                    continue
                if c2 in standard_ids:
                    maps_to[c1] = c2
        log.info("    Maps-to pairs found: %d", len(maps_to))
    else:
        log.warning("  CONCEPT_RELATIONSHIP.csv not found – only direct standard codes mapped")

    result: dict[str, int] = {}
    for code, cid in code_to_cid.items():
        if cid in standard_ids:
            result[code] = cid
        elif cid in maps_to:
            result[code] = maps_to[cid]

    log.info("  Source map ready: %d entries\n", len(result))
    return result

# ─── Step 1: Collect referenced concept_ids ───────────────────────────────────

def collect_referenced_concepts(source_map: dict[str, int]) -> set[int]:
    """
    Scans all OMOP tables and collects every standard concept_id that will be
    needed.  If a row's *_concept_id is 0 or missing, falls back to resolving
    *_source_value through source_map.
    """
    log.info("=== Step 1: Collect referenced concept_ids ===")
    ids: set[int] = set()
    for tbl in TABLE_CONFIG:
        path = OMOP_DIR / tbl["file"]
        if not path.exists():
            log.warning("  missing: %s", path.name)
            continue
        for row in iter_csv(path):
            cid = _int(row, tbl["concept_col"])
            if not cid or cid == 0:                          # fallback to source_value
                sv = _val(row, tbl["source_col"])
                if sv:
                    cid = source_map.get(sv) or source_map.get(sv.strip())
            if cid and cid != 0:
                ids.add(cid)
    log.info("  total referenced concept_ids: %d\n", len(ids))
    return ids


# ─── Step 2: Load Concept nodes ───────────────────────────────────────────────

def load_concepts(driver, referenced_ids: set[int]) -> None:
    log.info("=== Step 2: Load Concept nodes ===")
    concept_path = VOCAB_DIR / "CONCEPT.csv"
    if not concept_path.exists():
        log.warning("  CONCEPT.csv not found – skipping\n")
        return

    cypher = """
    UNWIND $rows AS r
    MERGE (c:Concept {concept_id: r.concept_id})
    SET c.name          = r.concept_name,
        c.domain_id     = r.domain_id,
        c.vocabulary_id = r.vocabulary_id,
        c.concept_class = r.concept_class_id,
        c.standard_flag = r.standard_concept,
        c.concept_code  = r.concept_code
    """

    delim = detect_delimiter(concept_path)
    batch: list = []
    total = 0

    with open(concept_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        with driver.session() as session:
            for row in reader:
                try:
                    cid = int(row.get("concept_id", "").strip())
                except ValueError:
                    continue
                if cid not in referenced_ids:
                    continue

                batch.append({
                    "concept_id":       cid,
                    "concept_name":     (row.get("concept_name")     or "").strip(),
                    "domain_id":        (row.get("domain_id")        or "").strip(),
                    "vocabulary_id":    (row.get("vocabulary_id")    or "").strip(),
                    "concept_class_id": (row.get("concept_class_id") or "").strip(),
                    "standard_concept": (row.get("standard_concept") or "").strip(),
                    "concept_code":     (row.get("concept_code")     or "").strip(),
                })
                if len(batch) >= BATCH:
                    flush(session, cypher, batch)
                    total += len(batch)
                    batch = []

            if batch:
                flush(session, cypher, batch)
                total += len(batch)

    log.info("  Concept nodes loaded: %d\n", total)


# ─── Step 3: Load Patient nodes ───────────────────────────────────────────────

def load_patients(driver) -> None:
    log.info("=== Step 3: Load Patient nodes ===")
    person_path = OMOP_DIR / "person.csv"
    if not person_path.exists():
        log.warning("  person.csv not found – skipping\n")
        return

    cypher = """
    UNWIND $rows AS r
    MERGE (p:Patient {person_id: r.person_id})
    SET p.birth_year        = r.year_of_birth,
        p.birth_month       = r.month_of_birth,
        p.birth_day         = r.day_of_birth,
        p.gender_concept_id = r.gender_concept_id,
        p.race_concept_id   = r.race_concept_id,
        p.ethnicity_concept_id = r.ethnicity_concept_id,
        p.gender_source     = r.gender_source_value,
        p.race_source       = r.race_source_value
    """

    batch: list = []
    total = 0
    with driver.session() as session:
        for row in iter_csv(person_path):
            pid = _int(row, "person_id")
            if not pid:
                continue
            batch.append({
                "person_id":           pid,
                "year_of_birth":       _int(row,   "year_of_birth"),
                "month_of_birth":      _int(row,   "month_of_birth"),
                "day_of_birth":        _int(row,   "day_of_birth"),
                "gender_concept_id":   _int(row,   "gender_concept_id"),
                "race_concept_id":     _int(row,   "race_concept_id"),
                "ethnicity_concept_id":_int(row,   "ethnicity_concept_id"),
                "gender_source_value": _val(row,   "gender_source_value"),
                "race_source_value":   _val(row,   "race_source_value"),
            })
            if len(batch) >= BATCH:
                flush(session, cypher, batch)
                total += len(batch)
                batch = []
        if batch:
            flush(session, cypher, batch)
            total += len(batch)

    log.info("  Patient nodes loaded: %d\n", total)


# ─── Step 4: Load clinical-event nodes + Patient→Event edges ──────────────────

def load_events(driver, source_map: dict[str, int]) -> None:
    log.info("=== Step 4: Load clinical-event nodes ===")

    for tbl in TABLE_CONFIG:
        path = OMOP_DIR / tbl["file"]
        if not path.exists():
            log.warning("  missing: %s – skipping", tbl["file"])
            continue

        label       = tbl["label"]
        id_col      = tbl["id_col"]
        node_id     = tbl["node_id"]
        person_col  = tbl["person_col"]
        concept_col = tbl["concept_col"]
        source_col  = tbl["source_col"]
        rel         = tbl["rel"]
        date_col    = tbl["date_col"]
        end_col     = tbl.get("end_col")
        extra_cols  = tbl.get("extra_cols", [])

        extra_set = "\n".join(
            f"        e.{col} = r.{col}," for col in extra_cols
        )

        cypher = f"""
        UNWIND $rows AS r
        MATCH (p:Patient {{person_id: r.person_id}})
        MERGE (e:{label} {{{node_id}: r.event_id}})
        SET e.date          = r.date,
            e.end_date      = r.end_date,
            e.source_value  = r.source_value,
            e.concept_id    = r.concept_id,
            {extra_set}
            e._dummy        = null
        MERGE (p)-[:{rel}]->(e)
        """

        batch: list = []
        total = 0
        with driver.session() as session:
            for row in iter_csv(path):
                eid = _int(row, id_col)
                pid = _int(row, person_col)
                if not eid or not pid:
                    continue

                # Resolve concept_id: use column value if non-zero,
                # otherwise look up source_value in the source map
                concept_id = _int(row, concept_col)
                if not concept_id or concept_id == 0:
                    sv = _val(row, source_col)
                    if sv:
                        concept_id = source_map.get(sv)

                record: dict = {
                    "event_id":    eid,
                    "person_id":   pid,
                    "date":        _val(row, date_col),
                    "end_date":    _val(row, end_col) if end_col else None,
                    "source_value":_val(row, source_col),
                    "concept_id":  concept_id,
                }
                for col in extra_cols:
                    v = _val(row, col)
                    if v is not None:
                        try:
                            record[col] = float(v) if "." in v else int(v)
                        except (ValueError, TypeError):
                            record[col] = v
                    else:
                        record[col] = None

                batch.append(record)
                if len(batch) >= BATCH:
                    flush(session, cypher, batch)
                    total += len(batch)
                    batch = []

            if batch:
                flush(session, cypher, batch)
                total += len(batch)

        log.info("  %-16s  nodes/edges loaded: %d", label, total)

    log.info("")


# ─── Step 5: MAPS_TO edges  (Event → Concept) ─────────────────────────────────

def build_maps_to(driver) -> None:
    log.info("=== Step 5: MAPS_TO edges ===")
    labels = [tbl["label"] for tbl in TABLE_CONFIG]
    with driver.session() as s:
        for label in labels:
            result = s.run(f"""
                MATCH (e:{label})
                WHERE e.concept_id IS NOT NULL AND e.concept_id <> 0
                WITH e
                MATCH (c:Concept {{concept_id: e.concept_id}})
                MERGE (e)-[:MAPS_TO]->(c)
                RETURN count(*) AS n
            """)
            n = result.single()["n"]
            log.info("  %-16s  MAPS_TO created: %d", label, n)
    log.info("")


# ─── Step 6: NEXT_EVENT temporal chain per patient ────────────────────────────

def build_next_event_chain(driver) -> None:
    """
    For each patient, collect all their events cross-domain,
    sort by date, then chain with NEXT_EVENT relationships.
    """
    log.info("=== Step 6: NEXT_EVENT temporal chain ===")

    with driver.session() as s:
        s.run("MATCH ()-[r:NEXT_EVENT]->() DELETE r")
    log.info("  Cleared existing NEXT_EVENT edges.")

    timeline: dict = defaultdict(list)

    for tbl in TABLE_CONFIG:
        path = OMOP_DIR / tbl["file"]
        if not path.exists():
            continue
        label   = tbl["label"]
        id_col  = tbl["id_col"]
        p_col   = tbl["person_col"]
        d_col   = tbl["date_col"]
        node_id = tbl["node_id"]

        for row in iter_csv(path):
            pid  = _int(row, p_col)
            eid  = _int(row, id_col)
            date = _val(row, d_col) or "9999-99-99"
            if pid and eid:
                timeline[pid].append((date, label, eid, node_id))

    cypher_templates: dict = {}

    def get_cypher(label_a: str, nid_a: str, label_b: str, nid_b: str) -> str:
        key = (label_a, nid_a, label_b, nid_b)
        if key not in cypher_templates:
            cypher_templates[key] = f"""
            UNWIND $rows AS r
            MATCH (a:{label_a} {{{nid_a}: r.id_a}})
            MATCH (b:{label_b} {{{nid_b}: r.id_b}})
            MERGE (a)-[:NEXT_EVENT {{delta_days: r.delta}}]->(b)
            """
        return cypher_templates[key]

    def date_to_int(d: str) -> int:
        try:
            parts = d.split("-")
            return int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
        except Exception:
            return 0

    total_edges = 0
    pair_buffer: dict = defaultdict(list)

    def flush_pairs(session):
        nonlocal total_edges
        for (la, na, lb, nb), rows in pair_buffer.items():
            for i in range(0, len(rows), BATCH):
                session.run(get_cypher(la, na, lb, nb), rows=rows[i:i+BATCH])
                total_edges += len(rows[i:i+BATCH])
        pair_buffer.clear()

    with driver.session() as session:
        for pid, events in timeline.items():
            events.sort(key=lambda x: x[0])

            for i in range(len(events) - 1):
                date_a, label_a, eid_a, nid_a = events[i]
                date_b, label_b, eid_b, nid_b = events[i + 1]
                delta = date_to_int(date_b) - date_to_int(date_a)

                pair_buffer[(label_a, nid_a, label_b, nid_b)].append({
                    "id_a":  eid_a,
                    "id_b":  eid_b,
                    "delta": delta,
                })

            if sum(len(v) for v in pair_buffer.values()) >= 50_000:
                flush_pairs(session)

        flush_pairs(session)

    log.info("  NEXT_EVENT edges created: %d\n", total_edges)


# ─── Wipe ─────────────────────────────────────────────────────────────────────

def wipe_graph(driver) -> None:
    log.warning("Wiping entire graph …")
    with driver.session() as s:
        s.run(
            "MATCH (n) "
            "CALL { WITH n DETACH DELETE n } "
            "IN TRANSACTIONS OF 10000 ROWS"
        )
    log.info("Graph wiped.\n")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Neo4j EHR Knowledge Graph from OMOP CDM"
    )
    parser.add_argument(
        "--wipe", action="store_true",
        help="Drop all nodes/edges before rebuilding"
    )
    parser.add_argument(
        "--skip-chain", action="store_true",
        help="Skip NEXT_EVENT temporal chain (faster debug run)"
    )
    args = parser.parse_args()

    log.info("Connecting to Neo4j at %s …", NEO4J_URI)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
        log.info("Connected.\n")
    except Exception as exc:
        log.error("Cannot connect to Neo4j: %s", exc)
        sys.exit(1)

    t0 = time.time()

    if args.wipe:
        wipe_graph(driver)

    create_schema(driver)

    source_map = build_source_map()                        # Step 1b: build SNOMED→OMOP map
    referenced = collect_referenced_concepts(source_map)   # Step 1:  scan all tables
    load_concepts(driver, referenced)                      # Step 2:  load Concept nodes
    load_patients(driver)                                  # Step 3:  load Patient nodes
    load_events(driver, source_map)                        # Step 4:  load events + edges
    build_maps_to(driver)                                  # Step 5:  MAPS_TO edges
    if not args.skip_chain:
        build_next_event_chain(driver)                     # Step 6:  NEXT_EVENT chain

    driver.close()
    elapsed = time.time() - t0
    log.info("=== Done in %.1f s ===", elapsed)


if __name__ == "__main__":
    main()
