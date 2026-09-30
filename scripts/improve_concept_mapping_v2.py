# scripts/improve_concept_mapping_v2.py
"""
Improved concept mapping using text-based lookup against Athena vocabulary.
Matches source_value strings to concept_name in the CONCEPT table.
"""

import sqlite3
import csv
import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH   = Path("D:/projects/EHR/omop_cdm.db")
VOCAB_DIR = Path("D:/projects/EHR/vocab")   # adjust if your vocab folder differs

# ── Load Athena CONCEPT.csv into a lookup dict ─────────────────────────────────
def load_concept_lookup(vocab_dir: Path) -> dict:
    """
    Returns: { normalized_name: (concept_id, domain_id, vocabulary_id, concept_code) }
    Priority: standard concepts only (standard_concept == 'S').
    """
    concept_file = vocab_dir / "CONCEPT.csv"
    lookup = {}
    print(f"Loading CONCEPT.csv from {concept_file} ...")
    with open(concept_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("standard_concept") != "S":
                continue
            name_key = row["concept_name"].strip().lower()
            # keep first match (standard concepts are deduplicated by name in most cases)
            if name_key not in lookup:
                lookup[name_key] = (
                    int(row["concept_id"]),
                    row["domain_id"],
                    row["vocabulary_id"],
                    row["concept_code"],
                )
    print(f"  Loaded {len(lookup):,} standard concepts.")
    return lookup


# ── Strip SNOMED qualifier suffixes like "(disorder)", "(procedure)" etc. ──────
import re
_QUALIFIER_RE = re.compile(r"\s*\([^)]+\)\s*$")

def normalize(s: str) -> str:
    s = s.strip().lower()
    s = _QUALIFIER_RE.sub("", s)   # remove "(disorder)", "(procedure)", etc.
    return s.strip()


# ── Map one table ──────────────────────────────────────────────────────────────
def map_table(conn, table: str, src_col: str, concept_col: str, lookup: dict):
    cursor = conn.execute(
        f"SELECT DISTINCT {src_col} FROM {table} "
        f"WHERE {src_col} IS NOT NULL AND {src_col} != ''"
    )
    source_values = [row[0] for row in cursor.fetchall()]

    mapped = 0
    unmapped_examples = []

    for sv in source_values:
        key         = normalize(sv)
        key_raw     = sv.strip().lower()          # also try without stripping qualifier

        match = lookup.get(key) or lookup.get(key_raw)

        if match:
            concept_id = match[0]
            conn.execute(
                f"UPDATE {table} SET {concept_col} = ? WHERE {src_col} = ?",
                (concept_id, sv),
            )
            mapped += 1
        else:
            if len(unmapped_examples) < 5:
                unmapped_examples.append(sv)

    conn.commit()
    total = len(source_values)
    pct   = 100 * mapped / total if total else 0
    print(f"  [{table}] {mapped}/{total} mapped ({pct:.1f}%)")
    if unmapped_examples:
        print(f"    Unmapped examples: {unmapped_examples}")
    return mapped, total


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")
    if not VOCAB_DIR.exists():
        raise FileNotFoundError(f"Vocab dir not found: {VOCAB_DIR}")

    lookup = load_concept_lookup(VOCAB_DIR)

    conn = sqlite3.connect(DB_PATH)

    tables = [
        ("condition_occurrence",  "condition_source_value",   "condition_concept_id"),
        ("drug_exposure",         "drug_source_value",        "drug_concept_id"),
        ("procedure_occurrence",  "procedure_source_value",   "procedure_concept_id"),
        ("measurement",           "measurement_source_value", "measurement_concept_id"),
        ("observation",           "observation_source_value", "observation_concept_id"),
    ]

    print("\n=== Concept Mapping ===\n")
    total_mapped = total_all = 0
    for table, src_col, concept_col in tables:
        m, t = map_table(conn, table, src_col, concept_col, lookup)
        total_mapped += m
        total_all    += t

    conn.close()

    overall = 100 * total_mapped / total_all if total_all else 0
    print(f"\nOverall: {total_mapped}/{total_all} ({overall:.1f}%) mapped.")


if __name__ == "__main__":
    main()
