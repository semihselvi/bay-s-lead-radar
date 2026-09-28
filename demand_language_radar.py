from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore

import adaptive_radar_learning as learning
import main as core


VERSION = "1.1-concern-query-learning"
LOOKBACK_DAYS = int(os.getenv("RADAR_CONCERN_LOOKBACK_DAYS", "14") or "14")

SEEDS = (
    {"language": "en", "term": "north cyprus property"},
    {"language": "en", "term": "north cyprus off plan"},
    {"language": "en", "term": "north cyprus payment plan"},
    {"language": "en", "term": "buy apartment north cyprus"},
    {"language": "ru", "term": "купить квартиру северный кипр"},
    {"language": "ru", "term": "недвижимость северный кипр рассрочка"},
    {"language": "ru", "term": "северный кипр первоначальный взнос"},
    {"language": "tr", "term": "kuzey kıbrıs ev almak"},
    {"language": "tr", "term": "kuzey kıbrıs taksitli daire"},
    {"language": "tr", "term": "kuzey kıbrıs peşinat daire"},
)

CONTENT_TITLES = {
    "title_deed": "Koçan/tapu: satın almadan önce hangi kontroller yapılmalı?",
    "payment_plan": "Taksitli alımda peşinat, vade ve gerçek toplam maliyet nasıl okunur?",
    "off_plan_risk": "Off-plan projede teslim ve inşaat riski nasıl kontrol edilir?",
    "developer_trust": "Developer seçerken hangi belgeler ve geçmiş projeler kontrol edilmeli?",
    "foreign_buyer_rules": "Yabancı alıcı Kuzey Kıbrıs'ta satın alırken hangi kuralları bilmeli?",
    "residency": "Gayrimenkul alımı ile oturma izni arasındaki ilişki nedir?",
}


CONCERN_QUERY_TEMPLATES = {
    "payment_plan": (
        ("en", "North Cyprus looking to buy property payment plan"),
        ("en", "North Cyprus apartment down payment installments"),
        ("ru", "Северный Кипр хочу купить квартиру рассрочка"),
        ("ru", "Северный Кипр квартира первоначальный взнос"),
        ("tr", "Kuzey Kıbrıs daire almak istiyorum taksit"),
        ("tr", "Kuzey Kıbrıs ev almak istiyorum peşinat"),
    ),
    "residency": (
        ("en", "North Cyprus looking to buy property residence permit"),
        ("en", "North Cyprus buy apartment residency"),
        ("ru", "Северный Кипр хочу купить квартиру ВНЖ"),
        ("tr", "Kuzey Kıbrıs ev almak istiyorum oturma izni"),
    ),
    "title_deed": (
        ("en", "North Cyprus looking to buy property title deed"),
        ("en", "North Cyprus apartment title deed buy"),
        ("ru", "Северный Кипр хочу купить квартиру титул"),
        ("tr", "Kuzey Kıbrıs daire almak istiyorum koçan"),
        ("tr", "Kuzey Kıbrıs ev satın almak tapu"),
    ),
    "foreign_buyer_rules": (
        ("en", "North Cyprus foreign buyer looking to buy property"),
        ("en", "North Cyprus can foreigners buy apartment"),
        ("ru", "Северный Кипр иностранец хочу купить квартиру"),
        ("tr", "Kuzey Kıbrıs yabancı ev satın almak istiyorum"),
    ),
    "developer_trust": (
        ("en", "North Cyprus looking to buy property reliable developer"),
        ("en", "North Cyprus buy apartment trusted developer"),
        ("ru", "Северный Кипр хочу купить квартиру надежный застройщик"),
        ("tr", "Kuzey Kıbrıs daire almak istiyorum güvenilir müteahhit"),
    ),
    "off_plan_risk": (
        ("en", "North Cyprus looking to buy off plan property"),
        ("en", "North Cyprus buy apartment completion date"),
        ("ru", "Северный Кипр хочу купить квартиру на стадии строительства"),
        ("tr", "Kuzey Kıbrıs inşaattan daire almak istiyorum"),
    ),
}


