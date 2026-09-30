"""
OMOP Concept Mapping Improvement
Maps source codes to standard OMOP concept_ids using Athena vocabulary files.
"""
import sqlite3
import csv
import sys
import time
from pathlib import Path

DB_PATH   = Path("D:/projects/EHR/omop_cdm.db")
VOCAB_DIR = Path("D:/projects/EHR/vocab")

GENDER_MAP = {
    "m": 8507, "male": 8507,
    "f": 8532, "female": 8532,
}

RACE_MAP = {
    "white": 8527,
    "black or african american": 8516,
    "asian": 8515,
    "american indian or alaska native": 8657,
    "native hawaiian or other pacific islander": 8557,
    "other": 8522,
    "unknown": 0,
}

ETHNICITY_MAP = {
    "hispanic or latino": 38003563,
    "hispanic": 38003563,
    "not hispanic or latino": 38003564,
    "nonhispanic": 38003564,
}

VISIT_MAP = {
    "ambulatory": 9202,
    "outpatient": 9202,
    "wellness": 9202,
    "inpatient": 9201,
    "emergency": 9203,
    "urgentcare": 9203,
    "home": 581476,
    "hospice": 38004277,
    "snf": 42898160,
}

TYPE_CONCEPT = {
    "condition":   32020,
    "drug":        38000177,
    "procedure":   38000275,
    "measurement": 44818702,
    "observation": 38000280,
    "visit":       44818518,
}


