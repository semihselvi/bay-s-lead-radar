from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import nc_v6_broad_radar as v6

VERSION = "ru-public-buyer-1.0"

SOURCE_DOMAINS = {
    "VK": ["vk.com"],
    "Odnoklassniki": ["ok.ru"],
    "Pikabu": ["pikabu.ru"],
    "MailRu Answers": ["otvet.mail.ru"],
    "VC.ru": ["vc.ru"],
    "DTF": ["dtf.ru"],
}

QUERIES = [
    '"Северный Кипр" хочу купить квартиру',
    '"Северный Кипр" хочу купить недвижимость',
    '"Северный Кипр" ищу квартиру купить',
    '"Северный Кипр" где купить квартиру',
    '"Северный Кипр" стоит ли покупать недвижимость',
    '"Северный Кипр" инвестиции недвижимость',
    '"Северный Кипр" бюджет квартира',
    '"Северный Кипр" рассрочка квартира',
    'Искеле хочу купить квартиру',
    'Гирне хочу купить квартиру',
    'Фамагуста хочу купить квартиру',
]

RENT_ONLY_RE = re.compile(
    r"(?:\bсниму\b|\bхочу\s+снять\b|\bаренд\w*\b|\bдолгосроч\w*\b|\bпосуточ\w*\b)",
    re.I,
)

SELLER_RE = re.compile(
    r"(?:\bпродаю\b|\bпродам\b|\bпрода[её]тся\b|\bсдаю\b|\bсдам\b|"
    r"\bагентств\w*\b|\bзастройщик\w*\b|\bриелтор\w*\b|\bриэлтор\w*\b)",
    re.I,
)

BUYER_STRONG_RE = re.compile(
    r"(?:\bхочу\s+купить\b|\bхотим\s+купить\b|\bкуплю\b|"
    r"\bпланир\w*\s+купить\b|\bищу\b.{0,80}\b(?:купить|на\s+покупку|для\s+покупки)\b|"
    r"\bгде\s+(?:лучше\s+)?купить\b|\bстоит\s+ли\s+покупать\b|"
    r"\bчто\s+можно\s+купить\b|\bбюджет\b.{0,80}\b(?:квартир\w*|дом\w*|вилл\w*|недвижимост\w*)\b)",
    re.I | re.S,
)


def _domain_source(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold()
    for source, domains in SOURCE_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return source
    return "Russian Public Web"


def _stable_id(item: dict) -> str:
    raw = "|".join([
        str(item.get("url") or ""),
        str(item.get("title") or ""),
        str(item.get("text") or "")[:500],
    ])
    return hashlib.sha256(("ru-public|" + raw).encode("utf-8", "ignore")).hexdigest()


def classify_item(item: dict) -> tuple[dict | None, str]:
    title = str(item.get("title") or "")
    text = str(item.get("text") or "")
    blob = f"{title} {text}".strip()
    url = str(item.get("url") or "")

    if not blob or not url:
        return None, "missing_content"

    if not v6.has_nc_geo(blob):
        return None, "no_north_cyprus_context"

    if RENT_ONLY_RE.search(blob) and not BUYER_STRONG_RE.search(blob):
        return None, "rental_only"

    if SELLER_RE.search(blob) and not BUYER_STRONG_RE.search(blob):
        return None, "seller_or_provider"

    signal, reason = v6.classify_text(
        blob,
        group="Russian public North Cyprus",
        explicit_geo=True,
    )
    if signal is None:
        return None, reason

    if signal.get("intent_type") not in {"BUYER", "INVESTOR"}:
        return None, f"not_sales_buyer:{signal.get('intent_type','')}"

    if not BUYER_STRONG_RE.search(blob) and signal.get("intent_score", 0) < 72:
        return None, "weak_purchase_intent"

    lead = {
        **item,
        **signal,
        "lead_id": _stable_id(item),
        "source": _domain_source(url),
        "platform": _domain_source(url),
        "source_type": "russian_public_indexed_post",
        "market": "north_cyprus",
        "route_to": "Prime Kıbrıs",
        "classification": "HOT" if signal.get("intent_score", 0) >= 82 else "WARM",
        "radar_version": VERSION,
        "found_at": datetime.now(timezone.utc).isoformat(),
    }
    return lead, "accepted"


def collect_candidates() -> tuple[list[dict], dict]:
    seen: set[str] = set()
    accepted: list[dict] = []
    stats = {
        "queries": 0,
        "raw": 0,
        "accepted": 0,
        "rejects": {},
        "by_source": {},
    }

    for source, domains in SOURCE_DOMAINS.items():
        for query in QUERIES:
            stats["queries"] += 1
            rows = v6.search_debug(query, domains)
            stats["raw"] += len(rows)

            for item in rows:
                key = _stable_id(item)
                if key in seen:
                    continue
                seen.add(key)

                lead, reason = classify_item(item)
                if lead is None:
                    stats["rejects"][reason] = stats["rejects"].get(reason, 0) + 1
                    continue

                accepted.append(lead)
                stats["accepted"] += 1
                stats["by_source"][source] = stats["by_source"].get(source, 0) + 1

    return accepted, stats


def persist_and_notify(leads: list[dict]) -> int:
    client = v6.core.db()
    new_count = 0

    for lead in leads:
        ref = client.collection(v6.core.COLLECTION).document(lead["lead_id"])
        snap = ref.get()
        if snap.exists:
            continue

        ref.set(lead, merge=True)
        v6.notify_lead(lead, "RU-PUBLIC")
        new_count += 1

    return new_count


def main() -> None:
    leads, stats = collect_candidates()
    new_count = persist_and_notify(leads)

    stats["new_saved"] = new_count
    stats["version"] = VERSION
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        client = v6.core.db()
        doc_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        client.collection("bay_s_lead_radar_ru_public_scans").document(doc_id).set(stats)
    except Exception as exc:
        stats["scan_log_error"] = f"{type(exc).__name__}:{exc}"

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