def concern_query_terms(feedback: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn observed buyer concerns into safe, purchase-intent search language."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts = dict(feedback.get("counts") or {})

    for label, count_raw in sorted(counts.items(), key=lambda x: (-int(x[1] or 0), x[0])):
        count = int(count_raw or 0)
        if count <= 0:
            continue
        score = min(94.0, 45.0 + count * 4.0)
        for language, term in CONCERN_QUERY_TEMPLATES.get(label, ()):
            key = term.casefold()
            if key in seen or not learning.safe_demand_query(term, surface="web"):
                continue
            seen.add(key)
            surfaces = ["web"]
            if learning.safe_demand_query(term, surface="telegram"):
                surfaces.append("telegram")
            out.append({
                "term": term,
                "language": language,
                "seed": f"buyer_concern:{label}",
                "bucket": "observed_buyer_concern",
                "value": count,
                "score": score,
                "surfaces": surfaces,
                "source": "buyer_concern_learning",
            })
    return out


def _value_score(value: Any, *, bucket: str) -> float:
    if isinstance(value, str) and value.casefold() == "breakout":
        return 95.0
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.0
    base = 30.0 if bucket == "rising" else 18.0
    return round(min(100.0, base + min(70.0, numeric * 0.7)), 2)


def related_rows(related: dict[str, Any], *, seed: str, language: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("rising", "top"):
        frame = related.get(bucket)
        if frame is None:
            continue
        try:
            records = frame.to_dict("records")
        except Exception:
            records = frame if isinstance(frame, list) else []
        for row in records:
            term = " ".join(str((row or {}).get("query") or "").split())
            key = term.casefold()
            if not term or key in seen:
                continue
            if not learning.safe_demand_query(term, surface="web"):
                continue
            seen.add(key)
            surfaces = ["web"]
            if learning.safe_demand_query(term, surface="telegram"):
                surfaces.append("telegram")
            out.append({
                "term": term,
                "language": language,
                "seed": seed,
                "bucket": bucket,
                "value": (row or {}).get("value", 0),
                "score": _value_score((row or {}).get("value", 0), bucket=bucket),
                "surfaces": surfaces,
            })
    return out


def collect_trend_terms() -> tuple[list[dict[str, Any]], list[str]]:
    from trendspy import Trends

    tr = Trends()
    found: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for item in SEEDS:
        seed = item["term"]
        try:
            related = tr.related_queries(seed, timeframe="today 3-m")
            for row in related_rows(related, seed=seed, language=item["language"]):
                key = row["term"].casefold()
                previous = found.get(key)
                if previous is None or row["score"] > previous["score"]:
                    found[key] = row
            time.sleep(1.0)
        except Exception as exc:
            errors.append(f"{seed}:{type(exc).__name__}:{exc}")

    return sorted(found.values(), key=lambda x: (-x["score"], x["term"].casefold())), errors


def save_terms(db: Any, terms: list[dict[str, Any]]) -> int:
    saved = 0
    now = datetime.now(timezone.utc).isoformat()
    for row in terms:
        term = str(row["term"])
        doc_id = hashlib.sha256(term.casefold().encode("utf-8", "ignore")).hexdigest()
        ref = db.collection("bay_s_radar_query_terms").document(doc_id)
        try:
            snap = ref.get()
            old = snap.to_dict() if snap.exists else {}
        except Exception:
            old = {}

        seeds = set(old.get("seeds") or [])
        seeds.add(str(row.get("seed") or ""))
        ref.set({
            "term": term,
            "language": row.get("language") or old.get("language") or "",
            "source": row.get("source") or "google_trends_related",
            "bucket": row.get("bucket") or "",
            "value": row.get("value", 0),
            "score": max(float(old.get("score", 0) or 0), float(row.get("score", 0) or 0)),
            "surfaces": row.get("surfaces") or ["web"],
            "seeds": sorted(x for x in seeds if x),
            "seen_count": int(old.get("seen_count", 0) or 0) + 1,
            "active": True,
            "updated_at": now,
            "radar_version": VERSION,
        }, merge=True)
        saved += 1
    return saved


def recent_concerns(db: Any, *, limit: int = 300) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    rows: list[dict[str, Any]] = []
    try:
        stream = (
            db.collection("bay_s_buyer_concerns")
            .order_by("found_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        for snap in stream:
            data = snap.to_dict() or {}
            raw = str(data.get("found_at") or "")
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                continue
            rows.append(data)
    except Exception:
        return []
    return rows


def build_content_feedback(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    best: dict[str, dict[str, Any]] = {}
    sources: Counter[str] = Counter()

    for row in rows:
        sources[str(row.get("source") or "unknown")] += 1
        for label in row.get("labels") or []:
            label = str(label)
            counts[label] += 1
            score = int(row.get("score", 0) or 0)
            if label not in best or score > int(best[label].get("score", 0) or 0):
                best[label] = row

    topics = []
    for label, count in counts.most_common():
        example = best.get(label, {})
        topics.append({
            "label": label,
            "count": count,
            "suggested_title": CONTENT_TITLES.get(label, label.replace("_", " ").title()),
            "example_question": " ".join(str(example.get("text") or "").split())[:420],
            "source": example.get("source") or "",
            "score": int(example.get("score", 0) or 0),
        })

    return {
        "lookback_days": LOOKBACK_DAYS,
        "concern_rows": len(rows),
        "counts": dict(counts),
        "sources": dict(sources),
        "topics": topics,
    }


def save_content_feedback(db: Any, feedback: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    doc_id = now.strftime("%Y-%m-%d")
    db.collection("bay_s_content_signals").document(doc_id).set({
        **feedback,
        "generated_at": now.isoformat(),
        "radar_version": VERSION,
    }, merge=True)


def run() -> None:
    db = core.db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    marker = db.collection("bay_s_demand_language_runs").document(today)
    try:
        if marker.get().exists and os.getenv("RADAR_DEMAND_FORCE", "0") != "1":
            print("DEMAND_LANGUAGE_RADAR already completed today")
            return
    except Exception:
        pass

    feedback = build_content_feedback(recent_concerns(db))
    concern_terms = concern_query_terms(feedback)

    # Trends is optional enrichment only. Real observed buyer concerns are the
    # primary query-learning signal, so a Trends outage cannot stop learning.
    trend_terms, trend_errors = collect_trend_terms()
    combined: dict[str, dict[str, Any]] = {}
    for row in [*concern_terms, *trend_terms]:
        key = str(row.get("term") or "").casefold()
        if not key:
            continue
        previous = combined.get(key)
        if previous is None or float(row.get("score", 0) or 0) > float(previous.get("score", 0) or 0):
            combined[key] = row
    terms = sorted(combined.values(), key=lambda x: (-float(x.get("score", 0) or 0), str(x.get("term") or "").casefold()))
    saved = save_terms(db, terms)
    save_content_feedback(db, feedback)

    marker.set({
        "date": today,
        "terms_found": len(terms),
        "terms_saved": saved,
        "concern_terms": len(concern_terms),
        "trend_terms": len(trend_terms),
        "trend_errors": trend_errors[:20],
        "content_topics": len(feedback.get("topics") or []),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "radar_version": VERSION,
    }, merge=True)

    top_terms = ", ".join(x["term"] for x in terms[:5]) or "-"
    top_topics = ", ".join(
        f"{x['label']}:{x['count']}"
        for x in (feedback.get("topics") or [])[:5]
    ) or "-"
    core.telegram(
        "🧠 PRIME RADAR | TALEP DİLİ\n\n"
        f"Yeni/yenilenen arama terimi: {saved}\n"
        f"Concern kaynaklı terim: {len(concern_terms)} | Trends terimi: {len(trend_terms)}\n"
        f"Öne çıkan terimler: {top_terms}\n"
        f"Buyer concern: {feedback.get('concern_rows', 0)}\n"
        f"İçerik sinyalleri: {top_topics}\n"
        f"Trends hata: {len(trend_errors)}"
    )

    print("DEMAND_LANGUAGE_RADAR", json.dumps({
        "version": VERSION,
        "terms_found": len(terms),
        "terms_saved": saved,
        "concern_terms": concern_terms,
        "trend_terms": trend_terms,
        "trend_errors": trend_errors,
        "content_feedback": feedback,
    }, ensure_ascii=False))


if __name__ == "__main__":
    run()
