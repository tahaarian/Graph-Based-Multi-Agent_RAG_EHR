"""
scripts/ingest_patients.py

Ingests Synthea CSV data into Neo4j as a Dynamic Heterogeneous Graph.
Node types: Patient, Visit, Condition, Medication, Observation, Procedure
Edge types: HAS_VISIT, HAS_CONDITION, HAS_MEDICATION, HAS_OBSERVATION,
            HAS_PROCEDURE, CO_OCCURS_WITH, TEMPORALLY_FOLLOWS
"""

import os
import logging
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
DATA_DIR       = Path(os.getenv("SYNTHEA_DATA_DIR", "data/raw/synthea"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

BATCH_SIZE = 500  # rows per Cypher transaction

# ── Driver ────────────────────────────────────────────────────────────────────
class Neo4jIngester:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

    def run_batch(self, query: str, rows: list[dict]) -> None:
        with self.driver.session() as session:
            session.execute_write(lambda tx: tx.run(query, rows=rows))

    # ── Constraints & Indexes ──────────────────────────────────────────────
    def create_schema(self) -> None:
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Patient)     REQUIRE p.patient_id   IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Visit)       REQUIRE v.visit_id     IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Condition)   REQUIRE c.condition_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Medication)  REQUIRE m.medication_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Observation) REQUIRE o.observation_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (pr:Procedure)  REQUIRE pr.procedure_id IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (p:Patient)     ON (p.birthdate)",
            "CREATE INDEX IF NOT EXISTS FOR (v:Visit)       ON (v.start)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Condition)   ON (c.start, c.code)",
            "CREATE INDEX IF NOT EXISTS FOR (m:Medication)  ON (m.start, m.code)",
            "CREATE INDEX IF NOT EXISTS FOR (o:Observation) ON (o.date,  o.code)",
            "CREATE INDEX IF NOT EXISTS FOR (pr:Procedure)  ON (pr.date, pr.code)",
        ]
        with self.driver.session() as session:
            for stmt in constraints + indexes:
                session.run(stmt)
        log.info("Schema constraints and indexes applied.")

    # ── Patients ───────────────────────────────────────────────────────────
    def ingest_patients(self, df: pd.DataFrame) -> None:
        query = """
        UNWIND $rows AS row
        MERGE (p:Patient {patient_id: row.Id})
        SET   p.birthdate  = row.BIRTHDATE,
              p.deathdate  = row.DEATHDATE,
              p.gender     = row.GENDER,
              p.race        = row.RACE,
              p.ethnicity  = row.ETHNICITY,
              p.city        = row.CITY,
              p.state       = row.STATE
        """
        self._run_in_batches("Patients", df, query)

    # ── Encounters (Visits) ────────────────────────────────────────────────
    def ingest_encounters(self, df: pd.DataFrame) -> None:
        query = """
        UNWIND $rows AS row
        MATCH  (p:Patient {patient_id: row.PATIENT})
        MERGE  (v:Visit   {visit_id:   row.Id})
        SET    v.start             = row.START,
               v.stop              = row.STOP,
               v.encounter_class   = row.ENCOUNTERCLASS,
               v.description       = row.DESCRIPTION,
               v.reason_code       = row.REASONCODE,
               v.reason_description = row.REASONDESCRIPTION
        MERGE  (p)-[:HAS_VISIT {start: row.START}]->(v)
        """
        self._run_in_batches("Encounters", df, query)

    # ── Conditions ────────────────────────────────────────────────────────
    def ingest_conditions(self, df: pd.DataFrame) -> None:
        query = """
        UNWIND $rows AS row
        MATCH  (p:Patient {patient_id: row.PATIENT})
        MATCH  (v:Visit   {visit_id:   row.ENCOUNTER})
        MERGE  (c:Condition {condition_id: row.PATIENT + '_' + row.CODE + '_' + row.START})
        SET    c.code        = row.CODE,
               c.description = row.DESCRIPTION,
               c.start        = row.START,
               c.stop         = row.STOP,
               c.system       = 'SNOMED-CT'
        MERGE  (p)-[:HAS_CONDITION {start: row.START}]->(c)
        MERGE  (v)-[:CO_OCCURS_WITH]->(c)
        """
        self._run_in_batches("Conditions", df, query)

    # ── Medications ───────────────────────────────────────────────────────
    def ingest_medications(self, df: pd.DataFrame) -> None:
        query = """
        UNWIND $rows AS row
        MATCH  (p:Patient {patient_id: row.PATIENT})
        MATCH  (v:Visit   {visit_id:   row.ENCOUNTER})
        MERGE  (m:Medication {medication_id: row.PATIENT + '_' + row.CODE + '_' + row.START})
        SET    m.code        = row.CODE,
               m.description = row.DESCRIPTION,
               m.start        = row.START,
               m.stop         = row.STOP,
               m.base_cost    = toFloat(row.BASE_COST),
               m.dispenses    = toInteger(row.DISPENSES),
               m.system       = 'RxNorm'
        MERGE  (p)-[:HAS_MEDICATION {start: row.START}]->(m)
        MERGE  (v)-[:CO_OCCURS_WITH]->(m)
        """
        self._run_in_batches("Medications", df, query)

    # ── Observations ──────────────────────────────────────────────────────
    def ingest_observations(self, df: pd.DataFrame) -> None:
        query = """
        UNWIND $rows AS row
        MATCH  (p:Patient {patient_id: row.PATIENT})
        MATCH  (v:Visit   {visit_id:   row.ENCOUNTER})
        MERGE  (o:Observation {
            observation_id: row.PATIENT + '_' + row.CODE + '_' + row.DATE
        })
        SET    o.code        = row.CODE,
               o.description = row.DESCRIPTION,
               o.date         = row.DATE,
               o.value        = row.VALUE,
               o.units        = row.UNITS,
               o.type         = row.TYPE,
               o.system       = 'LOINC'
        MERGE  (p)-[:HAS_OBSERVATION {date: row.DATE}]->(o)
        MERGE  (v)-[:CO_OCCURS_WITH]->(o)
        """
        self._run_in_batches("Observations", df, query)

    # ── Procedures ────────────────────────────────────────────────────────
    def ingest_procedures(self, df: pd.DataFrame) -> None:
        # Drop rows where required fields are null
        required = ["PATIENT", "CODE", "START", "ENCOUNTER"]
        df = df.dropna(subset=required)

        query = """
        UNWIND $rows AS row
        MATCH  (p:Patient {patient_id: row.PATIENT})
        MATCH  (v:Visit   {visit_id:   row.ENCOUNTER})
        MERGE  (pr:Procedure {
            procedure_id: row.PATIENT + '_' + row.CODE + '_' + row.START
        })
        SET    pr.code        = row.CODE,
            pr.description = row.DESCRIPTION,
            pr.date         = row.START,
            pr.stop         = row.STOP,
            pr.base_cost    = toFloat(row.BASE_COST),
            pr.reason_code  = row.REASONCODE,
            pr.system       = 'SNOMED-CT'
        MERGE  (p)-[:HAS_PROCEDURE {date: row.START}]->(pr)
        MERGE  (v)-[:CO_OCCURS_WITH]->(pr)
        """
        self._run_in_batches("Procedures", df, query)

    # ── Temporal succession edges ──────────────────────────────────────────
    def build_temporal_edges(self) -> None:
        query = """
        MATCH (p:Patient)-[:HAS_VISIT]->(v:Visit)
        WITH  p, v ORDER BY v.start
        WITH  p, collect(v) AS visits
        UNWIND range(0, size(visits) - 2) AS i
        WITH   visits[i] AS v1, visits[i+1] AS v2
        MERGE  (v1)-[r:TEMPORALLY_FOLLOWS]->(v2)
        SET    r.interval_days = duration.between(
                datetime(v1.start), datetime(v2.start)
            ).days
        """
        with self.driver.session() as session:
            result = session.run(query)
            summary = result.consume()
            log.info(
                "Temporal edges created: %d relationships",
                summary.counters.relationships_created,
            )

    # ── Helpers ───────────────────────────────────────────────────────────
    def _run_in_batches(
        self, label: str, df: pd.DataFrame, query: str
    ) -> None:
        records = df.where(pd.notna(df), None).to_dict("records")
        total   = len(records)
        created = 0
        for start in tqdm(range(0, total, BATCH_SIZE), desc=label):
            batch = records[start : start + BATCH_SIZE]
            self.run_batch(query, batch)
            created += len(batch)
        log.info("%s: %d rows ingested.", label, created)


