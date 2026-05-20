"""Disk-backed session store — 30 day TTL, atomic writes."""
import os, json, re, time, threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "./data"))
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
SESSION_TTL = 30 * 24 * 60 * 60

_cache = {}
_lock = threading.Lock()
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

def _safe(sid): return bool(sid) and bool(_SID_RE.match(sid))
def _path(sid): return SESSIONS_DIR / f"{sid}.json"

def get_session(sid, create_if_missing=True):
    if not _safe(sid):
        return {"history": [], "lastSeen": int(time.time())} if create_if_missing else None
    with _lock:
        s = _cache.get(sid)
        if s is None:
            p = _path(sid)
            if p.exists():
                try:
                    with p.open("r", encoding="utf-8") as f: s = json.load(f)
                    if time.time() - s.get("lastSeen", 0) > SESSION_TTL: s = None
                except Exception: s = None
        if s is None:
            if not create_if_missing: return None
            s = {"history": [], "lastSeen": int(time.time())}
        _cache[sid] = s
        return s

def save_session(sid, session):
    if not _safe(sid): return
    p = _path(sid); tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f: json.dump(session, f)
    tmp.replace(p)
    with _lock: _cache[sid] = session
