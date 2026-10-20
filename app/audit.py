import json
from datetime import datetime, timezone
from pathlib import Path

from app import userctx

LOG_FILE = Path(__file__).parent / "data" / "audit.jsonl"


def log(event: str, **details) -> None:
    """Append one JSON line per event. Never overwrite, never edit.
    The acting user (if any) is recorded automatically."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    user = userctx.current()
    if user and "user" not in record:
        record["user"] = user
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")