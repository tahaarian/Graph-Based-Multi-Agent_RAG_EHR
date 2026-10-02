# scripts/embed_concepts.py
"""
Embed OMOP Concept nodes (from Neo4j) with SapBERT and store in Qdrant.

Usage:
    python scripts/embed_concepts.py [--wipe] [--batch-size 64] [--test]

Requirements:
    pip install torch transformers sentence-transformers qdrant-client neo4j tqdm
"""

import argparse
import logging
import os
import sys
from typing import Optional

import torch
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    VectorParams,
)
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer

# ---------------------------------------------------------------------------
# Config (override via env vars)
# ---------------------------------------------------------------------------

import os
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI      = os.getenv("NEO4J_URI")
NEO4J_USER     = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")   # ← همنام با .env

if not NEO4J_PASSWORD:
    raise ValueError("NEO4J_PASSWORD not set in .env")

QDRANT_URL  = os.getenv("QDRANT_URL", None)
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION  = os.getenv("QDRANT_COL", "omop_concepts")

# ساخت client با منطق درست
_qurl = QDRANT_URL or ""
print(f"DEBUG QDRANT_URL repr: {repr(_qurl)}")
if _qurl == ":memory:":
    qdrant_client = QdrantClient(":memory:")          # in-memory mode
elif _qurl.startswith("http"):
    qdrant_client = QdrantClient(url=_qurl)           # remote server
else:
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)  # local server


# SapBERT: best-in-class for OMOP/SNOMED clinical concepts
# Swap to "dmis-lab/biobert-base-cased-v1.2" for BioBERT
MODEL_NAME     = os.getenv("EMBED_MODEL",
                 "cambridgeltl/SapBERT-from-PubMedBERT-fulltext")
EMBED_DIM      = 768   # both SapBERT and BioBERT output 768-d

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
# Neo4j helpers
# ---------------------------------------------------------------------------

def fetch_concepts(driver) -> list[dict]:
    """
    Pull all Concept nodes from Neo4j.
    Returns a list of dicts with keys:
        concept_id, concept_name, domain_id, vocabulary_id, concept_code
    """
    query = """
    MATCH (c:Concept)
    RETURN
        c.concept_id        AS concept_id,
        c.name              AS concept_name,
        c.domain_id         AS domain_id,
        c.vocabulary_id     AS vocabulary_id,
        c.concept_code      AS concept_code
    ORDER BY c.concept_id
    """
    with driver.session() as session:
        result = session.run(query)
        concepts = [dict(r) for r in result]
    log.info(f"Fetched {len(concepts):,} concept nodes from Neo4j.")
    return concepts


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

class SapBERTEmbedder:
    """
    Mean-pool the [CLS] token representation from SapBERT.
    SapBERT was trained with mean-pooling over all tokens, so we use that.
    """

    def __init__(self, model_name: str, device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"Loading model '{model_name}' on {self.device} ...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model     = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()
        log.info("Model loaded.")

    @torch.no_grad()
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return L2-normalised embeddings for a batch of strings."""
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="pt",
        ).to(self.device)

        out = self.model(**enc)
        # Mean-pool over token dimension, then L2-normalise
        mask = enc["attention_mask"].unsqueeze(-1).float()
        vecs = (out.last_hidden_state * mask).sum(1) / mask.sum(1)
        vecs = torch.nn.functional.normalize(vecs, p=2, dim=-1)
        return vecs.cpu().tolist()


def build_text(concept: dict) -> str:
    """
    Compose a short clinical phrase for embedding.
    Domain prefix helps the model disambiguate homographs
    (e.g. "Condition: Diabetes mellitus type 2").
    """
    domain = concept.get("domain_id") or ""
    name   = concept.get("concept_name") or ""
    vocab  = concept.get("vocabulary_id") or ""
    code   = concept.get("concept_code") or ""
    parts  = [p for p in [domain, name, vocab, code] if p]
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def init_collection(client: QdrantClient, wipe: bool):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        if wipe:
            client.delete_collection(COLLECTION)
            log.info(f"Deleted existing collection '{COLLECTION}'.")
        else:
            log.info(f"Collection '{COLLECTION}' already exists — skipping creation.")
            return

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    log.info(f"Created Qdrant collection '{COLLECTION}' (dim={EMBED_DIM}, cosine).")


def upsert_points(
    client: QdrantClient,
    concepts: list[dict],
    vectors: list[list[float]],
):
    points = []
    for concept, vector in zip(concepts, vectors):
        payload = {
            "concept_id":    concept.get("concept_id"),
            "concept_name":  concept.get("concept_name"),
            "domain_id":     concept.get("domain_id"),
            "vocabulary_id": concept.get("vocabulary_id"),
            "concept_code":  concept.get("concept_code"),
        }
        # Qdrant point id must be an unsigned int or UUID
        point_id = abs(hash(str(concept.get("concept_id")))) % (2**63)
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    client.upsert(collection_name=COLLECTION, points=points, wait=True)


# ---------------------------------------------------------------------------
# Semantic search test
# ---------------------------------------------------------------------------

def test_search(client: QdrantClient, embedder: SapBERTEmbedder):
    queries = [
        "diabetes mellitus type 2",
        "myocardial infarction",
        "metformin hydrochloride",
    ]
    log.info("\n--- Semantic search smoke-test ---")
    for q in queries:
        vec = embedder.embed_batch([q])[0]
        hits = client.search(
            collection_name=COLLECTION,
            query_vector=vec,
            limit=3,
        )
        log.info(f"\nQuery: '{q}'")
        for h in hits:
            log.info(
                f"  [{h.score:.4f}] {h.payload.get('concept_name')}"
                f"  (id={h.payload.get('concept_id')},"
                f"  domain={h.payload.get('domain_id')})"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Embed OMOP concepts → Qdrant")
    parser.add_argument("--wipe",       action="store_true",
                        help="Drop and recreate Qdrant collection before embedding.")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Tokeniser / inference batch size (default 64).")
    parser.add_argument("--test",       action="store_true",
                        help="Run a quick semantic search test after embedding.")
    args = parser.parse_args()

    # 1. Connect
    neo4j_driver = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    ##qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
   ## log.info("Connected to Neo4j and Qdrant.")

    # 2. Load concepts
    concepts = fetch_concepts(neo4j_driver)
    if not concepts:
        log.error("No concepts found in Neo4j. Did you run build_graph.py first?")
        sys.exit(1)

    # 3. Qdrant collection
    init_collection(qdrant_client, wipe=args.wipe)

    # 4. Load model
    embedder = SapBERTEmbedder(MODEL_NAME)

    # 5. Embed in batches
    batch_size  = args.batch_size
    total       = len(concepts)
    inserted    = 0

    log.info(f"Embedding {total:,} concepts in batches of {batch_size} ...")
    for start in tqdm(range(0, total, batch_size), unit="batch"):
        batch   = concepts[start : start + batch_size]
        texts   = [build_text(c) for c in batch]
        vectors = embedder.embed_batch(texts)
        upsert_points(qdrant_client, batch, vectors)
        inserted += len(batch)

    log.info(f"Done. Inserted {inserted:,} points into '{COLLECTION}'.")

    # 6. Optional smoke-test
    if args.test:
        test_search(qdrant_client, embedder)

    neo4j_driver.close()


if __name__ == "__main__":
    main()
