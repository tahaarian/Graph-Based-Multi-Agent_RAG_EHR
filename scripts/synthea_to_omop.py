# scripts/synthea_to_omop.py
import pandas as pd
import os
from pathlib import Path

RAW = Path("data/raw/synthea")
OUT = Path("data/processed/omop_cdm")
OUT.mkdir(parents=True, exist_ok=True)

# ---- PERSON ----
patients = pd.read_csv(RAW / "patients.csv")
person = pd.DataFrame({
    "person_id": range(1, len(patients)+1),
    "person_source_value": patients["Id"],
    "gender_source_value": patients["GENDER"],
    "year_of_birth": pd.to_datetime(patients["BIRTHDATE"]).dt.year,
    "race_source_value": patients["RACE"],
    "ethnicity_source_value": patients["ETHNICITY"],
})
person.to_csv(OUT / "person.csv", index=False)
pid_map = dict(zip(patients["Id"], person["person_id"]))
print(f"person: {len(person)} rows")

# ---- VISIT_OCCURRENCE ----
enc = pd.read_csv(RAW / "encounters.csv")
visit = pd.DataFrame({
    "visit_occurrence_id": range(1, len(enc)+1),
    "person_id": enc["PATIENT"].map(pid_map),
    "visit_source_value": enc["Id"],
    "visit_start_date": pd.to_datetime(enc["START"]).dt.date,
    "visit_end_date": pd.to_datetime(enc["STOP"]).dt.date,
    "visit_type_source_value": enc["ENCOUNTERCLASS"],
})
visit.to_csv(OUT / "visit_occurrence.csv", index=False)
vid_map = dict(zip(enc["Id"], visit["visit_occurrence_id"]))
print(f"visit_occurrence: {len(visit)} rows")

# ---- CONDITION_OCCURRENCE ----
cond = pd.read_csv(RAW / "conditions.csv")
condition = pd.DataFrame({
    "condition_occurrence_id": range(1, len(cond)+1),
    "person_id": cond["PATIENT"].map(pid_map),
    "visit_occurrence_id": cond["ENCOUNTER"].map(vid_map),
    "condition_source_value": cond["CODE"].astype(str),
    "condition_source_vocab": "SNOMED",
    "condition_start_date": pd.to_datetime(cond["START"]).dt.date,
    "condition_end_date": pd.to_datetime(cond["STOP"]).dt.date,
    "condition_concept_name": cond["DESCRIPTION"],
})
condition.to_csv(OUT / "condition_occurrence.csv", index=False)
print(f"condition_occurrence: {len(condition)} rows")

# ---- DRUG_EXPOSURE ----
meds = pd.read_csv(RAW / "medications.csv")
drug = pd.DataFrame({
    "drug_exposure_id": range(1, len(meds)+1),
    "person_id": meds["PATIENT"].map(pid_map),
    "visit_occurrence_id": meds["ENCOUNTER"].map(vid_map),
    "drug_source_value": meds["CODE"].astype(str),
    "drug_source_vocab": "RxNorm",
    "drug_exposure_start_date": pd.to_datetime(meds["START"]).dt.date,
    "drug_exposure_end_date": pd.to_datetime(meds["STOP"]).dt.date,
    "drug_concept_name": meds["DESCRIPTION"],
})
drug.to_csv(OUT / "drug_exposure.csv", index=False)
print(f"drug_exposure: {len(drug)} rows")

# ---- PROCEDURE_OCCURRENCE ----
proc = pd.read_csv(RAW / "procedures.csv")
procedure = pd.DataFrame({
    "procedure_occurrence_id": range(1, len(proc)+1),
    "person_id": proc["PATIENT"].map(pid_map),
    "visit_occurrence_id": proc["ENCOUNTER"].map(vid_map),
    "procedure_source_value": proc["CODE"].astype(str),
    "procedure_source_vocab": "SNOMED",
    "procedure_date": pd.to_datetime(proc["START"]).dt.date,
    "procedure_concept_name": proc["DESCRIPTION"],
})
procedure.to_csv(OUT / "procedure_occurrence.csv", index=False)
print(f"procedure_occurrence: {len(procedure)} rows")

# ---- MEASUREMENT ----
obs = pd.read_csv(RAW / "observations.csv")
meas_mask = obs["TYPE"] == "numeric"
meas = obs[meas_mask].copy()
measurement = pd.DataFrame({
    "measurement_id": range(1, len(meas)+1),
    "person_id": meas["PATIENT"].map(pid_map),
    "visit_occurrence_id": meas["ENCOUNTER"].map(vid_map),
    "measurement_source_value": meas["CODE"].astype(str),
    "measurement_source_vocab": "LOINC",
    "measurement_date": pd.to_datetime(meas["DATE"]).dt.date,
    "measurement_concept_name": meas["DESCRIPTION"],
    "value_as_number": pd.to_numeric(meas["VALUE"], errors="coerce"),
    "unit_source_value": meas["UNITS"],
})
measurement.to_csv(OUT / "measurement.csv", index=False)
print(f"measurement: {len(measurement)} rows")

# ---- OBSERVATION ----
obs_mask = obs["TYPE"] != "numeric"
obs_df = obs[obs_mask].copy()
observation = pd.DataFrame({
    "observation_id": range(1, len(obs_df)+1),
    "person_id": obs_df["PATIENT"].map(pid_map),
    "visit_occurrence_id": obs_df["ENCOUNTER"].map(vid_map),
    "observation_source_value": obs_df["CODE"].astype(str),
    "observation_source_vocab": "LOINC",
    "observation_date": pd.to_datetime(obs_df["DATE"]).dt.date,
    "observation_concept_name": obs_df["DESCRIPTION"],
    "value_as_string": obs_df["VALUE"].astype(str),
})
observation.to_csv(OUT / "observation.csv", index=False)
print(f"observation: {len(observation)} rows")

print("\nETL complete. Files written to", OUT)
