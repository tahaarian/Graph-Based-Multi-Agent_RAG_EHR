"""Tests for config.settings.Settings (env override + defaults)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config.settings import Settings  # noqa: E402


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://override:9999")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings(_env_file=None)
    assert s.neo4j_uri == "bolt://override:9999"
    assert s.log_level == "DEBUG"


def test_defaults_no_env(monkeypatch):
    for var in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "QDRANT_URL",
                "QDRANT_API_KEY", "LLM_PROVIDER", "LOCAL_LLM_MODEL_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # no .env fallback
    s = Settings(_env_file=None)
    assert s.neo4j_uri == "bolt://localhost:7687"
    assert s.neo4j_user == "neo4j"
    assert s.neo4j_password == ""
    assert s.qdrant_url == "http://localhost:6333"
    assert s.qdrant_api_key is None
    assert s.llm_provider == "local"
    assert s.local_llm_model_path == "./models/llama-3.2-3b-instruct-q4.gguf"
    assert s.log_level == "INFO"


def test_covers_real_env_file(monkeypatch, tmp_path):
    """A real .env file at repo root must be picked up (non-_env_file=None path)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("NEO4J_URI=bolt://fromfile:7687\nLOG_LEVEL=WARNING\n", encoding="utf-8")
    s = Settings()  # reads .env from cwd
    assert s.neo4j_uri == "bolt://fromfile:7687"
    assert s.log_level == "WARNING"
