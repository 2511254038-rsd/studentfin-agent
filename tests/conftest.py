import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("MODEL", "test-model")

import pytest

from app import agent, audit, tools


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """Every test gets a fresh ledger and audit log in a temp folder."""
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(tools, "LEDGER", tmp_path / "ledger.jsonl")
    agent.PENDING.clear()
    agent.TRACE.clear()
    yield
