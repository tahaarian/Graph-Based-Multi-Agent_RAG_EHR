"""
improve_concept_mapping_v3.py

Fixes vs v2:
  - Auto-detects delimiter for CONCEPT.csv (tab) and CDM tables (comma)
  - Builds dual lookup: vocab_by_code  (concept_code  → concept_id)
                         vocab_by_name  (concept_name  → concept_id)
  - map_source_value tries code first, then name  → recovers SNOMED/RxNorm numeric source values
"""

import csv
import logging
import sys
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────
BASE_DIR   = Path(r"D:\projects\EHR\Graph-Based-Multi-Agent_RAG_EHR")
VOCAB_DIR  = Path("D:/projects/EHR/vocab") 
OMOP_DIR   = BASE_DIR / "data" / "processed" / "omop_cdm"
OUT_DIR    = BASE_DIR / "data" / "processed"

# Tables to map: { csv_filename: (source_value_col, target_concept_id_col) }
TABLE_CONFIG = {
    "condition_occurrence.csv":  ("condition_source_value",   "condition_concept_id"),
    "drug_exposure.csv":         ("drug_source_value",        "drug_concept_id"),
    "procedure_occurrence.csv":  ("procedure_source_value",   "procedure_concept_id"),
    "measurement.csv":           ("measurement_source_value", "measurement_concept_id"),
    "observation.csv":           ("observation_source_value", "observation_concept_id"),
}

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / "mapping_v3.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def detect_delimiter(path: Path) -> str:
    """Peek at the first line and decide between tab and comma."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        first = fh.readline()
    return "\t" if first.count("\t") > first.count(",") else ","


def load_vocab(vocab_dir: Path) -> tuple[dict, dict]:
    """
    Parse CONCEPT.csv and return two dicts:
        vocab_by_code : { concept_code  (str) → concept_id (int) }
        vocab_by_name : { concept_name  (lower) → concept_id (int) }
    """
    concept_file = vocab_dir / "CONCEPT.csv"
    if not concept_file.exists():
        raise FileNotFoundError(f"CONCEPT.csv not found in {vocab_dir}")

    sep = detect_delimiter(concept_file)
    log.info("CONCEPT.csv delimiter detected: %r", sep)

    vocab_by_code: dict[str, int] = {}
    vocab_by_name: dict[str, int] = {}
    skipped = 0

    with concept_file.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=sep)
        for row in reader:
            raw_id   = row.get("concept_id",   "").strip()
            raw_code = row.get("concept_code",  "").strip()
            raw_name = row.get("concept_name",  "").strip()

            if not raw_id:
                skipped += 1
                continue
            try:
                cid = int(raw_id)
            except ValueError:
                skipped += 1
                continue

            if raw_code:
                vocab_by_code[raw_code] = cid
            if raw_name:
                vocab_by_name[raw_name.lower()] = cid

    log.info(
        "Vocabulary loaded — by code: %d  |  by name: %d  |  skipped rows: %d",
        len(vocab_by_code), len(vocab_by_name), skipped,
    )
    return vocab_by_code, vocab_by_name


def map_source_value(sv: str,
                     vocab_by_code: dict,
                     vocab_by_name: dict) -> int | None:
    """
    Resolution order:
      1. Exact match on concept_code  (handles SNOMED / RxNorm numeric strings)
      2. Case-insensitive match on concept_name
    """
    sv = sv.strip()
    if not sv:
        return None

    # 1️⃣  code-based lookup (most CDM source_values are numeric SNOMED/RxNorm codes)
    if sv in vocab_by_code:
        return vocab_by_code[sv]

    # 2️⃣  name-based lookup (fallback for string descriptions)
    sv_lower = sv.lower()
    if sv_lower in vocab_by_name:
        return vocab_by_name[sv_lower]

    return None


# ─── Per-table processing ──────────────────────────────────────────────────────
def process_table(
    table_path: Path,
    src_col: str,
    tgt_col: str,
    vocab_by_code: dict,
    vocab_by_name: dict,
    out_dir: Path,
) -> dict:
    """
    Read a CDM table, map source values, write enriched CSV to out_dir.
    Returns a stats dict.
    """
    if not table_path.exists():
        log.warning("Table not found, skipping: %s", table_path)
        return {"file": table_path.name, "total": 0, "mapped": 0, "coverage": 0.0}

    sep = detect_delimiter(table_path)
    rows = []
    total = mapped = already_set = 0

    with table_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=sep)
        if reader.fieldnames is None:
            log.warning("Empty or header-less file: %s", table_path.name)
            return {"file": table_path.name, "total": 0, "mapped": 0, "coverage": 0.0}

        fieldnames = list(reader.fieldnames)
        # Ensure target column exists in output
        if tgt_col not in fieldnames:
            fieldnames.append(tgt_col)

        for row in reader:
            total += 1
            sv = row.get(src_col, "") or ""

            existing = row.get(tgt_col, "") or ""
            try:
                existing_id = int(existing)
            except (ValueError, TypeError):
                existing_id = 0

            if existing_id and existing_id != 0:
                # already has a valid concept_id
                already_set += 1
                mapped += 1
                rows.append(row)
                continue

            cid = map_source_value(sv, vocab_by_code, vocab_by_name)
            if cid is not None:
                row[tgt_col] = str(cid)
                mapped += 1
            else:
                row[tgt_col] = row.get(tgt_col, "0") or "0"

            rows.append(row)

    coverage = (mapped / total * 100) if total else 0.0

    # Write enriched output
    out_path = out_dir / table_path.name
    out_dir.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info(
        "%-35s  total=%6d  mapped=%6d  already_set=%6d  coverage=%.1f%%",
        table_path.name, total, mapped, already_set, coverage,
    )
    return {
        "file":        table_path.name,
        "total":       total,
        "mapped":      mapped,
        "already_set": already_set,
        "unmapped":    total - mapped,
        "coverage":    coverage,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 60)
    log.info("improve_concept_mapping_v3  —  starting")
    log.info("VOCAB_DIR : %s", VOCAB_DIR)
    log.info("OMOP_DIR  : %s", OMOP_DIR)
    log.info("OUT_DIR   : %s", OUT_DIR)
    log.info("=" * 60)

    # 1. Load vocabulary
    vocab_by_code, vocab_by_name = load_vocab(VOCAB_DIR)

    # 2. Process each table
    results = []
    for filename, (src_col, tgt_col) in TABLE_CONFIG.items():
        stats = process_table(
            table_path    = OMOP_DIR / filename,
            src_col       = src_col,
            tgt_col       = tgt_col,
            vocab_by_code = vocab_by_code,
            vocab_by_name = vocab_by_name,
            out_dir       = OUT_DIR,
        )
        results.append(stats)

    # 3. Summary
    grand_total  = sum(r["total"]  for r in results)
    grand_mapped = sum(r["mapped"] for r in results)
    grand_cov    = (grand_mapped / grand_total * 100) if grand_total else 0.0

    log.info("")
    log.info("─" * 60)
    log.info("  CONCEPT COVERAGE SUMMARY (v3)")
    log.info("─" * 60)
    for r in results:
        log.info(
            "  %-35s  %6d / %-6d  (%.1f%%)",
            r["file"], r["mapped"], r["total"], r["coverage"],
        )
    log.info("─" * 60)
    log.info(
        "  %-35s  %6d / %-6d  (%.1f%%)",
        "TOTAL", grand_mapped, grand_total, grand_cov,
    )
    log.info("─" * 60)
    log.info("Enriched tables written to: %s", OUT_DIR)
    log.info("Done.")


if __name__ == "__main__":
    main()
