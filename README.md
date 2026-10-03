Project Title and Badges
EHR-Graph-RAG
A dynamic graph-based multi-agent RAG framework for faithful retrieval and reasoned decision-making over longitudinal electronic health records (EHR).
Built on the EHRSHOT benchmark and the OMOP Common Data Model v5.4, EHR-Graph-RAG combines a dynamic heterogeneous patient graph, temporal retrieval (TSPR), and a multi-agent reasoning layer (CMAC, powered by LangGraph) to support clinical question answering over a patient's full longitudinal history.
Target outcome: a Q1 journal publication demonstrating that graph-structured, temporally aware retrieval outperforms flat-vector RAG on longitudinal EHR reasoning tasks.
Overview
Standard retrieval-augmented generation over clinical text treats a patient's record as a bag of isolated chunks. This breaks down for longitudinal EHR data, where the answer to a clinical question often depends on the ordering, spacing, and type of events — a medication, then a lab, then a diagnosis months later.
EHR-Graph-RAG addresses this by modeling each patient as a dynamic heterogeneous graph: OMOP clinical events are nodes, typed relationships (temporal succession, concept mappings, measurement linkage) are edges, and retrieval walks this graph instead of scanning flat embeddings. A multi-agent CMAC layer then plans, retrieves, verifies, and reasons over the retrieved subgraph, keeping intermediate steps faithful to the underlying record.
Key Features
Dynamic heterogeneous patient graphs built directly from OMOP CDM v5.4 tables (condition, observation, procedure, drug, measurement).
Temporal retrieval (TSPR) that respects event ordering and time gaps rather than cosine similarity alone.
Multi-agent reasoning (CMAC) orchestrated with LangGraph: planning, retrieval, verification, and synthesis agents with explicit intermediate state.
Faithfulness-first design: every generated claim is traceable to retrieved graph nodes and edges.
EHRSHOT benchmark integration for standardized, reproducible evaluation across clinical prediction and question-answering tasks.
Connection validation tooling: one-command checks for environment variables and database connectivity before any pipeline run.
Architecture and Pipeline
The system is organized as four layers: ingestion into OMOP, graph construction, temporal retrieval, and multi-agent reasoning.
The end-to-end pipeline is:
EHRSHOT raw data
      │
      ▼
OMOP CDM v5.4 ingestion  ──►  PostgreSQL / OHDSI tooling
      │
      ▼
Dynamic heterogeneous graph (Neo4j)
  • MAPPED_TO edges (concept mapping)
  • TEMPORALLY_FOLLOWS edges (event ordering)
      │
      ▼
Temporal retrieval (TSPR)
  • graph-guided expansion + vector search (Qdrant)
      │
      ▼
CMAC multi-agent layer (LangGraph)
  • plan → retrieve → verify → synthesize
      │
      ▼
Answer with traceable evidence + evaluation (Phase 5)

Key components:
ComponentResponsibilityStorageIngestion pipelineMap EHRSHOT to OMOP CDM v5.4PostgreSQLGraph layerDynamic heterogeneous patient graphNeo4jVector indexChunk and event embeddingsQdrantTSPRTemporally-aware subgraph retrievalNeo4j + QdrantCMAC agentsPlan, retrieve, verify, synthesizeLangGraph + LLM API
Installation
Requirements: Python 3.10+, Docker (for Neo4j and Qdrant), and access to the EHRSHOT dataset.
git clone <repository-url>
cd EHR-Graph-RAG
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Start the databases with Docker Compose:
docker compose up -d

Then validate the environment before running anything else (see next section).
Environment Configuration
Copy the template and fill in real values — never commit actual secrets.
cp .env.example .env

.env template:
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-neo4j-password>

# Qdrant
QDRANT_URL=https://<your-cluster>.qdrant.io
QDRANT_API_KEY=<your-qdrant-api-key>

# LLM provider
OPENAI_API_KEY=<your-openai-api-key>

Validate configuration and connectivity:
# checks all required environment variables are set
python scripts/check_environment.py

# performs live connection tests against Neo4j and Qdrant
python scripts/test_db_connections.py

Both scripts must pass before running the ingestion or retrieval pipelines.
Data Ingestion and OMOP Mapping
The ingestion pipeline converts EHRSHOT records into OMOP CDM v5.4 domains and then projects them into the Neo4j graph. Concept mappings produce MAPPED_TO edges; event ordering within each patient timeline produces TEMPORALLY_FOLLOWS edges.
Condition, observation, and procedure domains are fully mapped. The medication domain is currently a critical blocker: as of post-Phase 3, the DRUG → MAPPED_TO count is 0, meaning RxNorm concept codes are not yet linked into the graph. The enrichment script scripts/enrich_rxnorm.py is under active development to backfill medication-to-concept mappings; run it after ingestion once ready:
python scripts/enrich_rxnorm.py

Re-run graph metric extraction afterward to confirm medication mappings land in Neo4j.
Graph Metrics (Post-Phase 3)
Relationship counts extracted from Neo4j after completion of Phase 3:
RelationshipDomainCountMAPPED_TOCondition35,245MAPPED_TOObservation3,681MAPPED_TOProcedure67,344MAPPED_TOMedication0 (critical blocker)TEMPORALLY_FOLLOWSAll domains11,795
Note: the reported MAPPED_TO total across mapped domains is 38,926, while medication MAPPED_TO = 0 means drug events exist in OMOP but are not yet linked to RxNorm concepts; resolution is tracked via scripts/enrich_rxnorm.py (see above).
Usage
Typical workflow once ingestion and validation are complete:
# 1. Run the ingestion pipeline into OMOP + graph
python scripts/run_ingestion.py

# 2. Build embeddings into Qdrant
python scripts/build_embeddings.py

# 3. Run temporal retrieval (TSPR) on a sample query
python scripts/run_tspr.py --patient-id <id> --query "..."

# 4. Run the CMAC multi-agent layer (Phase 4, in progress)
python scripts/run_cmac.py --task <task-name>

CMAC exposes a LangGraph state machine per query: a planning agent decomposes the question, a retrieval agent issues TSPR queries, a verification agent checks claims against retrieved nodes, and a synthesis agent produces the final answer with citations to graph evidence.
Project Roadmap
PhaseDescriptionStatus0Infrastructure (databases, environment, CI)✅ Done1EHRSHOT → OMOP CDM v5.4 ingestion✅ Done2Dynamic heterogeneous graph construction✅ Done3Temporal retrieval (TSPR)✅ Done4CMAC multi-agent layer (LangGraph)🚧 In progress5Evaluation on EHRSHOT benchmark⏳ Pending
Current focus: completing the CMAC agent graph and resolving the medication MAPPED_TO blocker via scripts/enrich_rxnorm.py.
Project Structure
EHR-Graph-RAG/
├── scripts/
│   ├── check_environment.py     # env variable validation
│   ├── test_db_connections.py   # Neo4j / Qdrant connectivity
│   ├── run_ingestion.py         # EHRSHOT → OMOP → graph
│   ├── enrich_rxnorm.py         # medication concept enrichment (WIP)
│   ├── build_embeddings.py      # vector index in Qdrant
│   ├── run_tspr.py              # temporal retrieval
│   └── run_cmac.py              # multi-agent reasoning entry point
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md

License and Citation
Distributed under the MIT License — see LICENSE for details.
If you use EHR-Graph-RAG in research, please cite the project (citation entry will be finalized with the journal submission). Contributions are welcome via pull requests; please run scripts/check_environment.py and scripts/test_db_connections.py before opening a PR that touches the pipeline.