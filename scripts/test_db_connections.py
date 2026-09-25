#!/usr/bin/env python3
"""Independently test connectivity to Neo4j and Qdrant, with actionable guidance."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings  # noqa: E402
from src.ehr_graph_rag.utils.db_clients import (  # noqa: E402
    Neo4jClient,
    Neo4jConnectionError,
    QdrantClientWrapper,
    QdrantConnectionError,
)


def main() -> int:
    settings = get_settings()
    results: list[tuple[str, bool]] = []

    print("=" * 60)
    print("Database connectivity tests")
    print("=" * 60)

    # --- Neo4j ---
    print(f"\n[Neo4j] target: {settings.neo4j_uri}")
    try:
        client = Neo4jClient()
        client.connect()
        client.verify_connectivity()
        client.close()
        print("  ✅ Neo4j connection OK")
        results.append(("Neo4j", True))
    except (Neo4jConnectionError, Exception) as exc:
        print(f"  ❌ Neo4j connection FAILED: {exc}")
        print("     Neo4j Desktop/Aura is not running or NEO4J_URI/credentials in .env are wrong. "
              "Start Neo4j Desktop, or update .env.")
        results.append(("Neo4j", False))

    # --- Qdrant ---
    print(f"\n[Qdrant] target: {settings.qdrant_url}")
    try:
        wrapper = QdrantClientWrapper()
        ok = wrapper.health_check()
        wrapper.close()
        print("  ✅ Qdrant health check OK" if ok else "  ❌ Qdrant health check FAILED")
        results.append(("Qdrant", ok))
    except (QdrantConnectionError, Exception) as exc:
        print(f"  ❌ Qdrant health check FAILED: {exc}")
        print("     Qdrant server not reachable. Since this project avoids Docker, either "
              "(a) install the qdrant binary directly for your OS and run it, or "
              "(b) use qdrant-client's local in-memory/on-disk mode "
              "(QdrantClient(path='./data/qdrant_local')) for development instead of a server.")
        results.append(("Qdrant", False))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, ok in results:
        print(f"  {name:<8} {'✅ PASS' if ok else '❌ FAIL'}")
    failed = [name for name, ok in results if not ok]
    print("\nAll services checked. " + ("All passed." if not failed else f"Failures: {', '.join(failed)}"))
    return 0  # always finish; failures are informational in Phase 0


if __name__ == "__main__":
    sys.exit(main())
