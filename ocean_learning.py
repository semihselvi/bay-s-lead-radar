from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

QUERY_COLLECTION = "bay_s_ocean_query_learning"
SOURCE_COLLECTION = "bay_s_ocean_source_learning"
DISCOVERED_SOURCE_COLLECTION = "bay_s_ocean_discovered_sources"
PERSON_COLLECTION = "bay_s_ocean_person_journey"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()


def normalize_identity(item: dict) -> str:
    author = str(item.get("author") or "").strip().casefold()
    source = str(item.get("source") or "").strip().casefold()
    url = str(item.get("url") or "").strip()
    if author:
        return stable_id("person", f"{source}|{author}")
    if url:
        return stable_id("person", url.split("?", 1)[0].rstrip("/"))
    text = " ".join(str(item.get("text") or "").split()).casefold()[:300]
    return stable_id("person", text)


def query_score(data: dict) -> float:
    runs = int(data.get("runs") or 0)
    raw = int(data.get("raw") or 0)
    qualified = int(data.get("qualified") or 0)
    new = int(data.get("new") or 0)

    exploration = 24.0 if runs == 0 else 0.0
    new_value = new * 35.0
    new_eff = (new / max(1, raw)) * 250.0
    qual_support = qualified * 2.0
    maturity_penalty = min(12.0, math.log2(runs + 1) * 2.0)
    stale_penalty = 0.0
    if runs >= 2 and new == 0:
        stale_penalty = min(70.0, 15.0 + runs * 4.0 + qualified * 1.5)
    return exploration + new_value + new_eff + qual_support - maturity_penalty - stale_penalty


def source_score(data: dict) -> float:
    runs = int(data.get("runs") or 0)
    raw = int(data.get("raw") or 0)
    qualified = int(data.get("qualified") or 0)
    new = int(data.get("new") or 0)

    exploration = 20.0 if runs == 0 else 0.0
    return (
        exploration
        + new * 30.0
        + (new / max(1, raw)) * 220.0
        + qualified * 1.5
        - (10.0 if runs >= 3 and new == 0 else 0.0)
    )


def rank_queries(db, queries: list[str]) -> list[str]:
    if not db:
        return list(queries)
    scored = []
    for q in queries:
        doc_id = stable_id("query", q)
        data = {}
        try:
            snap = db.collection(QUERY_COLLECTION).document(doc_id).get()
            if snap.exists:
                data = snap.to_dict() or {}
        except Exception:
            pass
        scored.append((query_score(data), q))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for _, q in scored]


def update_query_stats(db, query: str, raw: int = 0, qualified: int = 0, new: int = 0):
    if not db or not query:
        return
    ref = db.collection(QUERY_COLLECTION).document(stable_id("query", query))
    try:
        ref.set({
            "query": query,
            "last_run_at": now_iso(),
        }, merge=True)
        from google.cloud import firestore
        ref.update({
            "runs": firestore.Increment(1),
            "raw": firestore.Increment(raw),
            "qualified": firestore.Increment(qualified),
            "new": firestore.Increment(new),
        })
    except Exception as exc:
        print("OCEAN_QUERY_LEARNING_WRITE_ERROR", type(exc).__name__, exc)


def update_source_stats(db, source: str, raw: int = 0, qualified: int = 0, new: int = 0):
    if not db or not source:
        return
    ref = db.collection(SOURCE_COLLECTION).document(stable_id("source", source))
    try:
        ref.set({"source": source, "last_run_at": now_iso()}, merge=True)
        from google.cloud import firestore
        ref.update({
            "runs": firestore.Increment(1),
            "raw": firestore.Increment(raw),
            "qualified": firestore.Increment(qualified),
            "new": firestore.Increment(new),
        })
    except Exception as exc:
        print("OCEAN_SOURCE_LEARNING_WRITE_ERROR", type(exc).__name__, exc)


def load_source_scores(db) -> dict[str, float]:
    if not db:
        return {}
    out = {}
    try:
        for doc in db.collection(SOURCE_COLLECTION).stream():
            data = doc.to_dict() or {}
            name = str(data.get("source") or "")
            if name:
                out[name] = source_score(data)
    except Exception as exc:
        print("OCEAN_SOURCE_LEARNING_READ_ERROR", type(exc).__name__, exc)
    return out



def learn_discovered_source(db, source_key: str, source_type: str, url: str = "", qualified: int = 0, new: int = 0):
    if not db or not source_key:
        return
    ref = db.collection(DISCOVERED_SOURCE_COLLECTION).document(stable_id("discovered-source", f"{source_type}|{source_key}"))
    try:
        ref.set({
            "source_key": source_key,
            "source_type": source_type,
            "url": url,
            "last_seen_at": now_iso(),
        }, merge=True)
        from google.cloud import firestore
        ref.update({
            "seen": firestore.Increment(1),
            "qualified": firestore.Increment(qualified),
            "new": firestore.Increment(new),
        })
    except Exception as exc:
        print("OCEAN_DISCOVERED_SOURCE_WRITE_ERROR", type(exc).__name__, exc)


def best_discovered_sources(db, limit: int = 20) -> list[dict]:
    if not db:
        return []
    rows = []
    try:
        for doc in db.collection(DISCOVERED_SOURCE_COLLECTION).stream():
            data = doc.to_dict() or {}
            seen = int(data.get("seen") or 0)
            qualified = int(data.get("qualified") or 0)
            new = int(data.get("new") or 0)
            score = new * 30.0 + qualified * 4.0 + (new / max(1, seen)) * 120.0
            data["score"] = score
            rows.append(data)
    except Exception as exc:
        print("OCEAN_DISCOVERED_SOURCE_READ_ERROR", type(exc).__name__, exc)
    rows.sort(key=lambda x: x.get("score", 0), reverse=True)
    return rows[:max(1, limit)]


def record_person_event(db, lead: dict) -> dict:
    person_id = normalize_identity(lead)
    current = {
        "person_id": person_id,
        "events": 1,
        "max_intent": int(lead.get("intent_score") or 0),
        "sources": [str(lead.get("source") or "")],
        "first_seen_at": now_iso(),
        "last_seen_at": now_iso(),
        "latest_url": str(lead.get("url") or ""),
        "latest_text": str(lead.get("text") or "")[:1200],
        "latest_author": str(lead.get("author") or ""),
    }
    if not db:
        current["journey_score"] = current["max_intent"]
        return current

    ref = db.collection(PERSON_COLLECTION).document(person_id)
    try:
        snap = ref.get()
        old = snap.to_dict() or {} if snap.exists else {}
        events = int(old.get("events") or 0) + 1
        max_intent = max(int(old.get("max_intent") or 0), int(lead.get("intent_score") or 0))
        sources = sorted(set((old.get("sources") or []) + [str(lead.get("source") or "")]))
        first_seen = old.get("first_seen_at") or now_iso()
        journey_bonus = min(12, max(0, events - 1) * 3) + min(8, max(0, len(sources) - 1) * 4)
        journey_score = min(100, max_intent + journey_bonus)

        current = {
            "person_id": person_id,
            "events": events,
            "max_intent": max_intent,
            "sources": sources,
            "first_seen_at": first_seen,
            "last_seen_at": now_iso(),
            "latest_url": str(lead.get("url") or ""),
            "latest_text": str(lead.get("text") or "")[:1200],
            "latest_author": str(lead.get("author") or ""),
            "journey_score": journey_score,
        }
        ref.set(current, merge=True)
    except Exception as exc:
        print("OCEAN_PERSON_JOURNEY_ERROR", type(exc).__name__, exc)
        current["journey_score"] = current["max_intent"]
    return current
