from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


CONCERN_PATTERNS = {
    "title_deed": re.compile(
        r"(?:title\s+deed|deed|ko[çc]an|tapu|pre[-\s]?74|exchange\s+title|турецк\w*\s+титул|титул\w*)",
        re.I,
    ),
    "payment_plan": re.compile(
        r"(?:payment\s+plan|installment|instalment|down\s*payment|deposit|taksit|peşinat|pesinat|рассроч\w*|предоплат\w*|первоначальн\w*\s+взнос)",
        re.I,
    ),
    "off_plan_risk": re.compile(
        r"(?:off[-\s]?plan|under\s+construction|completion\s+date|handover|teslim\s+tarihi|inşaat\s+halinde|стройк\w*|срок\s+сдач\w*)",
        re.I,
    ),
    "developer_trust": re.compile(
        r"(?:developer|builder|construction\s+company|geliştirici|m[üu]teahhit|şirket\s+güvenilir|застройщик\w*|надежн\w*\s+застройщик)",
        re.I,
    ),
    "foreign_buyer_rules": re.compile(
        r"(?:foreigner|foreign\s+buyer|can\s+foreigners\s+buy|yabanc[ıi].{0,30}(?:alabilir|satın)|иностранец\w*.{0,40}купить|разрешени\w*.{0,40}покупк)",
        re.I,
    ),
    "residency": re.compile(
        r"(?:residency|residence\s+permit|oturma\s+izni|ikamet|внж|вид\s+на\s+жительство)",
        re.I,
    ),
}

QUESTION_RE = re.compile(
    r"(?:\?|how\b|what\b|which\b|where\b|safe\b|worth\b|recommend\w*|"
    r"nas[ıi]l\b|hangi\b|nerede\b|güvenilir\b|mantıklı\b|"
    r"как\b|что\b|какой\b|где\b|безопасн\w*|стоит\s+ли|посовету\w*)",
    re.I,
)


def concern_labels(text: str) -> list[str]:
    value = str(text or "")
    return [name for name, pattern in CONCERN_PATTERNS.items() if pattern.search(value)]


def concern_signal(text: str, *, has_north_context: bool) -> dict[str, Any] | None:
    labels = concern_labels(text)
    if not labels or not has_north_context:
        return None
    score = 50 + min(30, len(labels) * 8)
    if QUESTION_RE.search(text or ""):
        score += 12
    return {
        "labels": labels,
        "score": min(score, 95),
        "question_like": bool(QUESTION_RE.search(text or "")),
    }


def query_doc_id(query: str) -> str:
    return hashlib.sha256(str(query or "").casefold().encode("utf-8", "ignore")).hexdigest()


def yield_score(stats: dict[str, Any]) -> float:
    runs = max(1, int(stats.get("runs", 0) or 0))
    raw = max(0, int(stats.get("raw", 0) or 0))
    valid = max(0, int(stats.get("valid", 0) or 0))
    unique = max(0, int(stats.get("unique", stats.get("valid", 0)) or 0))
    new = max(0, int(stats.get("new", 0) or 0))
    north = max(0, int(stats.get("north_context", 0) or 0))

    # Buyers dominate the score; north-context efficiency is a small tiebreaker.
    buyer_value = (valid * 6.0) + (unique * 4.0) + (new * 8.0)
    efficiency = (valid / max(1, raw)) * 100.0
    north_eff = (north / max(1, raw)) * 10.0
    maturity_penalty = min(6.0, math.log2(runs + 1))
    return round(buyer_value + efficiency + north_eff - maturity_penalty, 4)


def rank_queries(queries: Iterable[str], history: dict[str, dict[str, Any]]) -> list[str]:
    indexed = {q: i for i, q in enumerate(queries)}
    return sorted(
        indexed,
        key=lambda q: (
            -yield_score(history.get(q, {})),
            indexed[q],
        ),
    )


def read_query_history(db: Any, queries: Iterable[str], collection: str = "bay_s_radar_query_yield") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for query in queries:
        try:
            snap = db.collection(collection).document(query_doc_id(query)).get()
            if snap.exists:
                data = snap.to_dict() or {}
                if str(data.get("query") or "") == query:
                    out[query] = data
        except Exception:
            continue
    return out


def update_query_yield(
    db: Any,
    query: str,
    run_stats: dict[str, Any],
    *,
    collection: str = "bay_s_radar_query_yield",
) -> None:
    ref = db.collection(collection).document(query_doc_id(query))
    try:
        snap = ref.get()
        old = snap.to_dict() if snap.exists else {}
    except Exception:
        old = {}

    merged = {
        "query": query,
        "runs": int(old.get("runs", 0) or 0) + 1,
        "raw": int(old.get("raw", 0) or 0) + int(run_stats.get("raw", 0) or 0),
        "north_context": int(old.get("north_context", 0) or 0) + int(run_stats.get("north_context", 0) or 0),
        "valid": int(old.get("valid", 0) or 0) + int(run_stats.get("valid", 0) or 0),
        "unique": int(old.get("unique", 0) or 0) + int(run_stats.get("unique", 0) or 0),
        "new": int(old.get("new", 0) or 0) + int(run_stats.get("new", 0) or 0),
        "last_run": dict(run_stats),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    merged["score"] = yield_score(merged)
    ref.set(merged, merge=True)


def update_source_yield(
    db: Any,
    source: str,
    *,
    scanned: int,
    valid: int,
    new: int,
    collection: str = "bay_s_radar_source_yield",
) -> None:
    doc_id = hashlib.sha256(str(source or "").casefold().encode("utf-8", "ignore")).hexdigest()
    ref = db.collection(collection).document(doc_id)
    try:
        snap = ref.get()
        old = snap.to_dict() if snap.exists else {}
    except Exception:
        old = {}

    runs = int(old.get("runs", 0) or 0) + 1
    total_scanned = int(old.get("scanned", 0) or 0) + int(scanned or 0)
    total_valid = int(old.get("valid", 0) or 0) + int(valid or 0)
    total_new = int(old.get("new", 0) or 0) + int(new or 0)
    score = round(
        (total_valid * 6.0 + total_new * 10.0) / max(1.0, math.log2(total_scanned + 2)),
        4,
    )
    ref.set({
        "source": source,
        "runs": runs,
        "scanned": total_scanned,
        "valid": total_valid,
        "new": total_new,
        "score": score,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, merge=True)


def save_concern(
    db: Any,
    *,
    source: str,
    url: str,
    text: str,
    labels: list[str],
    score: int,
    published: str = "",
    collection: str = "bay_s_buyer_concerns",
) -> None:
    stable = f"{source}|{url}|{text[:500]}"
    doc_id = hashlib.sha256(stable.encode("utf-8", "ignore")).hexdigest()
    db.collection(collection).document(doc_id).set({
        "source": source,
        "url": url,
        "text": str(text or "")[:2000],
        "labels": list(labels),
        "score": int(score),
        "published": published,
        "found_at": datetime.now(timezone.utc).isoformat(),
    }, merge=True)
