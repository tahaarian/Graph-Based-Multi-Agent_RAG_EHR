"""Database client wrappers for Neo4j and Qdrant with clear error reporting."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)


class Neo4jConnectionError(Exception):
    """Raised when a Neo4j connection cannot be established."""


class QdrantConnectionError(Exception):
    """Raised when a Qdrant connection / health check fails."""


class Neo4jClient:
    """Thin wrapper around neo4j.GraphDatabase with context-manager support."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._driver: Any = None

    def connect(self) -> None:
        """Open the Neo4j driver; raise Neo4jConnectionError on failure."""
        try:
            from neo4j import GraphDatabase  # imported lazily for a clear error message
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise Neo4jConnectionError(
                "The 'neo4j' driver package is not installed. "
                "Install it with: pip install neo4j  (or: conda install -c conda-forge neo4j-python-driver)"
            ) from exc
        try:
            self._driver = GraphDatabase.driver(
                self._settings.neo4j_uri,
                auth=(self._settings.neo4j_user, self._settings.neo4j_password),
            )
            logger.info("Neo4j driver created for %s", self._settings.neo4j_uri)
        except Exception as exc:  # auth errors, bad URI, unreachable host, ...
            raise Neo4jConnectionError(
                f"Could not create Neo4j driver for '{self._settings.neo4j_uri}': {exc}. "
                "Check that the server is running and NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in .env are correct."
            ) from exc

    def verify_connectivity(self) -> None:
        """Verify the server is reachable; call connect() first if needed."""
        if self._driver is None:
            self.connect()
        try:
            self._driver.verify_connectivity()
        except Exception as exc:
            raise Neo4jConnectionError(
                f"Neo4j server at '{self._settings.neo4j_uri}' is not reachable: {exc}. "
                "Start Neo4j Desktop (or your Aura instance) and verify credentials in .env."
            ) from exc

    def close(self) -> None:
        """Close the underlying driver if open."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j driver closed.")

    def __enter__(self) -> "Neo4jClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class QdrantClientWrapper:
    """Thin wrapper around qdrant_client.QdrantClient with a health check."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None

    def connect(self) -> None:
        """Create the Qdrant client; raise QdrantConnectionError on failure."""
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover
            raise QdrantConnectionError(
                "The 'qdrant-client' package is not installed. "
                "Install it with: pip install qdrant-client"
            ) from exc
        try:
            url = self._settings.qdrant_url
            
            # Support embedded/in-memory mode
            if url == ":memory:":
                self._client = QdrantClient(location=":memory:")
                logger.info("Qdrant client created in memory mode")
            elif url.startswith("./") or url.startswith("../") or (len(url) > 2 and url[1] == ':'):
                # File-based embedded mode (relative or absolute path)
                self._client = QdrantClient(path=url)
                logger.info("Qdrant client created in embedded mode: %s", url)
            else:
                # Server mode
                self._client = QdrantClient(
                    url=url,
                    api_key=GAPGPTMASKTOKENckwaheeqrvsX0X,
                    timeout=5,
                )
                logger.info("Qdrant client created for server: %s", url)
        except Exception as exc:
            raise QdrantConnectionError(
                f"Could not create Qdrant client for '{self._settings.qdrant_url}': {exc}. "
                "Check that QDRANT_URL in .env is correct (:memory: for in-memory, path for file-based, or http://... for server)."
            ) from exc

    def health_check(self) -> bool:
        """Return True if the Qdrant server answers a collections listing."""
        if self._client is None:
            self.connect()
        try:
            self._client.get_collections()
            return True
        except Exception as exc:
            raise QdrantConnectionError(
                f"Qdrant health check failed: {exc}. "
                "Ensure the Qdrant configuration in .env is correct."
            ) from exc

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