# ── CSV loaders ───────────────────────────────────────────────────────────────
def load_csv(filename: str) -> pd.DataFrame:
    path = DATA_DIR / filename
    if not path.exists():
        log.warning("File not found, skipping: %s", path)
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, low_memory=False)
    log.info("Loaded %s  →  %d rows, %d columns", filename, *df.shape)
    return df


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ingester = Neo4jIngester()
    try:
        log.info("Creating schema constraints and indexes …")
        ingester.create_schema()

        log.info("Ingesting Patients …")
        ingester.ingest_patients(load_csv("patients.csv"))

        log.info("Ingesting Encounters (Visits) …")
        ingester.ingest_encounters(load_csv("encounters.csv"))

        log.info("Ingesting Conditions …")
        ingester.ingest_conditions(load_csv("conditions.csv"))

        log.info("Ingesting Medications …")
        ingester.ingest_medications(load_csv("medications.csv"))

        log.info("Ingesting Observations …")
        ingester.ingest_observations(load_csv("observations.csv"))

        log.info("Ingesting Procedures …")
        ingester.ingest_procedures(load_csv("procedures.csv"))

        log.info("Building temporal succession edges …")
        ingester.build_temporal_edges()

        log.info("✓ Ingestion complete.")
    finally:
        ingester.close()


if __name__ == "__main__":
    main()
