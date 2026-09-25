"""Centralised logging configuration for EHR Graph-RAG."""

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging with a timestamp/level/module/message formatter."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(module)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