def load_concept_lookup(vocab_dir):
    concept_csv = vocab_dir / "CONCEPT.csv"
    if not concept_csv.exists():
        print("  WARN: CONCEPT.csv not found. Only hardcoded maps will be applied.")
        return {}

    lookup = {}
    print(f"  Loading {concept_csv} ...")
    t0 = time.time()
    with open(concept_csv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("invalid_reason", "").strip():
                continue
            key = (row["vocabulary_id"].strip(), row["concept_code"].strip())
            lookup[key] = int(row["concept_id"])
    elapsed = round(time.time() - t0, 1)
    print(f"  Loaded {len(lookup):,} concepts in {elapsed}s.")
    return lookup


def get_cid(lookup, vocab, code):
    return lookup.get((vocab, str(code or "").strip()), 0)


def update_person(conn, lookup):
    print("\n  [person] Updating gender / race / ethnicity ...")
    rows = conn.execute(
        "SELECT person_id, gender_source_value, race_source_value,"
        " ethnicity_source_value FROM person"
    ).fetchall()

    updated = 0
    for pid, gender, race, ethnicity in rows:
        gcid = GENDER_MAP.get((gender or "").strip().lower(), 0)
        rcid = RACE_MAP.get((race or "").strip().lower(), 0)
        if rcid == 0:
            rcid = get_cid(lookup, "Race", race or "")
        ecid = ETHNICITY_MAP.get((ethnicity or "").strip().lower(), 0)

        conn.execute(
            "UPDATE person"
            " SET gender_concept_id=?, race_concept_id=?, ethnicity_concept_id=?"
            " WHERE person_id=?",
            (gcid, rcid, ecid, pid),
        )
        if gcid or rcid or ecid:
            updated += 1
    conn.commit()
    print(f"    {updated}/{len(rows)} rows updated.")


def update_visits(conn, lookup):
    print("\n  [visit_occurrence] Updating visit / type concept ids ...")
    rows = conn.execute(
        "SELECT visit_occurrence_id, visit_source_value FROM visit_occurrence"
    ).fetchall()

    for vid, vsv in rows:
        key = (vsv or "").strip().lower().replace(" ", "")
        vcid = VISIT_MAP.get(key, 9202)
        conn.execute(
            "UPDATE visit_occurrence"
            " SET visit_concept_id=?, visit_type_concept_id=?"
            " WHERE visit_occurrence_id=?",
            (vcid, TYPE_CONCEPT["visit"], vid),
        )
    conn.commit()
    print(f"    {len(rows)} rows updated.")


def update_conditions(conn, lookup):
    print("\n  [condition_occurrence] SNOMED / ICD10CM ...")
    rows = conn.execute(
        "SELECT condition_occurrence_id, condition_source_value"
        " FROM condition_occurrence WHERE condition_concept_id = 0"
    ).fetchall()

    mapped = 0
    for coid, code in rows:
        cid = get_cid(lookup, "SNOMED", code) or get_cid(lookup, "ICD10CM", code)
        conn.execute(
            "UPDATE condition_occurrence"
            " SET condition_concept_id=?, condition_type_concept_id=?"
            " WHERE condition_occurrence_id=?",
            (cid, TYPE_CONCEPT["condition"], coid),
        )
        if cid:
            mapped += 1
    conn.commit()
    pct = round(mapped / len(rows) * 100, 1) if rows else 0
    print(f"    {mapped}/{len(rows)} mapped ({pct}%).")


def update_drugs(conn, lookup):
    print("\n  [drug_exposure] RxNorm ...")
    rows = conn.execute(
        "SELECT drug_exposure_id, drug_source_value"
        " FROM drug_exposure WHERE drug_concept_id = 0"
    ).fetchall()

    mapped = 0
    for deid, code in rows:
        cid = (get_cid(lookup, "RxNorm", code)
               or get_cid(lookup, "RxNorm Extension", code))
        conn.execute(
            "UPDATE drug_exposure"
            " SET drug_concept_id=?, drug_type_concept_id=?"
            " WHERE drug_exposure_id=?",
            (cid, TYPE_CONCEPT["drug"], deid),
        )
        if cid:
            mapped += 1
    conn.commit()
    pct = round(mapped / len(rows) * 100, 1) if rows else 0
    print(f"    {mapped}/{len(rows)} mapped ({pct}%).")


def update_procedures(conn, lookup):
    print("\n  [procedure_occurrence] SNOMED / CPT4 / ICD10PCS ...")
    rows = conn.execute(
        "SELECT procedure_occurrence_id, procedure_source_value"
        " FROM procedure_occurrence WHERE procedure_concept_id = 0"
    ).fetchall()

    mapped = 0
    for poid, code in rows:
        cid = (get_cid(lookup, "SNOMED", code)
               or get_cid(lookup, "CPT4", code)
               or get_cid(lookup, "ICD10PCS", code))
        conn.execute(
            "UPDATE procedure_occurrence"
            " SET procedure_concept_id=?, procedure_type_concept_id=?"
            " WHERE procedure_occurrence_id=?",
            (cid, TYPE_CONCEPT["procedure"], poid),
        )
        if cid:
            mapped += 1
    conn.commit()
    pct = round(mapped / len(rows) * 100, 1) if rows else 0
    print(f"    {mapped}/{len(rows)} mapped ({pct}%).")


def update_measurements(conn, lookup):
    print("\n  [measurement] LOINC ...")
    rows = conn.execute(
        "SELECT measurement_id, measurement_source_value"
        " FROM measurement WHERE measurement_concept_id = 0"
    ).fetchall()

    mapped = 0
    for mid, code in rows:
        cid = get_cid(lookup, "LOINC", code)
        conn.execute(
            "UPDATE measurement"
            " SET measurement_concept_id=?, measurement_type_concept_id=?"
            " WHERE measurement_id=?",
            (cid, TYPE_CONCEPT["measurement"], mid),
        )
        if cid:
            mapped += 1
    conn.commit()
    pct = round(mapped / len(rows) * 100, 1) if rows else 0
    print(f"    {mapped}/{len(rows)} mapped ({pct}%).")


def update_observations(conn, lookup):
    print("\n  [observation] SNOMED / LOINC ...")
    rows = conn.execute(
        "SELECT observation_id, observation_source_value"
        " FROM observation WHERE observation_concept_id = 0"
    ).fetchall()

    mapped = 0
    for oid, code in rows:
        cid = (get_cid(lookup, "SNOMED", code)
               or get_cid(lookup, "LOINC", code))
        conn.execute(
            "UPDATE observation"
            " SET observation_concept_id=?, observation_type_concept_id=?"
            " WHERE observation_id=?",
            (cid, TYPE_CONCEPT["observation"], oid),
        )
        if cid:
            mapped += 1
    conn.commit()
    pct = round(mapped / len(rows) * 100, 1) if rows else 0
    print(f"    {mapped}/{len(rows)} mapped ({pct}%).")


def print_coverage(conn):
    sep = "-" * 65
    print(f"\n{sep}")
    print("  CONCEPT COVERAGE SUMMARY")
    print(sep)
    checks = [
        ("person",             "gender_concept_id"),
        ("visit_occurrence",   "visit_concept_id"),
        ("condition_occurrence","condition_concept_id"),
        ("drug_exposure",      "drug_concept_id"),
        ("procedure_occurrence","procedure_concept_id"),
        ("measurement",        "measurement_concept_id"),
        ("observation",        "observation_concept_id"),
    ]
    for table, col in checks:
        total  = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        mapped = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} > 0"
        ).fetchone()[0]
        pct = round(mapped / total * 100, 1) if total else 0
        bar = ">" if pct > 80 else ("~" if pct > 40 else "!")
        print(f"  [{bar}] {table}.{col:<32s}  {pct:>5.1f}%  ({mapped}/{total})")
    print(sep)


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    print(f"Connecting to {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH)

    print("\nLoading Athena vocabulary ...")
    lookup = load_concept_lookup(VOCAB_DIR)

    update_person(conn, lookup)
    update_visits(conn, lookup)
    update_conditions(conn, lookup)
    update_drugs(conn, lookup)
    update_procedures(conn, lookup)
    update_measurements(conn, lookup)
    update_observations(conn, lookup)

    print_coverage(conn)
    conn.close()
    print("\nDone.")
