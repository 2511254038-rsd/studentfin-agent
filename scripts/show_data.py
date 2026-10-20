"""Read-only data viewer for the demo. Shows what the app stores, without secrets.

  python3 scripts/show_data.py                  # tables in the terminal
  python3 scripts/show_data.py --sqlite out.db  # also write a browsable SQLite snapshot

Password salts and hashes are never printed or exported. Chat text is replaced by its length.
The live app stores data in files under app/data/. The SQLite file is a read-only snapshot
made from those files for inspection. The app does not read it.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"

SCHEMA = """
CREATE TABLE users (
  username TEXT PRIMARY KEY, created_utc TEXT, has_profile INTEGER,
  transfers INTEGER, bdt_balance REAL, usd_balance REAL, password_storage TEXT);
CREATE TABLE profiles (
  username TEXT PRIMARY KEY REFERENCES users(username), display_name TEXT, university TEXT,
  home_country TEXT, study_country TEXT, home_currency TEXT, study_currency TEXT,
  monthly_support_usd REAL);
CREATE TABLE instalments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT REFERENCES users(username),
  label TEXT, amount REAL, currency TEXT, due TEXT, paid INTEGER);
CREATE TABLE transfers (
  txn_id TEXT PRIMARY KEY, username TEXT REFERENCES users(username), ts TEXT, route_id TEXT,
  amount_usd REAL, fees_usd REAL, currency TEXT, debit REAL);
CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event TEXT, username TEXT, tool TEXT,
  allowed INTEGER, tier TEXT, reason TEXT, detail TEXT);
"""


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def load_all():
    users_raw = read_json(DATA / "users.json", {})
    seed = read_json(DATA / "account.json", {}).get("balances", {})
    users, profiles, instalments, transfers = [], [], [], []
    for name in sorted(users_raw):
        rec = users_raw[name]
        created = ""
        if rec.get("created"):
            created = datetime.fromtimestamp(rec["created"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        prof = read_json(DATA / "profiles" / f"{name}.json", None)
        ledger = read_jsonl(DATA / "ledgers" / f"{name}.jsonl")
        balances = dict(seed)
        for tx in ledger:
            cur = tx.get("currency", "BDT")
            balances[cur] = balances.get(cur, 0) - tx.get("debit", 0)
        storage = "missing"
        if rec.get("hash"):
            storage = "scrypt hash, %d hex chars (hidden)" % len(rec["hash"])
        users.append({
            "username": name, "created_utc": created, "has_profile": 1 if prof else 0,
            "transfers": len(ledger), "bdt_balance": round(balances.get("BDT", 0), 2),
            "usd_balance": round(balances.get("USD", 0), 2), "password_storage": storage,
        })
        if prof:
            profiles.append({
                "username": name, "display_name": prof.get("display_name", ""),
                "university": prof.get("university", ""), "home_country": prof.get("home_country", ""),
                "study_country": prof.get("study_country", ""), "home_currency": prof.get("home_currency", ""),
                "study_currency": prof.get("study_currency", ""),
                "monthly_support_usd": prof.get("monthly_support_usd", 0),
            })
            for inst in prof.get("instalments", []):
                instalments.append({
                    "username": name, "label": inst.get("label", ""), "amount": inst.get("amount", 0),
                    "currency": inst.get("currency", ""), "due": inst.get("due", ""),
                    "paid": 1 if inst.get("paid") else 0,
                })
        for t in ledger:
            transfers.append({
                "txn_id": t.get("txn_id"), "username": name, "ts": t.get("ts"),
                "route_id": t.get("route_id"), "amount_usd": t.get("amount_usd"),
                "fees_usd": t.get("fees_usd"), "currency": t.get("currency"), "debit": t.get("debit"),
            })
    audit = []
    for e in read_jsonl(DATA / "audit.jsonl"):
        e = dict(e)
        allowed = e.pop("allowed", None)
        row = {
            "ts": e.pop("ts", ""), "event": e.pop("event", ""), "username": e.pop("user", ""),
            "tool": e.pop("tool", ""), "allowed": None if allowed is None else (1 if allowed else 0),
            "tier": e.pop("tier", ""), "reason": e.pop("reason", ""),
        }
        if "text" in e:
            e["text_chars"] = len(str(e.pop("text")))
        e.pop("prev_hash", None)
        e.pop("hash", None)
        row["detail"] = json.dumps(e, sort_keys=True)[:300]
        audit.append(row)
    return {"users": users, "profiles": profiles, "instalments": instalments,
            "transfers": transfers, "audit": audit}


def cell(value, width=26):
    s = "" if value is None else str(value)
    return s if len(s) <= width else s[: width - 3] + "..."


def show(title, rows, cols, last=None):
    shown = rows if last is None else rows[-last:]
    note = "" if last is None or len(rows) <= last else ", last %d shown" % last
    print("\n== %s (%d rows%s) ==" % (title, len(rows), note))
    if not shown:
        print("(empty)")
        return
    widths = [max(len(c), max(len(cell(r.get(c))) for r in shown)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in shown:
        print("  ".join(cell(r.get(c)).ljust(w) for c, w in zip(cols, widths)))


def write_sqlite(path, t):
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO users VALUES (:username,:created_utc,:has_profile,:transfers,"
        ":bdt_balance,:usd_balance,:password_storage)", t["users"])
    con.executemany(
        "INSERT INTO profiles VALUES (:username,:display_name,:university,:home_country,"
        ":study_country,:home_currency,:study_currency,:monthly_support_usd)", t["profiles"])
    con.executemany(
        "INSERT INTO instalments (username,label,amount,currency,due,paid) "
        "VALUES (:username,:label,:amount,:currency,:due,:paid)", t["instalments"])
    con.executemany(
        "INSERT INTO transfers (txn_id,username,ts,route_id,amount_usd,fees_usd,currency,debit) "
        "VALUES (:txn_id,:username,:ts,:route_id,:amount_usd,:fees_usd,:currency,:debit)", t["transfers"])
    con.executemany(
        "INSERT INTO audit_events (ts,event,username,tool,allowed,tier,reason,detail) "
        "VALUES (:ts,:event,:username,:tool,:allowed,:tier,:reason,:detail)", t["audit"])
    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser(description="Read-only demo data viewer")
    ap.add_argument("--sqlite", help="also write a browsable SQLite snapshot to this path")
    args = ap.parse_args()
    t = load_all()
    show("users", t["users"], ["username", "created_utc", "has_profile", "transfers",
                               "bdt_balance", "usd_balance", "password_storage"])
    show("profiles", t["profiles"], ["username", "display_name", "university", "study_country",
                                     "home_currency", "study_currency"])
    show("instalments", t["instalments"], ["username", "label", "amount", "currency", "due", "paid"])
    show("transfers", t["transfers"], ["txn_id", "username", "route_id", "amount_usd",
                                       "fees_usd", "debit", "ts"])
    show("audit events", t["audit"], ["ts", "event", "username", "tool", "allowed", "tier", "reason"], last=15)
    if args.sqlite:
        write_sqlite(args.sqlite, t)
        print("\nSQLite snapshot written to %s (read-only copy; the app does not read it)" % args.sqlite)


if __name__ == "__main__":
    main()