EHR Graph-RAG: Dynamic Graph-Based Multi-Agent RAG Framework for Longitudinal EHRs
This project is a dynamic graph-based, multi-agent Graph-RAG framework for faithful retrieval and reasoned decision-making over longitudinal Electronic Health Records. Instead of pure vector retrieval, patient history is modeled as a dynamic heterogeneous graph (Patient · Visit · Condition · Medication · Observation · Procedure), combining Temporal-Semantic Path Retrieval (TSPR) and multi-agent consensus (CMAC) to produce traceable, evidence-backed answers.
Benchmark: EHRSHOT
Schema: OMOP CDM v5.4
Target: Q1 journal publication
Stack: Neo4j · PyTorch Geometric · SapBERT · LangGraph · Qdrant
Pipeline Overview
The following ASCII diagram shows the end-to-end flow across Phases 1–5, including current graph statistics and the medication mapping blocker:
Raw OMOP CDM v5.4 CSVs (EHRSHOT)
            │
            ▼
┌───────────────────────────────┐
│  Phase 1 · Ingestion           │  ← scripts/load_ehrshot.py
│  EHRSHOT / OMOP CDM v5.4      │     scripts/validate_schema.py
└───────────────┬───────────────┘
                │  patients, visits, conditions,
                │  medications, observations, procedures
                ▼
┌───────────────────────────────────────────────┐
│  Phase 2 · Dynamic Heterogeneous Graph         │  ← scripts/build_graph.py
│  Neo4j  +  PyG  +  SapBERT embeddings         │     scripts/build_concept_links.py
│                                                │     scripts/enrich_rxnorm.py  ⚠ WIP
│  Nodes : Patient · Visit · Concept            │
│  Edges : HAS_VISIT · OCCURRED_AT              │
│          MAPPED_TO · TEMPORALLY_FOLLOWS        │
└───────────────┬───────────────┘
                │  38,926 MAPPED_TO edges
                │  11,795 TEMPORALLY_FOLLOWS edges
                │  ⚠  Medication MAPPED_TO = 0 (blocker)
                ▼
┌───────────────────────────────────────────────┐
│  Phase 3 · TSPR                                │  ← src/ehr_graph_rag/retrieval/tspr.py
│  Temporal-Semantic Path Retrieval              │
│  Temporal decay × cosine similarity scoring   │
└───────────────┬───────────────┘
                │  ranked subgraph paths
                ▼
┌───────────────────────────────────────────────┐
│  Phase 4 · CMAC                                │  ← src/ehr_graph_rag/agents/  (LangGraph)
│  Multi-Agent Consensus                         │
│  Agents: Diagnosis · Pharmacology · Labs       │
└───────────────┬───────────────┘
                │  evidence-backed answer
                ▼
┌───────────────────────────────────────────────┐
│  Phase 5 · Evaluation                          │  ← src/ehr_graph_rag/evaluation/
│  AUROC · F1 · RAGAS Faithfulness              │
└───────────────────────────────────────────────┘

Setup
Two setup options are supported:
Option A — Conda (recommended)
conda env create -f environment.yml
conda activate ehr-graph-rag

Option B — pip
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

PyG note: torch_geometric requires the project-specific wheel index. If the default install fails, install from the matching wheel index for your Torch/CUDA combination:
pip install torch_geometric \
  -f https://data.pyg.org/whl/torch-${TORCH_VERSION}+${CUDA}.html

Configuration & Environment Validation
Copy the environment template and fill in real values:
cp .env.example .env

Minimum required keys in .env:
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-password>

QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=<your-key>

LLM_MODEL=gpt-4o
OPENAI_API_KEY=<your-key>

.env is covered by .gitignore — never commit it.
Environment Validation
python scripts/check_environment.py      # Python version & installed packages
python scripts/test_db_connections.py    # Neo4j and Qdrant connectivity

Project Structure
├── config/
│   ├── settings.py           # pydantic-settings config
│   └── logging_config.py
├── data/
│   ├── raw/                  # raw OMOP CDM v5.4 CSVs  (not committed)
│   ├── processed/            # cleaned / mapped records
│   └── external/             # vocabularies, data dictionaries
├── docs/
│   └── architecture.md
├── scripts/
│   ├── check_environment.py
│   ├── test_db_connections.py
│   ├── build_graph.py
│   ├── build_concept_links.py
│   └── enrich_rxnorm.py      # WIP — resolves Medication MAPPED_TO = 0
├── src/ehr_graph_rag/
│   ├── ingestion/            # Phase 1 — EHRSHOT / OMOP CDM v5.4 loading
│   ├── graph/                # Phase 2 — Neo4j + PyG + SapBERT
│   ├── retrieval/            # Phase 3 — TSPR
│   ├── agents/               # Phase 4 — CMAC multi-agent consensus (LangGraph)
│   ├── evaluation/           # Phase 5 — AUROC / F1 / RAGAS
│   └── utils/                # DB clients, shared utilities
└── tests/

Graph Metrics
Current state after Phase 3:
Edge typeCountStatusMAPPED_TO — Condition35,245✅MAPPED_TO — Observation3,681✅MAPPED_TO — Procedure67,344✅MAPPED_TO — total38,926✅MAPPED_TO — Medication0❌ Critical blockerTEMPORALLY_FOLLOWS11,795⏳ Decay weighting pending
Medication blocker: scripts/enrich_rxnorm.py is in development to resolve the 0-match rate via RxNorm API / CSV lookup against the drug_exposure table. This is the highest-priority item for Phase 4.
Roadmap
PhaseMilestoneStatus0Infrastructure — repo, conda environment, Neo4j/Qdrant clients✅ Done1Ingestion — EHRSHOT / OMOP CDM v5.4 loading and schema validation✅ Done2Dynamic Heterogeneous Graph — Neo4j graph, SapBERT embeddings, concept links✅ Done3TSPR — Temporal-Semantic Path Retrieval (temporal decay pending)🔄 In Progress4CMAC — Multi-agent consensus via LangGraph; enrich_rxnorm.py medication mapping🔄 In Progress5Evaluation — AUROC, F1, and RAGAS faithfulness on EHRSHOT⏳ Pending