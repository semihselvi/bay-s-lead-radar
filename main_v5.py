from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import main as core


VERSION = "5.0-buyer-expansion"
WEB_MAX_AGE_DAYS = int(os.getenv("RADAR_V5_WEB_MAX_AGE_DAYS", "90"))
TELEGRAM_BACKFILL_DAYS = int(os.getenv("RADAR_V5_TELEGRAM_BACKFILL_DAYS", "7"))
TELEGRAM_BACKFILL_LIMIT = int(os.getenv("RADAR_V5_TELEGRAM_BACKFILL_LIMIT", "12"))

# Keep Telegram recent enough to catch a missed scheduled run, without turning the
# user account into a deep-history crawler.
core.TELEGRAM_HOURS = int(os.getenv("RADAR_V5_TELEGRAM_HOURS", "48"))


EXA_QUERIES: list[tuple[str, list[str] | None]] = [
    ("North Cyprus I want to buy property apartment villa", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("Northern Cyprus looking to buy property personal buyer", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("North Cyprus considering buying property expat", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("North Cyprus which area should I buy property", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("North Cyprus can foreigners buy property advice", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("moving to North Cyprus buying home property", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("retire North Cyprus buy property personal", ["expat.com", "britishexpats.com", "reddit.com"]),
    ("Северный Кипр хочу купить недвижимость", ["reddit.com", "expat.com"]),
    ("Северный Кипр ищу квартиру купить", ["reddit.com", "expat.com"]),
    ("Северный Кипр стоит ли покупать недвижимость", ["reddit.com", "expat.com"]),
    ("Nordzypern ich suche Immobilie zum Kauf", ["reddit.com", "expat.com"]),
    ("Nordzypern Wohnung kaufen Auswandern", ["reddit.com", "expat.com"]),
    ("Nordzypern welche Region Immobilie kaufen", ["reddit.com", "expat.com"]),
    ("Cypr Północny chcę kupić nieruchomość", ["reddit.com", "expat.com"]),
    ("Cypr Północny mieszkanie kupić", ["reddit.com", "expat.com"]),
]

REDDIT_QUERIES = [
    '"North Cyprus" "looking to buy" property',
    '"Northern Cyprus" buying property',
    '"North Cyprus" moving property',
    '"TRNC" buy apartment',
    '"Nordzypern" Immobilie kaufen',
    '"Северный Кипр" купить недвижимость',
]

NORTH_RE = re.compile(
    r"\b(?:north(?:ern)?\s+cyprus|trnc|kktc|nordzypern|nord\s*zypern|"
    r"северн(?:ый|ом)\s+кипр(?:е)?|cypr\s+p[oó]łnocny|p[oó]łnocnym\s+cyprze|"
    r"iskele|İskele|long\s+beach|girne|kyrenia|famagusta|gazimağusa|gazimagusa|"
    r"esentepe|tatl[iı]su|bafra|yenibo[gğ]azi[cç]i)\b",
    re.I,
)

DIRECT_PATTERNS = [
    re.compile(r"\b(?:i|we)\b.{0,35}\b(?:want|looking|planning|plan|considering|ready|hoping|would\s+like)\b.{0,80}\b(?:buy|purchase|buying|purchasing)\b", re.I | re.S),
    re.compile(r"\b(?:looking\s+to\s+buy|want\s+to\s+buy|ready\s+to\s+buy|cash\s+buyer)\b", re.I),
    re.compile(r"\b(?:my|our)\s+budget\b.{0,160}\b(?:property|apartment|flat|house|villa|studio)\b", re.I | re.S),
    re.compile(r"\b(?:я|мы)\b.{0,35}\b(?:хочу|хотим|планирую|планируем|ищу|ищем|готов\w*)\b.{0,100}\b(?:купить|покупк\w*)\b", re.I | re.S),
    re.compile(r"\b(?:хочу\s+купить|хотим\s+купить|ищу\s+недвижимост\w*|ищу\s+квартир\w*)\b", re.I),
    re.compile(r"\b(?:ich|wir)\b.{0,35}\b(?:suche|suchen|möchte|moechte|möchten|moechten|will|wollen|plane|planen)\b.{0,120}\b(?:kaufen|erwerben|zum\s+kauf)\b", re.I | re.S),
    re.compile(r"\bsuche\b.{0,120}\b(?:immobilie|wohnung|haus|villa|apartment)\w*\b.{0,100}\b(?:zum\s+kauf|zu\s+kaufen)\b", re.I | re.S),
    re.compile(r"\b(?:ja|my)\b.{0,35}\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,120}\b(?:kupić|kupic|zakupić|zakupic)\b", re.I | re.S),
    re.compile(r"\bszukam\b.{0,120}\b(?:nieruchomość|nieruchomosci|mieszkanie|apartament|willa|dom)\w*\b.{0,100}\b(?:do\s+kupienia|kupić|kupic)\b", re.I | re.S),
]

WARM_PATTERNS = [
    re.compile(r"\b(?:which|what)\s+(?:area|region|location).{0,80}\b(?:buy|buying|property)\b", re.I | re.S),
    re.compile(r"\bwhere\s+should\s+(?:i|we)\s+buy\b", re.I),
    re.compile(r"\bcan\s+foreigners?\s+buy\b", re.I),
    re.compile(r"\b(?:is\s+it\s+safe|safe)\s+to\s+buy\b", re.I),
    re.compile(r"\b(?:anyone|who)\s+(?:bought|purchased).{0,120}\b(?:property|apartment|house|villa)\b", re.I | re.S),
    re.compile(r"\b(?:considering|thinking\s+about)\s+(?:buying|purchasing)\b", re.I),
    re.compile(r"\b(?:moving|relocating|retiring)\s+to\b.{0,120}\b(?:buy|buying|property|home)\b", re.I | re.S),
    re.compile(r"\b(?:где\s+лучше\s+купить|стоит\s+ли\s+покупать|как\s+купить|можно\s+ли\s+иностранц\w*\s+купить)\b", re.I),
    re.compile(r"\b(?:welche\s+region|wo\s+sollte\s+ich\s+kaufen|als\s+ausländer\s+kaufen|als\s+auslaender\s+kaufen)\b", re.I),
    re.compile(r"\b(?:gdzie\s+kupić|gdzie\s+kupic|czy\s+cudzoziemiec\s+może\s+kupić|czy\s+cudzoziemiec\s+moze\s+kupic)\b", re.I),
]

SUPPLY_PATTERNS = [
    "for sale", "available now", "available units", "new project", "developer",
    "real estate agency", "estate agent", "realtor", "broker", "commission",
    "contact us", "whatsapp us", "our properties", "our projects", "price from",
    "продается", "продаётся", "продам", "агентство", "риэлтор", "застройщик",
    "zu verkaufen", "zum verkauf", "makler", "projektentwickler",
    "na sprzedaż", "na sprzedaz", "deweloper", "biuro nieruchomości",
]

NEGATIVE_PATTERNS = [
    "already bought", "already purchased", "we bought", "i bought", "found a property",
    "no longer looking", "not buying", "decided not to buy", "renting instead",
    "купил", "купили", "передумал", "уже купил", "уже купили",
    "bereits gekauft", "schon gekauft", "nicht mehr auf der suche",
    "już kupiłem", "juz kupilem", "już kupiliśmy", "juz kupilismy",
]

BUDGET_RE = re.compile(
    r"(?:£|€|\$|₺|₽)\s?\d[\d\s.,]*|\b\d[\d\s.,]*\s?(?:gbp|eur|usd|try|tl|rub|руб|k|m|mln|million)\b",
    re.I,
)
TIME_RE = re.compile(
    r"\b(?:this\s+month|next\s+month|this\s+year|next\s+year|within\s+\d+|soon|"
    r"in\s+\d+\s+(?:weeks?|months?)|2026|2027|в\s+этом\s+году|в\s+следующем\s+году|"
    r"dieses\s+jahr|nächstes\s+jahr|naechstes\s+jahr|w\s+tym\s+roku)\b",
    re.I,
)
PROPERTY_RE = re.compile(
    r"\b(?:property|apartment|flat|house|villa|studio|home|land|immobilie|wohnung|haus|"
    r"недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|"
    r"nieruchomość|nieruchomosci|mieszkanie|apartament|willa|dom)\b",
    re.I,
)


def _blob(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title", "text", "author"))


def _published_recent(item: dict[str, Any], max_days: int = WEB_MAX_AGE_DAYS) -> tuple[bool, bool]:
    raw = str(item.get("published") or "").strip()
    if not raw:
        return True, False
    try:
        value = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=max_days), True
    except Exception:
        return True, False


def classify_web(item: dict[str, Any]) -> dict[str, Any] | None:
    text = _blob(item)
    low = text.casefold()
    if not NORTH_RE.search(text):
        return None
    if any(term in low for term in NEGATIVE_PATTERNS):
        return None
    recent, has_date = _published_recent(item)
    if not recent:
        return None
    direct_hits = sum(bool(p.search(text)) for p in DIRECT_PATTERNS)
    warm_hits = sum(bool(p.search(text)) for p in WARM_PATTERNS)
    supply_hits = sum(term in low for term in SUPPLY_PATTERNS)
    property_context = bool(PROPERTY_RE.search(text))
    if supply_hits >= 2 and direct_hits == 0:
        return None
    if supply_hits >= 3:
        return None
    if direct_hits == 0 and warm_hits == 0:
        return None
    if not property_context and direct_hits == 0:
        return None
    if not has_date and direct_hits == 0:
        return None
    budget = bool(BUDGET_RE.search(text))
    timeframe = bool(TIME_RE.search(text))
    specificity = int(budget) + int(timeframe)
    label = "HOT" if direct_hits and specificity else "WARM"
    intent_score = min(98, 68 + direct_hits * 12 + warm_hits * 7 + specificity * 6)
    credibility = min(95, 62 + int(has_date) * 8 + int(budget) * 8 + int(timeframe) * 6 - supply_hits * 8)
    out = dict(item)
    out.update({
        "market": "north_cyprus",
        "route_to": "Prime Kıbrıs",
        "classification": label,
        "intent_score": intent_score,
        "credibility_score": max(40, credibility),
        "market_fit_score": 100,
        "buyer_signal": "direct" if direct_hits else "consideration",
        "budget_detected": budget,
        "timeframe_detected": timeframe,
        "radar_version": VERSION,
    })
    return out


def _lead_key(item: dict[str, Any]) -> str:
    raw = "|".join([
        str(item.get("source") or ""),
        str(item.get("url") or ""),
        str(item.get("title") or ""),
        str(item.get("author") or ""),
    ])
    return hashlib.sha256(raw.casefold().encode("utf-8", "ignore")).hexdigest()


def _save_web_lead(db_client, lead: dict[str, Any], started: datetime) -> bool:
    key = _lead_key(lead)
    ref = db_client.collection(core.COLLECTION).document(key)
    if ref.get().exists:
        return False
    payload = dict(lead)
    payload["lead_id"] = key
    payload["found_at"] = started.isoformat()
    ref.set(payload)
    lead["lead_id"] = key
    lead["found_at"] = started.isoformat()
    return True


def _clip(text: str, n: int = 700) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def notify_web_lead(lead: dict[str, Any]) -> None:
    emoji = "🔥" if lead.get("classification") == "HOT" else "🟡"
    title = _clip(lead.get("title") or lead.get("text") or "", 260)
    snippet = _clip(lead.get("text") or "", 650)
    msg = (
        f"{emoji} BAY-S V5 | {lead.get('classification')} FOREIGN BUYER\n\n"
        f"Kaynak: {lead.get('source','')}\n"
        f"Pazar: North Cyprus | Prime Kıbrıs\n"
        f"Sinyal: {lead.get('buyer_signal','')}\n"
        f"Intent: {lead.get('intent_score',0)}/100 | Güven: {lead.get('credibility_score',0)}/100\n\n"
        f"{title}\n\n{snippet}\n\n"
        f"🔗 {lead.get('url','')}"
    )
    core.telegram(msg[:3900])


def notify_telegram_lead(lead: dict[str, Any], prefix: str = "NEW") -> bool:
    if str(lead.get("market") or "") != "north_cyprus":
        return False
    if str(lead.get("classification") or "") not in {"HOT", "WARM"}:
        return False
    message = _clip(lead.get("message") or "", 900)
    emoji = "🔥" if lead.get("classification") == "HOT" else "🟡"
    msg = (
        f"{emoji} BAY-S V5 | {lead.get('classification')} TELEGRAM BUYER [{prefix}]\n\n"
        f"Grup: {lead.get('group','')}\n"
        f"Kişi: {lead.get('author','-') or '-'}\n"
        f"Skor: {lead.get('telegram_score',0)} | Öncelik: {lead.get('group_priority','')}\n\n"
        f"{message}\n\n"
        f"🔗 {lead.get('url','') or 'Doğrudan link yok'}"
    )
    core.telegram(msg[:3900])
    return True


def _mark_notified(db_client, lead: dict[str, Any], when: datetime) -> None:
    lead_id = str(lead.get("lead_id") or "")
    if not lead_id:
        return
    try:
        db_client.collection(core.COLLECTION).document(lead_id).set(
            {"v5_notified_at": when.isoformat(), "radar_version": VERSION},
            merge=True,
        )
    except Exception as exc:
        print(f"V5_MARK_NOTIFIED_ERROR {type(exc).__name__}: {exc}")


def backfill_unnotified_telegram(db_client, started: datetime) -> list[dict[str, Any]]:
    cutoff = started - timedelta(days=TELEGRAM_BACKFILL_DAYS)
    recovered: list[dict[str, Any]] = []
    try:
        for snap in db_client.collection(core.COLLECTION).stream():
            if len(recovered) >= TELEGRAM_BACKFILL_LIMIT:
                break
            data = snap.to_dict() or {}
            if data.get("source") != "Telegram":
                continue
            if data.get("v5_notified_at"):
                continue
            if data.get("market") != "north_cyprus":
                continue
            if data.get("classification") not in {"HOT", "WARM"}:
                continue
            raw_found = str(data.get("found_at") or "")
            try:
                found = datetime.fromisoformat(raw_found.replace("Z", "+00:00"))
                if found.tzinfo is None:
                    found = found.replace(tzinfo=timezone.utc)
                if found < cutoff:
                    continue
            except Exception:
                continue
            group = str(data.get("group") or "")
            text = str(data.get("message") or "")
            score_data = core.tg_score(text, group)
            score, label, *_rest = score_data
            market = score_data[8]
            if label not in {"HOT", "WARM"} or market != "north_cyprus":
                continue
            data["lead_id"] = snap.id
            data["telegram_score"] = score
            data["classification"] = label
            recovered.append(data)
    except Exception as exc:
        print(f"V5_TELEGRAM_BACKFILL_ERROR {type(exc).__name__}: {exc}")
    return recovered


def main() -> None:
    started = datetime.now(timezone.utc)
    print(
        f"BAY-S RADAR {VERSION} STARTED | exa={len(EXA_QUERIES)} | "
        f"reddit={len(REDDIT_QUERIES)} | telegram_window={core.TELEGRAM_HOURS}h"
    )
    db_client = core.db()
    seen: set[str] = set()
    web_leads: list[dict[str, Any]] = []
    counts = {"Exa": 0, "Reddit": 0, "Telegram": 0, "Recovered": 0}
    errors = 0

    for idx, (query, domains) in enumerate(EXA_QUERIES, start=1):
        print(f"[V5 EXA {idx}/{len(EXA_QUERIES)}] {query}")
        try:
            for item in core.exa_search(query, domains):
                counts["Exa"] += 1
                key = _lead_key(item)
                if key in seen:
                    continue
                seen.add(key)
                lead = classify_web(item)
                if lead is None:
                    continue
                if _save_web_lead(db_client, lead, started):
                    web_leads.append(lead)
        except Exception as exc:
            errors += 1
            print(f"V5_EXA_ERROR {type(exc).__name__}: {exc}")

    for idx, query in enumerate(REDDIT_QUERIES, start=1):
        print(f"[V5 REDDIT {idx}/{len(REDDIT_QUERIES)}] {query}")
        try:
            for item in core.reddit_search(query):
                counts["Reddit"] += 1
                key = _lead_key(item)
                if key in seen:
                    continue
                seen.add(key)
                lead = classify_web(item)
                if lead is None:
                    continue
                if _save_web_lead(db_client, lead, started):
                    web_leads.append(lead)
        except Exception as exc:
            errors += 1
            print(f"V5_REDDIT_ERROR {type(exc).__name__}: {exc}")

    try:
        tg_result = asyncio.run(core.telegram_buyer_scan(db_client, started))
    except Exception as exc:
        errors += 1
        print(f"V5_TELEGRAM_ERROR {type(exc).__name__}: {exc}")
        tg_result = {"status": "error", "new_leads": [], "groups": 0, "messages": 0, "hot_warm": 0}

    current_tg = [
        x for x in (tg_result.get("new_leads") or [])
        if x.get("market") == "north_cyprus" and x.get("classification") in {"HOT", "WARM"}
    ]
    counts["Telegram"] = len(current_tg)

    notified_ids: set[str] = set()
    for lead in current_tg:
        if notify_telegram_lead(lead, "NEW"):
            _mark_notified(db_client, lead, started)
            notified_ids.add(str(lead.get("lead_id") or ""))

    recovered = backfill_unnotified_telegram(db_client, started)
    for lead in recovered:
        lead_id = str(lead.get("lead_id") or "")
        if lead_id in notified_ids:
            continue
        if notify_telegram_lead(lead, "RECOVERED"):
            _mark_notified(db_client, lead, started)
            notified_ids.add(lead_id)
            counts["Recovered"] += 1

    web_leads.sort(
        key=lambda x: (
            x.get("classification") == "HOT",
            int(x.get("intent_score") or 0),
            int(x.get("credibility_score") or 0),
        ),
        reverse=True,
    )
    for lead in web_leads[:10]:
        notify_web_lead(lead)
        _mark_notified(db_client, lead, started)

    completed = datetime.now(timezone.utc)
    scan = {
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "status": "completed",
        "radar_version": VERSION,
        "focus": "north_cyprus_foreign_buyers",
        "exa_queries": len(EXA_QUERIES),
        "reddit_queries": len(REDDIT_QUERIES),
        "source_counts": counts,
        "web_new_hot_warm": len(web_leads),
        "telegram_status": tg_result.get("status", "unknown"),
        "telegram_groups": tg_result.get("groups", 0),
        "telegram_messages_scanned": tg_result.get("messages", 0),
        "telegram_new_north_cyprus": len(current_tg),
        "telegram_recovered": counts["Recovered"],
        "errors": errors,
    }
    scan_id = started.strftime("%Y%m%dT%H%M%SZ")
    db_client.collection(core.SCAN_LOG_COLLECTION).document(scan_id).set(scan)

    total_alerts = len(web_leads[:10]) + len(current_tg) + counts["Recovered"]
    if total_alerts == 0:
        core.telegram(
            "ℹ️ BAY-S RADAR V5\n\n"
            "North Cyprus foreign-buyer taraması tamamlandı.\n"
            "Yeni HOT/WARM lead yok.\n\n"
            f"Exa ham sonuç: {counts['Exa']}\n"
            f"Reddit ham sonuç: {counts['Reddit']}\n"
            f"Telegram grup: {tg_result.get('groups', 0)}\n"
            f"Telegram mesaj: {tg_result.get('messages', 0)}\n"
            f"Hata: {errors}"
        )

    print(json.dumps({
        "scan": scan,
        "web_leads": web_leads,
        "telegram_new": current_tg,
        "recovered": recovered,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
