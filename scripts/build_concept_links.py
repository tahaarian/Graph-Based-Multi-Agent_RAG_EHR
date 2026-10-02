# scripts/build_concept_links.py
"""
Build MAPPED_TO edges in Neo4j by linking clinical nodes
(Condition, Medication, Observation, Procedure) to their
closest OMOP Concept using SapBERT embeddings + cosine search.

Strategy: fully in-process — no Qdrant server needed.
  1. Load all Concept nodes from Neo4j and embed them with SapBERT.
  2. Build an in-memory FAISS / numpy index.
  3. For each clinical node batch, embed and find nearest Concept.
  4. Write MAPPED_TO edges back to Neo4j.

Usage:
    python scripts/build_concept_links.py [--top-k 1] [--batch-size 64] [--score-threshold 0.70]
"""

import argparse
import logging
import os
import sys

import numpy as np
import torch
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
if not NEO4J_PASSWORD:
    raise ValueError("NEO4J_PASSWORD not set in .env")

MODEL_NAME = os.getenv(
    "EMBED_MODEL",
    "cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
)
EMBED_DIM = 768

# Node types to link and which property to use as the text label
CLINICAL_NODE_TYPES = {
    "Condition":   {"label_prop": "description", "id_prop": "condition_id"},
    "Medication":  {"label_prop": "description", "id_prop": "medication_id"},
    "Observation": {"label_prop": "description", "id_prop": "observation_id"},
    "Procedure":   {"label_prop": "description", "id_prop": "procedure_id"},
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

class SapBERTEmbedder:
    def __init__(self, model_name: str):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info(f"Loading SapBERT from: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model     = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()
        log.info(f"SapBERT loaded on {self.device}")

    @torch.no_grad()
    def embed(self, texts: list[str]) -> np.ndarray:
        """Returns L2-normalised float32 matrix (N, 768)."""
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="pt",
        ).to(self.device)
        out  = self.model(**enc)
        mask = enc["attention_mask"].unsqueeze(-1).float()
        vecs = (out.last_hidden_state * mask).sum(1) / mask.sum(1)
        vecs = torch.nn.functional.normalize(vecs, p=2, dim=-1)
        return vecs.cpu().numpy().astype(np.float32)


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def fetch_concepts(driver) -> list[dict]:
    query = """
    MATCH (c:Concept)
    RETURN
        c.concept_id    AS concept_id,
        c.name          AS concept_name,
        c.domain_id     AS domain_id,
        c.vocabulary_id AS vocabulary_id,
        c.concept_code  AS concept_code
    ORDER BY c.concept_id
    """
    with driver.session() as session:
        records = session.run(query)
        concepts = [dict(r) for r in records]
    log.info(f"Fetched {len(concepts):,} Concept nodes from Neo4j")
    return concepts


def fetch_clinical_nodes(driver, node_label: str, id_prop: str, label_prop: str) -> list[dict]:
    query = f"""
    MATCH (n:{node_label})
    WHERE NOT (n)-[:MAPPED_TO]->(:Concept)
    RETURN
        n.{id_prop}    AS node_id,
        n.{label_prop} AS text,
        elementId(n)   AS elem_id
    """
    with driver.session() as session:
        records = session.run(query)
        nodes = [dict(r) for r in records]
    log.info(f"  {node_label}: {len(nodes):,} نود پیدا شد (بدون MAPPED_TO)")
    return nodes


def write_mapped_to_edges(driver, node_label: str, id_prop: str, mappings: list[dict]):
    """
    mappings: list of {node_id, concept_id, score}
    """
    query = f"""
    UNWIND $rows AS row
    MATCH (n:{node_label} {{{id_prop}: row.node_id}})
    MATCH (c:Concept {{concept_id: row.concept_id}})
    MERGE (n)-[r:MAPPED_TO]->(c)
    SET r.score = row.score
    """
    with driver.session() as session:
        session.run(query, rows=mappings)


# ---------------------------------------------------------------------------
# In-process cosine search (numpy — no Qdrant needed)
# ---------------------------------------------------------------------------

def build_index(concept_vecs: np.ndarray) -> np.ndarray:
    """concept_vecs is already L2-normalised → cosine sim = dot product."""
    return concept_vecs  # shape (N, 768)


def search(
    index: np.ndarray,
    query_vecs: np.ndarray,
    top_k: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (indices, scores) each of shape (Q, top_k).
    Scores are cosine similarities in [-1, 1].
    """
    # (Q, N) cosine similarity matrix
    sims = query_vecs @ index.T
    # argsort descending
    top_idx   = np.argsort(-sims, axis=1)[:, :top_k]
    top_scores = np.take_along_axis(sims, top_idx, axis=1)
    return top_idx, top_scores


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_concept_text(c: dict) -> str:
    domain = c.get("domain_id") or ""
    name   = c.get("concept_name") or ""
    vocab  = c.get("vocabulary_id") or ""
    code   = c.get("concept_code") or ""
    return " | ".join(p for p in [domain, name, vocab, code] if p)


def run(top_k: int, batch_size: int, score_threshold: float):
    driver   = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    embedder = SapBERTEmbedder(MODEL_NAME)

    # ── 1. Embed all Concept nodes ──────────────────────────────────────────
    concepts = fetch_concepts(driver)
    if not concepts:
        log.error("هیچ Concept نودی در Neo4j پیدا نشد. ابتدا build_graph.py رو اجرا کن.")
        sys.exit(1)

    concept_texts = [build_concept_text(c) for c in concepts]
    concept_ids   = [c["concept_id"] for c in concepts]

    log.info(f"Embedding {len(concepts):,} concepts ...")
    concept_vecs = []
    for start in tqdm(range(0, len(concepts), batch_size), desc="Concepts", unit="batch"):
        batch_texts = concept_texts[start : start + batch_size]
        concept_vecs.append(embedder.embed(batch_texts))
    concept_vecs = np.vstack(concept_vecs)          # (N, 768)
    index        = build_index(concept_vecs)

    # ── 2. Link each clinical node type ─────────────────────────────────────
    total_mapped = 0
    for node_label, cfg in CLINICAL_NODE_TYPES.items():
        log.info(f"━━━ پردازش {node_label} ━━━")
        nodes = fetch_clinical_nodes(
            driver, node_label, cfg["id_prop"], cfg["label_prop"]
        )
        if not nodes:
            log.info(f"  همه {node_label} نودها قبلاً map شدن — skip")
            continue

        mappings = []
        for start in tqdm(range(0, len(nodes), batch_size), desc=node_label, unit="batch"):
            batch = nodes[start : start + batch_size]
            texts = [n.get("text") or "" for n in batch]

            # embed
            q_vecs = embedder.embed(texts)

            # search
            top_idx, top_scores = search(index, q_vecs, top_k=top_k)

            for i, node in enumerate(batch):
                best_idx   = int(top_idx[i, 0])
                best_score = float(top_scores[i, 0])
                if best_score < score_threshold:
                    continue
                mappings.append({
                    "node_id":    node["node_id"],
                    "concept_id": concept_ids[best_idx],
                    "score":      round(best_score, 4),
                })

        if mappings:
            write_mapped_to_edges(driver, node_label, cfg["id_prop"], mappings)
            log.info(f"  ✓ {len(mappings):,} MAPPED_TO edge نوشته شد")
            total_mapped += len(mappings)
        else:
            log.warning(f"  هیچ match معتبری با threshold={score_threshold} پیدا نشد")

    log.info(f"\n✅ کل MAPPED_TO edges ساخته‌شده: {total_mapped:,}")
    driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build MAPPED_TO edges in Neo4j")
    parser.add_argument("--top-k",           type=int,   default=1,    help="تعداد بهترین match‌ها")
    parser.add_argument("--batch-size",      type=int,   default=64,   help="اندازه batch برای embedding")
    parser.add_argument("--score-threshold", type=float, default=0.70, help="حداقل cosine similarity")
    args = parser.parse_args()

    run(
        top_k           = args.top_k,
        batch_size      = args.batch_size,
        score_threshold = args.score_threshold,
    )
