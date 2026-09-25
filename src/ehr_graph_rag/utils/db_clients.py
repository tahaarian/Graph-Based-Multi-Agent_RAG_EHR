# ehr-graph-rag/src/ehr_graph_rag/utils/db_clients.py
"""Database client utilities for Neo4j and Qdrant."""

import os
from typing import Optional
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import logging

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j database client wrapper."""
    
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD")
        
        if not self.password:
            raise ValueError("Neo4j password must be provided via NEO4J_PASSWORD env var")
        
        self.driver = None
        
    def connect(self):
        """Establish connection to Neo4j."""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # Test connection
            self.driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {self.uri}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
    
    def execute_query(self, query: str, parameters: Optional[dict] = None):
        """Execute a Cypher query."""
        if not self.driver:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")
        
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class QdrantVectorStore:
    """Qdrant vector store client wrapper with embedded mode support."""
    
    def __init__(
        self,
        mode: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        path: Optional[str] = None
    ):
        self.mode = mode or os.getenv("QDRANT_MODE", "server")
        self.host = host or os.getenv("QDRANT_HOST", "localhost")
        self.port = port or int(os.getenv("QDRANT_PORT", "6333"))
        self.path = path or os.getenv("QDRANT_PATH", "./data/qdrant_storage")
        
        self.client = None
    
    def connect(self):
        """Establish connection to Qdrant (embedded or server mode)."""
        try:
            if self.mode == "embedded":
                logger.info(f"Starting Qdrant in embedded mode at {self.path}")
                self.client = QdrantClient(path=self.path)
            else:
                logger.info(f"Connecting to Qdrant server at {self.host}:{self.port}")
                self.client = QdrantClient(host=self.host, port=self.port)
            
            # Test connection
            collections = self.client.get_collections()
            logger.info(f"Connected to Qdrant. Found {len(collections.collections)} collections.")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise
    
    def create_collection(
        self,
        collection_name: str,
        vector_size: int = 1536,
        distance: Distance = Distance.COSINE
    ):
        """Create a new collection if it doesn't exist."""
        if not self.client:
            raise RuntimeError("Not connected to Qdrant. Call connect() first.")
        
        try:
            collections = self.client.get_collections().collections
            existing = [c.name for c in collections]
            
            if collection_name not in existing:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=distance)
                )
                logger.info(f"Created collection: {collection_name}")
            else:
                logger.info(f"Collection {collection_name} already exists")
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            raise
    
    def close(self):
        """Close Qdrant connection (if applicable)."""
        if self.client:
            logger.info("Qdrant connection closed")
            self.client = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_neo4j_client() -> Neo4jClient:
    """Factory function to get Neo4j client."""
    return Neo4jClient()


def get_qdrant_client() -> QdrantVectorStore:
    """Factory function to get Qdrant client."""
    return QdrantVectorStore()
