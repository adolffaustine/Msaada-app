"""Lightweight vector store — Ollama nomic-embed-text + cosine similarity."""
import os, json, time, threading
from pathlib import Path
import numpy as np
import httpx

ANTHROPIC_FOUNDRY_BASE_URL = os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL", "https://api.anthropic.com")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "./data"))
PATH = DATA_DIR / "vectors.json"

_lock = threading.Lock()
_docs = None

def _load():
    global _docs
    if _docs is not None: return _docs
    if PATH.exists():
        try:
            with PATH.open("r", encoding="utf-8") as f: _docs = json.load(f)
        except Exception: _docs = []
    else: _docs = []
    return _docs

def _save():
    tmp = PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f: json.dump(_docs, f)
    tmp.replace(PATH)

def embed(text: str):
    if not text or not text.strip(): return None
    try:
        r = httpx.post(f"{ANTHROPIC_FOUNDRY_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text[:8000]}, timeout=30)
        r.raise_for_status()
        emb = r.json().get("embedding")
        return emb if isinstance(emb, list) and emb else None
    except Exception as e:
        print("embed error:", e); return None

def add(doc_id: str, text: str, metadata: dict | None = None):
    if not doc_id or not text: return False
    vec = embed(text)
    if vec is None: return False
    with _lock:
        _load()
        _docs[:] = [d for d in _docs if d.get("id") != doc_id]
        _docs.append({"id": doc_id, "text": text, "embedding": vec,
                      "metadata": metadata or {}, "ts": int(time.time())})
        _save()
    return True

def _cosine_topk(query_vec, all_vecs, k):
    if all_vecs.size == 0: return []
    q = np.array(query_vec, dtype=np.float32)
    q_norm = q / (np.linalg.norm(q) + 1e-12)
    A = all_vecs / (np.linalg.norm(all_vecs, axis=1, keepdims=True) + 1e-12)
    sims = A @ q_norm
    top = np.argsort(-sims)[:k]
    return [(int(i), float(sims[int(i)])) for i in top]

def search(query: str, k: int = 5, min_score: float = 0.55):
    if not query or not query.strip(): return []
    qv = embed(query)
    if qv is None: return []
    with _lock:
        docs = _load()
        if not docs: return []
        try: mat = np.array([d["embedding"] for d in docs], dtype=np.float32)
        except Exception: return []
    pairs = _cosine_topk(qv, mat, k)
    out = []
    for idx, score in pairs:
        if score < min_score: continue
        d = docs[idx]
        out.append({"id": d["id"], "score": round(score, 3), "text": d["text"],
                    "metadata": d.get("metadata") or {}, "ts": d.get("ts")})
    return out
