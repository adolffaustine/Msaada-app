"""JSON ticket store — atomic writes."""
import os, json, threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "./data"))
PATH = DATA_DIR / "tickets.json"
_lock = threading.Lock()

def load_tickets():
    if not PATH.exists(): return []
    try:
        with PATH.open("r", encoding="utf-8") as f: return json.load(f)
    except Exception: return []

def save_tickets(tickets):
    with _lock:
        tmp = PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f: json.dump(tickets, f, indent=2)
        tmp.replace(PATH)

def append_ticket(ticket):
    with _lock:
        tickets = load_tickets(); tickets.append(ticket); save_tickets(tickets)
