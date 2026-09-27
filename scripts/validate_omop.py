"""
OMOP CDM Data Validation Script
Checks: referential integrity, concept coverage, date consistency, demographics
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("D:/projects/EHR/omop_cdm.db")

CLINICAL_TABLES = [
    "visit_occurrence",
    "condition_occurrence",
    "drug_exposure",
    "procedure_occurrence",
    "measurement",
    "observation",
]

CONCEPT_COLUMNS = {
    "condition_occurrence":  ["condition_concept_id", "condition_type_concept_id"],
    "drug_exposure":         ["drug_concept_id", "drug_type_concept_id"],
    "procedure_occurrence":  ["procedure_concept_id", "procedure_type_concept_id"],
    "measurement":           ["measurement_concept_id", "measurement_type_concept_id"],
    "observation":           ["observation_concept_id", "observation_type_concept_id"],
    "visit_occurrence":      ["visit_concept_id", "visit_type_concept_id"],
    "person":                ["gender_concept_id", "race_concept_id", "ethnicity_concept_id"],
}


def run_query(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return cur.fetchall()


def scalar(conn, sql, params=()):
    return run_query(conn, sql, params)[0][0]


# ── 1. Referential integrity ──────────────────────────────────────────────────
def check_referential_integrity(conn):
    results = {}
    total_persons = scalar(conn, "SELECT COUNT(DISTINCT person_id) FROM person")

    for table in CLINICAL_TABLES:
        orphans = scalar(conn, f"""
            SELECT COUNT(*) FROM {table}
            WHERE person_id NOT IN (SELECT person_id FROM person)
        """)
        results[table] = {"orphaned_rows": orphans}

    # visit FK on condition / drug / procedure
    for table, fk_col in [
        ("condition_occurrence",  "visit_occurrence_id"),
        ("drug_exposure",         "visit_occurrence_id"),
        ("procedure_occurrence",  "visit_occurrence_id"),
        ("measurement",           "visit_occurrence_id"),
        ("observation",           "visit_occurrence_id"),
    ]:
        orphan_visits = scalar(conn, f"""
            SELECT COUNT(*) FROM {table}
            WHERE {fk_col} IS NOT NULL
              AND {fk_col} NOT IN (SELECT visit_occurrence_id FROM visit_occurrence)
        """)
        results[table][f"orphaned_{fk_col}"] = orphan_visits

    return total_persons, results


# ── 2. Concept-ID coverage ────────────────────────────────────────────────────
def check_concept_coverage(conn):
    results = {}
    for table, cols in CONCEPT_COLUMNS.items():
        total = scalar(conn, f"SELECT COUNT(*) FROM {table}")
        if total == 0:
            continue
        for col in cols:
            zero = scalar(conn, f"""
                SELECT COUNT(*) FROM {table}
                WHERE {col} IS NULL OR {col} = 0
            """)
            pct_mapped = round((1 - zero / total) * 100, 1)
            results[f"{table}.{col}"] = {
                "total": total,
                "unmapped": zero,
                "mapped_pct": pct_mapped,
            }
    return results


# ── 3. Date consistency ───────────────────────────────────────────────────────
def check_dates(conn):
    results = {}

    # Visit: end before start
    bad_visits = scalar(conn, """
        SELECT COUNT(*) FROM visit_occurrence
        WHERE visit_end_date < visit_start_date
    """)
    date_range = run_query(conn, """
        SELECT MIN(visit_start_date), MAX(visit_end_date) FROM visit_occurrence
    """)[0]
    results["visit_occurrence"] = {
        "date_range": f"{date_range[0]}  →  {date_range[1]}",
        "end_before_start": bad_visits,
    }

    # Conditions outside parent visit window
    bad_cond = scalar(conn, """
        SELECT COUNT(*) FROM condition_occurrence co
        JOIN visit_occurrence vo ON co.visit_occurrence_id = vo.visit_occurrence_id
        WHERE co.condition_start_date < vo.visit_start_date
           OR co.condition_start_date > vo.visit_end_date
    """)
    results["condition_occurrence"] = {"dates_outside_visit_window": bad_cond}

    return results


# ── 4. Demographics ───────────────────────────────────────────────────────────
def check_demographics(conn):
    row = run_query(conn, """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN year_of_birth IS NULL THEN 1 ELSE 0 END) as null_birth_year,
            MIN(year_of_birth), MAX(year_of_birth),
            SUM(CASE WHEN gender_concept_id = 0 OR gender_concept_id IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN race_concept_id   = 0 OR race_concept_id   IS NULL THEN 1 ELSE 0 END),
            COUNT(DISTINCT gender_concept_id)
        FROM person
    """)[0]
    return {
        "total": row[0],
        "null_birth_year": row[1],
        "birth_year_range": f"{row[2]} – {row[3]}",
        "unmapped_gender": row[4],
        "unmapped_race": row[5],
        "distinct_gender_concept_ids": row[6],
    }


# ── 5. Duplicate detection ────────────────────────────────────────────────────
def check_duplicates(conn):
    results = {}

    dup_persons = scalar(conn, """
        SELECT COUNT(*) FROM (
            SELECT person_source_value, COUNT(*) c
            FROM person GROUP BY person_source_value HAVING c > 1
        )
    """)
    results["person_duplicates"] = dup_persons

    for table, key_cols in [
        ("visit_occurrence",     "person_id, visit_start_date, visit_concept_id"),
        ("condition_occurrence", "person_id, condition_start_date, condition_source_value"),
        ("drug_exposure",        "person_id, drug_exposure_start_date, drug_source_value"),
    ]:
        dups = scalar(conn, f"""
            SELECT COUNT(*) FROM (
                SELECT {key_cols}, COUNT(*) c
                FROM {table} GROUP BY {key_cols} HAVING c > 1
            )
        """)
        results[f"{table}_duplicates"] = dups

    return results


# ── Report ────────────────────────────────────────────────────────────────────
def print_report(n_persons, ri, cc, dc, demo, dupl):
    sep = "=" * 62

    print(f"\n{sep}")
    print("  OMOP CDM VALIDATION REPORT")
    print(sep)

    # 1. Referential integrity
    print("\n[1] REFERENTIAL INTEGRITY")
    all_ok = True
    for table, info in ri.items():
        issues = {k: v for k, v in info.items() if v > 0}
        if issues:
            all_ok = False
            print(f"  FAIL  {table}: {issues}")
        else:
            print(f"  OK    {table}")
    if all_ok:
        print("  All FK checks passed.")

    # 2. Concept coverage
    print("\n[2] CONCEPT COVERAGE  (0 = still unmapped)")
    for key, info in cc.items():
        bar = "▓" if info["mapped_pct"] > 0 else "░"
        print(f"  {bar}  {key:<50s}  {info['mapped_pct']:>5.1f}%  "
              f"({info['total'] - info['unmapped']}/{info['total']})")

    # 3. Dates
    print("\n[3] DATE CONSISTENCY")
    for tbl, info in dc.items():
        for k, v in info.items():
            status = "OK" if v == 0 or "range" in k else ("WARN" if v > 0 else "OK")
            print(f"  {status}  {tbl}.{k}: {v}")

    # 4. Demographics
    print("\n[4] DEMOGRAPHICS")
    for k, v in demo.items():
        print(f"  {k}: {v}")

    # 5. Duplicates
    print("\n[5] DUPLICATE CHECK")
    for k, v in dupl.items():
        print(f"  {'WARN' if v > 0 else 'OK'}  {k}: {v}")

    print(f"\n{sep}\n")

    # Summary
    total_issues = (
        sum(sum(v.values()) for v in ri.values())
        + dc["visit_occurrence"]["end_before_start"]
        + sum(v for k, v in dupl.items() if v > 0)
    )
    unmapped_pct = {k: v["mapped_pct"] for k, v in cc.items() if "concept_id" in k and "type" not in k}
    avg_mapped = round(sum(unmapped_pct.values()) / len(unmapped_pct), 1) if unmapped_pct else 0

    print(f"  Total FK/date issues : {total_issues}")
    print(f"  Avg concept coverage : {avg_mapped}%  (target: >80% after vocab mapping)")
    print(sep)


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}")
        sys.exit(1)

    print(f"Connecting to {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("Checking referential integrity ...")
    n_persons, ri = check_referential_integrity(conn)

    print("Checking concept coverage ...")
    cc = check_concept_coverage(conn)

    print("Checking date consistency ...")
    dc = check_dates(conn)

    print("Checking demographics ...")
    demo = check_demographics(conn)

    print("Checking duplicates ...")
    dupl = check_duplicates(conn)

    conn.close()

    print_report(n_persons, ri, cc, dc, demo, dupl)
