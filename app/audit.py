import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(__file__).parent / "data" / "audit.jsonl"


def log(event: str, **details) -> None:
    """Append one JSON line per event. Never overwrite, never edit."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
