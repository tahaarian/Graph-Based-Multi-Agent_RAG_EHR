# scripts/diagnose_mapping.py
import sqlite3
from pathlib import Path

DB_PATH = Path("D:/projects/EHR/omop_cdm.db")
conn = sqlite3.connect(DB_PATH)

print("=== SAMPLE source_values ===\n")

tables = [
    ("condition_occurrence", "condition_source_value"),
    ("drug_exposure",        "drug_source_value"),
    ("procedure_occurrence", "procedure_source_value"),
    ("measurement",          "measurement_source_value"),
    ("observation",          "observation_source_value"),
]

for table, col in tables:
    rows = conn.execute(
        f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != '' LIMIT 5"
    ).fetchall()
    print(f"[{table}]")
    for r in rows:
        print("   ", r[0])
    print()

conn.close()
print("Done.")
