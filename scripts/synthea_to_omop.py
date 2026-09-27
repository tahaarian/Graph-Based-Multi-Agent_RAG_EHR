# scripts/synthea_to_omop.py
"""
Synthea CSV to OMOP CDM v5.4 Converter
Converts Synthea-generated CSV files to OMOP Common Data Model format
Stores in SQLite for prototyping (can be migrated to PostgreSQL/Neo4j later)
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging
from typing import Dict, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SyntheaToOMOP:
    """Converts Synthea CSV files to OMOP CDM v5.4"""
    
    def __init__(self, synthea_dir: Path, output_db: Path):
        self.synthea_dir = Path(synthea_dir)
        self.output_db = Path(output_db)
        self.conn: Optional[sqlite3.Connection] = None
        
        # ID mappings for foreign keys
        self.person_id_map: Dict[str, int] = {}
        self.visit_id_map: Dict[str, int] = {}
        self.provider_id_map: Dict[str, int] = {}
        self.care_site_id_map: Dict[str, int] = {}
        
    def __enter__(self):
        """Context manager entry"""
        self.conn = sqlite3.connect(self.output_db)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.conn:
            self.conn.close()
    
    def create_omop_tables(self):
        """Create OMOP CDM v5.4 core tables"""
        logger.info("Creating OMOP CDM v5.4 tables...")
        
        cursor = self.conn.cursor()
        
        # PERSON table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS person (
                person_id INTEGER PRIMARY KEY,
                gender_concept_id INTEGER,
                year_of_birth INTEGER,
                month_of_birth INTEGER,
                day_of_birth INTEGER,
                birth_datetime TEXT,
                race_concept_id INTEGER,
                ethnicity_concept_id INTEGER,
                person_source_value TEXT,
                gender_source_value TEXT,
                race_source_value TEXT,
                ethnicity_source_value TEXT
            )
        """)
        
        # VISIT_OCCURRENCE table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visit_occurrence (
                visit_occurrence_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                visit_concept_id INTEGER,
                visit_start_date TEXT,
                visit_start_datetime TEXT,
                visit_end_date TEXT,
                visit_end_datetime TEXT,
                visit_type_concept_id INTEGER DEFAULT 44818518,
                provider_id INTEGER,
                care_site_id INTEGER,
                visit_source_value TEXT,
                visit_source_concept_id INTEGER,
                FOREIGN KEY (person_id) REFERENCES person(person_id)
            )
        """)
        
        # CONDITION_OCCURRENCE table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS condition_occurrence (
                condition_occurrence_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                condition_concept_id INTEGER,
                condition_start_date TEXT,
                condition_start_datetime TEXT,
                condition_end_date TEXT,
                condition_end_datetime TEXT,
                condition_type_concept_id INTEGER DEFAULT 32020,
                visit_occurrence_id INTEGER,
                condition_source_value TEXT,
                condition_source_concept_id INTEGER,
                FOREIGN KEY (person_id) REFERENCES person(person_id),
                FOREIGN KEY (visit_occurrence_id) REFERENCES visit_occurrence(visit_occurrence_id)
            )
        """)
        
        # DRUG_EXPOSURE table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drug_exposure (
                drug_exposure_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                drug_concept_id INTEGER,
                drug_exposure_start_date TEXT,
                drug_exposure_start_datetime TEXT,
                drug_exposure_end_date TEXT,
                drug_exposure_end_datetime TEXT,
                drug_type_concept_id INTEGER DEFAULT 38000177,
                visit_occurrence_id INTEGER,
                drug_source_value TEXT,
                drug_source_concept_id INTEGER,
                route_concept_id INTEGER,
                quantity REAL,
                FOREIGN KEY (person_id) REFERENCES person(person_id),
                FOREIGN KEY (visit_occurrence_id) REFERENCES visit_occurrence(visit_occurrence_id)
            )
        """)
        
        # PROCEDURE_OCCURRENCE table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS procedure_occurrence (
                procedure_occurrence_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                procedure_concept_id INTEGER,
                procedure_date TEXT,
                procedure_datetime TEXT,
                procedure_type_concept_id INTEGER DEFAULT 38000275,
                visit_occurrence_id INTEGER,
                procedure_source_value TEXT,
                procedure_source_concept_id INTEGER,
                FOREIGN KEY (person_id) REFERENCES person(person_id),
                FOREIGN KEY (visit_occurrence_id) REFERENCES visit_occurrence(visit_occurrence_id)
            )
        """)
        
        # OBSERVATION table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS observation (
                observation_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                observation_concept_id INTEGER,
                observation_date TEXT,
                observation_datetime TEXT,
                observation_type_concept_id INTEGER DEFAULT 38000280,
                value_as_number REAL,
                value_as_string TEXT,
                value_as_concept_id INTEGER,
                visit_occurrence_id INTEGER,
                observation_source_value TEXT,
                observation_source_concept_id INTEGER,
                unit_source_value TEXT,
                FOREIGN KEY (person_id) REFERENCES person(person_id),
                FOREIGN KEY (visit_occurrence_id) REFERENCES visit_occurrence(visit_occurrence_id)
            )
        """)
        
        # MEASUREMENT table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS measurement (
                measurement_id INTEGER PRIMARY KEY,
                person_id INTEGER,
                measurement_concept_id INTEGER,
                measurement_date TEXT,
                measurement_datetime TEXT,
                measurement_type_concept_id INTEGER DEFAULT 44818702,
                value_as_number REAL,
                value_as_concept_id INTEGER,
                unit_concept_id INTEGER,
                visit_occurrence_id INTEGER,
                measurement_source_value TEXT,
                measurement_source_concept_id INTEGER,
                unit_source_value TEXT,
                FOREIGN KEY (person_id) REFERENCES person(person_id),
                FOREIGN KEY (visit_occurrence_id) REFERENCES visit_occurrence(visit_occurrence_id)
            )
        """)
        
        # PROVIDER table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provider (
                provider_id INTEGER PRIMARY KEY,
                provider_name TEXT,
                specialty_concept_id INTEGER,
                gender_concept_id INTEGER,
                provider_source_value TEXT,
                specialty_source_value TEXT
            )
        """)
        
        # CARE_SITE table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS care_site (
                care_site_id INTEGER PRIMARY KEY,
                care_site_name TEXT,
                care_site_source_value TEXT
            )
        """)
        
        self.conn.commit()
        logger.info("OMOP tables created successfully")
    
    def load_patients(self):
        """Load patients.csv into person table"""
        logger.info("Loading patients...")
        
        csv_path = self.synthea_dir / "patients.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        logger.info(f"Found {len(df)} patients")
        
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            person_id = idx + 1
            self.person_id_map[row['Id']] = person_id
            
            # Parse birthdate
            birth_date = pd.to_datetime(row['BIRTHDATE'])
            
            # Map gender: M = 8507 (Male), F = 8532 (Female)
            gender_concept_id = 8507 if row['GENDER'] == 'M' else 8532
            
            # Map race (simplified)
            race_map = {
                'white': 8527,
                'black': 8516,
                'asian': 8515,
                'native': 8657,
                'other': 8522
            }
            race_concept_id = race_map.get(row['RACE'].lower(), 0)
            
            # Map ethnicity
            ethnicity_map = {
                'hispanic': 38003563,
                'nonhispanic': 38003564
            }
            ethnicity_concept_id = ethnicity_map.get(row['ETHNICITY'].lower(), 0)
            
            cursor.execute("""
                INSERT INTO person (
                    person_id, gender_concept_id, year_of_birth, month_of_birth,
                    day_of_birth, birth_datetime, race_concept_id, ethnicity_concept_id,
                    person_source_value, gender_source_value, race_source_value,
                    ethnicity_source_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                person_id,
                gender_concept_id,
                birth_date.year,
                birth_date.month,
                birth_date.day,
                birth_date.isoformat(),
                race_concept_id,
                ethnicity_concept_id,
                row['Id'],
                row['GENDER'],
                row['RACE'],
                row['ETHNICITY']
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} patients into person table")
    
    def load_providers(self):
        """Load providers.csv into provider table"""
        logger.info("Loading providers...")
        
        csv_path = self.synthea_dir / "providers.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            provider_id = idx + 1
            self.provider_id_map[row['Id']] = provider_id
            
            # Map gender
            gender_concept_id = 8507 if row['GENDER'] == 'M' else 8532
            
            cursor.execute("""
                INSERT INTO provider (
                    provider_id, provider_name, gender_concept_id,
                    provider_source_value, specialty_source_value
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                provider_id,
                row['NAME'],
                gender_concept_id,
                row['Id'],
                row['SPECIALITY']
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} providers")
    
    def load_organizations(self):
        """Load organizations.csv into care_site table"""
        logger.info("Loading organizations...")
        
        csv_path = self.synthea_dir / "organizations.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            care_site_id = idx + 1
            self.care_site_id_map[row['Id']] = care_site_id
            
            cursor.execute("""
                INSERT INTO care_site (
                    care_site_id, care_site_name, care_site_source_value
                ) VALUES (?, ?, ?)
            """, (
                care_site_id,
                row['NAME'],
                row['Id']
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} organizations into care_site")
    
    def load_encounters(self):
        """Load encounters.csv into visit_occurrence table"""
        logger.info("Loading encounters...")
        
        csv_path = self.synthea_dir / "encounters.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        # Visit type mapping (simplified)
        visit_type_map = {
            'ambulatory': 9202,      # Outpatient Visit
            'emergency': 9203,        # Emergency Room Visit
            'inpatient': 9201,        # Inpatient Visit
            'wellness': 9202,         # Outpatient Visit
            'urgentcare': 9203,       # Emergency Room Visit
            'outpatient': 9202        # Outpatient Visit
        }
        
        for idx, row in df.iterrows():
            visit_id = idx + 1
            self.visit_id_map[row['Id']] = visit_id
            
            person_id = self.person_id_map.get(row['PATIENT'])
            if person_id is None:
                continue
            
            provider_id = self.provider_id_map.get(row['PROVIDER']) if pd.notna(row.get('PROVIDER')) else None
            care_site_id = self.care_site_id_map.get(row['ORGANIZATION']) if pd.notna(row.get('ORGANIZATION')) else None
            
            visit_concept_id = visit_type_map.get(row['ENCOUNTERCLASS'].lower(), 0)
            
            start_dt = pd.to_datetime(row['START'])
            end_dt = pd.to_datetime(row['STOP']) if pd.notna(row['STOP']) else start_dt
            
            cursor.execute("""
                INSERT INTO visit_occurrence (
                    visit_occurrence_id, person_id, visit_concept_id,
                    visit_start_date, visit_start_datetime,
                    visit_end_date, visit_end_datetime,
                    visit_type_concept_id, provider_id, care_site_id,
                    visit_source_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                visit_id,
                person_id,
                visit_concept_id,
                start_dt.date().isoformat(),
                start_dt.isoformat(),
                end_dt.date().isoformat(),
                end_dt.isoformat(),
                44818518,  # EHR
                provider_id,
                care_site_id,
                row['ENCOUNTERCLASS']
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} encounters into visit_occurrence")
    
    def load_conditions(self):
        """Load conditions.csv into condition_occurrence table"""
        logger.info("Loading conditions...")
        
        csv_path = self.synthea_dir / "conditions.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            person_id = self.person_id_map.get(row['PATIENT'])
            if person_id is None:
                continue
            
            visit_id = self.visit_id_map.get(row['ENCOUNTER']) if pd.notna(row.get('ENCOUNTER')) else None
            
            start_dt = pd.to_datetime(row['START'])
            end_dt = pd.to_datetime(row['STOP']) if pd.notna(row['STOP']) else None
            
            cursor.execute("""
                INSERT INTO condition_occurrence (
                    condition_occurrence_id, person_id, condition_concept_id,
                    condition_start_date, condition_start_datetime,
                    condition_end_date, condition_end_datetime,
                    condition_type_concept_id, visit_occurrence_id,
                    condition_source_value, condition_source_concept_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                idx + 1,
                person_id,
                0,  # Would need SNOMED to OMOP mapping
                start_dt.date().isoformat(),
                start_dt.isoformat(),
                end_dt.date().isoformat() if end_dt else None,
                end_dt.isoformat() if end_dt else None,
                32020,  # EHR
                visit_id,
                row['DESCRIPTION'],
                int(row['CODE']) if pd.notna(row['CODE']) and str(row['CODE']).isdigit() else None
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} conditions into condition_occurrence")
    
    def load_medications(self):
        """Load medications.csv into drug_exposure table"""
        logger.info("Loading medications...")
        
        csv_path = self.synthea_dir / "medications.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            person_id = self.person_id_map.get(row['PATIENT'])
            if person_id is None:
                continue
            
            visit_id = self.visit_id_map.get(row['ENCOUNTER']) if pd.notna(row.get('ENCOUNTER')) else None
            
            start_dt = pd.to_datetime(row['START'])
            end_dt = pd.to_datetime(row['STOP']) if pd.notna(row['STOP']) else None
            
            cursor.execute("""
                INSERT INTO drug_exposure (
                    drug_exposure_id, person_id, drug_concept_id,
                    drug_exposure_start_date, drug_exposure_start_datetime,
                    drug_exposure_end_date, drug_exposure_end_datetime,
                    drug_type_concept_id, visit_occurrence_id,
                    drug_source_value, drug_source_concept_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                idx + 1,
                person_id,
                0,  # Would need RxNorm to OMOP mapping
                start_dt.date().isoformat(),
                start_dt.isoformat(),
                end_dt.date().isoformat() if end_dt else None,
                end_dt.isoformat() if end_dt else None,
                38000177,  # Prescription written
                visit_id,
                row['DESCRIPTION'],
                int(row['CODE']) if pd.notna(row['CODE']) and str(row['CODE']).isdigit() else None
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} medications into drug_exposure")
    
    def load_procedures(self):
        """Load procedures.csv into procedure_occurrence table"""
        logger.info("Loading procedures...")
        
        csv_path = self.synthea_dir / "procedures.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        for idx, row in df.iterrows():
            person_id = self.person_id_map.get(row['PATIENT'])
            if person_id is None:
                continue
            
            visit_id = self.visit_id_map.get(row['ENCOUNTER']) if pd.notna(row.get('ENCOUNTER')) else None
            
            proc_dt = pd.to_datetime(row['DATE']) if pd.notna(row.get('DATE')) else pd.to_datetime(row['START'])
            
            cursor.execute("""
                INSERT INTO procedure_occurrence (
                    procedure_occurrence_id, person_id, procedure_concept_id,
                    procedure_date, procedure_datetime,
                    procedure_type_concept_id, visit_occurrence_id,
                    procedure_source_value, procedure_source_concept_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                idx + 1,
                person_id,
                0,  # Would need SNOMED to OMOP mapping
                proc_dt.date().isoformat(),
                proc_dt.isoformat(),
                38000275,  # EHR
                visit_id,
                row['DESCRIPTION'],
                int(row['CODE']) if pd.notna(row['CODE']) and str(row['CODE']).isdigit() else None
            ))
        
        self.conn.commit()
        logger.info(f"Loaded {len(df)} procedures into procedure_occurrence")
    
    def load_observations(self):
        """Load observations.csv into observation and measurement tables"""
        logger.info("Loading observations...")
        
        csv_path = self.synthea_dir / "observations.csv"
        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        cursor = self.conn.cursor()
        
        measurement_id = 1
        observation_id = 1
        
        # Vital signs and lab values go to measurement
        # Other observations go to observation
        measurement_types = ['vital signs', 'laboratory', 'lab', 'blood pressure', 
                            'body mass index', 'body weight', 'body height']
        
        for idx, row in df.iterrows():
            person_id = self.person_id_map.get(row['PATIENT'])
            if person_id is None:
                continue
            
            visit_id = self.visit_id_map.get(row['ENCOUNTER']) if pd.notna(row.get('ENCOUNTER')) else None
            obs_dt = pd.to_datetime(row['DATE'])
            
            description = str(row['DESCRIPTION']).lower()
            is_measurement = any(mt in description for mt in measurement_types)
            
            # Try to parse numeric value
            value_as_number = None
            value_as_string = str(row['VALUE']) if pd.notna(row['VALUE']) else None
            
            if value_as_string:
                try:
                    value_as_number = float(value_as_string)
                except (ValueError, TypeError):
                    pass
            
            if is_measurement:
                cursor.execute("""
                    INSERT INTO measurement (
                        measurement_id, person_id, measurement_concept_id,
                        measurement_date, measurement_datetime,
                        measurement_type_concept_id, value_as_number,
                        visit_occurrence_id, measurement_source_value,
                        measurement_source_concept_id, unit_source_value
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    measurement_id,
                    person_id,
                    0,  # Would need LOINC to OMOP mapping
                    obs_dt.date().isoformat(),
                    obs_dt.isoformat(),
                    44818702,  # Lab result
                    value_as_number,
                    visit_id,
                    row['DESCRIPTION'],
                    int(row['CODE']) if pd.notna(row['CODE']) and str(row['CODE']).isdigit() else None,
                    row['UNITS'] if pd.notna(row.get('UNITS')) else None
                ))
                measurement_id += 1
            else:
                cursor.execute("""
                    INSERT INTO observation (
                        observation_id, person_id, observation_concept_id,
                        observation_date, observation_datetime,
                        observation_type_concept_id, value_as_number,
                        value_as_string, visit_occurrence_id,
                        observation_source_value, observation_source_concept_id,
                        unit_source_value
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    observation_id,
                    person_id,
                    0,  # Would need concept mapping
                    obs_dt.date().isoformat(),
                    obs_dt.isoformat(),
                    38000280,  # Observation recorded from EHR
                    value_as_number,
                    value_as_string,
                    visit_id,
                    row['DESCRIPTION'],
                    int(row['CODE']) if pd.notna(row['CODE']) and str(row['CODE']).isdigit() else None,
                    row['UNITS'] if pd.notna(row.get('UNITS')) else None
                ))
                observation_id += 1
        
        self.conn.commit()
        logger.info(f"Loaded observations: measurement ({measurement_id-1}) + observation ({observation_id-1})")
    
    def run(self):
        """Run complete ETL pipeline"""
        logger.info("=" * 60)
        logger.info("Starting Synthea to OMOP CDM v5.4 Conversion")
        logger.info("=" * 60)
        
        self.create_omop_tables()
        self.load_patients()
        self.load_providers()
        self.load_organizations()
        self.load_encounters()
        self.load_conditions()
        self.load_medications()
        self.load_procedures()
        self.load_observations()
        
        # Print summary
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM person")
        person_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM visit_occurrence")
        visit_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM condition_occurrence")
        condition_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM drug_exposure")
        drug_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM procedure_occurrence")
        procedure_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM measurement")
        measurement_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM observation")
        observation_count = cursor.fetchone()[0]
        
        logger.info("=" * 60)
        logger.info("Conversion Complete!")
        logger.info("=" * 60)
        logger.info(f"person: {person_count:,}")
        logger.info(f"visit_occurrence: {visit_count:,}")
        logger.info(f"condition_occurrence: {condition_count:,}")
        logger.info(f"drug_exposure: {drug_count:,}")
        logger.info(f"procedure_occurrence: {procedure_count:,}")
        logger.info(f"measurement: {measurement_count:,}")
        logger.info(f"observation: {observation_count:,}")
        logger.info("=" * 60)
        logger.info(f"Database saved to: {self.output_db.absolute()}")


def main():
    """Main entry point"""
    # Paths (adjust these to your setup)
    synthea_csv_dir = Path(r"D:\projects\EHR\tools\output\csv")
    output_database = Path(r"D:\projects\EHR\omop_cdm.db")
    
    # Run conversion
    with SyntheaToOMOP(synthea_csv_dir, output_database) as converter:
        converter.run()


if __name__ == "__main__":
    main()
