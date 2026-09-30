# diagnose_v3.py  --  بذارش کنار v3 و اجرا کن
import csv
from pathlib import Path

VOCAB_DIR = Path("D:/projects/EHR/vocab")
DATA_DIR  = Path("D:/projects/EHR/Graph-Based-Multi-Agent_RAG_EHR/data/processed/omop_cdm")

# --- بررسی CONCEPT.csv ---
concept_file = VOCAB_DIR / "CONCEPT.csv"
with open(concept_file, encoding="utf-8", newline="") as f:
    raw_line = f.readline()
    print("=== CONCEPT.csv first raw line (first 200 chars) ===")
    print(repr(raw_line[:200]))
    print()
    # تشخیص delimiter
    tab_count   = raw_line.count("\t")
    comma_count = raw_line.count(",")
    print(f"Tabs: {tab_count}  |  Commas: {comma_count}")
    sep = "\t" if tab_count > comma_count else ","
    print(f"Detected separator: {repr(sep)}")
    print()
    f.seek(0)
    reader = csv.DictReader(f, delimiter=sep)
    row = next(reader)
    print("Columns:", list(row.keys()))
    print("Sample concept_name:", repr(row.get("concept_name", "MISSING")))
    print()

# --- بررسی condition_occurrence.csv ---
cond_file = DATA_DIR / "condition_occurrence.csv"
with open(cond_file, encoding="utf-8", newline="") as f:
    raw_line = f.readline()
    print("=== condition_occurrence.csv first raw line ===")
    print(repr(raw_line[:300]))
    print()
    tab_count   = raw_line.count("\t")
    comma_count = raw_line.count(",")
    sep = "\t" if tab_count > comma_count else ","
    f.seek(0)
    reader = csv.DictReader(f, delimiter=sep)
    row = next(reader)
    print("Columns:", list(row.keys()))
    print("Sample condition_source_value:", repr(row.get("condition_source_value", "MISSING")))
