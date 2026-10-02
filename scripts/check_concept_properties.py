# scripts/check_concept_properties.py
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
)

with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
    result = session.run("MATCH (c:Concept) RETURN keys(c) AS props LIMIT 1")
    record = result.single()
    if record:
        print("Properties on Concept nodes:", record["props"])
    else:
        print("No Concept nodes found!")

driver.close()
