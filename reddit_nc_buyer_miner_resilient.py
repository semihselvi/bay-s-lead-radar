from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests

import main
import reddit_nc_buyer_miner as base

VERSION = "1.2-reddit-resilient-rental-guard"
INDEX_LOOKBACK_DAYS = int(os.getenv("NC_REDDIT_INDEX_LOOKBACK_DAYS", "30"))
INDEX_QUERY_LIMIT = int(os.getenv("NC_REDDIT_INDEX_QUERY_LIMIT", "12"))
INDEX_COLLECTION = "bay_s_nc_reddit_index_notified"
INDEX_SCAN_COLLECTION = "bay_s_nc_reddit_index_scans"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-NC-Reddit-Index-Miner/1.2)",
    "Accept-Language": "en-US,en;q=0.9",
})

INDEX_QUERIES = [
    'site:reddit.com/r/NorthCyprus "buying property"',
    'site:reddit.com/r/NorthCyprus ("want to buy" OR "looking to buy") property',
    'site:reddit.com/r/NorthCyprus ("thinking of buying" OR "considering buying") property',
    'site:reddit.com/r/NorthCyprus ("safe to buy" OR "can foreigners buy") property',
    'site:reddit.com/r/NorthCyprus ("title deed" OR "pre-1974" OR "exchange title") property',
    'site:reddit.com/r/NorthCyprus ("resale" OR "off-plan" OR "payment plan") property buying',
    'site:reddit.com/r/NorthCyprus ("which area" OR "best area" OR "best location") buy property',
    'site:reddit.com/r/cyprus ("north cyprus" OR "northern cyprus") ("buy property" OR "buy apartment")',
    'site:reddit.com/r/expats "north cyprus" ("buy property" OR "buy apartment")',
    'site:reddit.com "North Cyprus" ("my budget" OR "cash buyer") property',
    'site:reddit.com "Северный Кипр" ("хочу купить" OR "ищу квартиру для покупки")',
    'site:reddit.com Nordzypern ("Immobilie kaufen" OR "Wohnung kaufen")',
]

DIRECT_TITLE_RE = re.compile(
    r"(?:"
    r"\bbuying\s+(?:a\s+)?(?:property|apartment|house|villa|home)\b|"
    r"\b(?:want|looking|planning|ready)\s+to\s+buy\b|"
    r"\bthinking\s+(?:of|about)\s+buying\b|\bconsidering\s+buying\b|"
    r"\b(?:father|mother|father-in-law|mother-in-law|parents?|partner|wife|husband)\b.{0,60}\bwants?\s+to\s+buy\b|"
    r"\bхочу\s+купить\b|\bищу\b.{0,80}\b(?:для\s+покупки|на\s+покупку)\b|"
    r"\bimmobilie\s+kaufen\b|\bwohnung\s+kaufen\b"
    r")",
    re.I | re.S,
)

RESEARCH_TITLE_RE = re.compile(
    r"(?:"
    r"\bcan\s+foreigners?\s+buy\b|\bis\s+it\s+safe\s+to\s+buy\b|"
    r"\bshould\s+i\s+buy\b|\bwhere\s+should\s+i\s+buy\b|"
    r"\bwhich\s+(?:area|location|region).{0,70}\bbuy\b|"
    r"\btitle\s+deed\b|\bpre[- ]?1974\b|\bexchange\s+title\b|"
    r"\bresale\b|\boff[- ]?plan\b|\bpayment\s+plan\b|\brental\s+yield\b|"
    r"\binvest(?:ing|ment)?\s+in\s+(?:north|northern)\s+cyprus\b|"
    r"\bstоит\s+ли\s+покупать\b|\bкак\s+купить\b|\bможно\s+ли\s+иностранц\w*.{0,50}\bкупить\b|"
    r"\bwelche\s+region.{0,60}\bkaufen\b|\bwo\s+sollte\s+ich\s+kaufen\b"
    r")",
    re.I | re.S,
)

FIRST_PERSON_BUY_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,60}\b(?:want|looking|planning|thinking|considering|interested|researching|ready)\b"
    r".{0,90}\b(?:buy|buying|purchase|purchasing|invest|investing)\b|"
    r"\bmy\s+budget\b.{0,120}\b(?:property|apartment|house|villa)\b|"
    r"\b(?:я|мы)\b.{0,50}\b(?:хочу|хотим|ищу|ищем|планирую|думаю|рассматриваю)\b.{0,90}\b(?:купить|покупк\w*)\b|"
    r"\b(?:ich|wir)\b.{0,50}\b(?:möchte|moechte|suche|suchen|plane|überlege|ueberlege)\b.{0,90}\b(?:kaufen|erwerben)\b"
    r")",
    re.I | re.S,
)

SELLER_RE = re.compile(
    r"(?:\bfor\s+sale\b|\breal\s+estate\s+agent\b|\bestate\s+agent\b|\brealtor\b|\bbroker\b|"
    r"\bdeveloper\b|\bcontact\s+me\b|\bdm\s+me\b|\bwhatsapp\b|\bprice\s+from\b|"
    r"\bavailable\s+units?\b|\bпрода[её]тся\b|\bпродам\b|\bагент\w*\b|\bриэлтор\w*\b|"
    r"\bзастройщик\w*\b|\bsatılık\b|\bemlak\s+danışman\w*\b)",
    re.I,
)

RENT_RE = re.compile(
    r"(?:\bfor\s+rent\b|\blooking\s+to\s+rent\b|\brental\s+only\b|\bper\s+month\b|"
    r"\bmonthly\s+rent\b|\bаренд\w*\b|\bснять\b|\bсниму\b|\bkiralık\b|\bzu\s+mieten\b)",
    re.I,
)

# Explicit rental-only language must win even when an ambiguous Reddit title says
# "buy or rent". This protects the fallback from turning a tenant into a buyer.
RENT_ONLY_RE = re.compile(
    r"(?:"
    r"\b(?:actually\s+)?looking\s+to\s+rent\s+only\b|"
    r"\bonly\s+looking\s+to\s+rent\b|\brent(?:al)?\s+only\b|"
    r"\bnot\s+(?:looking\s+to\s+)?buy(?:ing)?\b.{0,50}\brent\b|"
    r"\b(?:сниму|снять|аренд\w*)\b.{0,80}\bтолько\b|"
    r"\bтолько\b.{0,80}\b(?:сниму|снять|аренд\w*)\b|"
    r"\bsadece\s+kiral\w*\b|\bnur\s+mieten\b"
    r")",
    re.I | re.S,
)

PAST_OWNER_RE = re.compile(
    r"(?:\bi\s+(?:already\s+)?bought\b|\bwe\s+(?:already\s+)?bought\b|\bi\s+purchased\b|"
    r"\bwe\s+purchased\b|\bi\s+own\s+(?:a|an)\b|\bкупил\b|\bкупили\b|\bsatın\s+aldım\b|\bgekauft\b)",
    re.I,
)

CONCRETE_RE = re.compile(
    r"(?:[£€$]\s*\d[\d\s,.-]*(?:k|m)?|\b\d{2,4}\s*k\b|\bbudget\b|\b1\s*\+\s*[01]\b|"
    r"\b2\s*\+\s*[01]\b|\b3\s*\+\s*[01]\b|\bstudio\b|\bapartment\b|\bvilla\b|\bhouse\b|"
    r"\btitle\s+deed\b|\bpayment\s+plan\b|\bmortgage\b|\bcash\s+buyer\b)",
    re.I,
)


def clean(text: str) -> str:
    return " ".join(str(text or "").split())


def _reddit_thread_url(url: str) -> bool:
    try:
        p = urlparse(str(url or ""))
    except Exception:
        return False
    host = p.netloc.casefold().removeprefix("www.")
    return host in {"reddit.com", "old.reddit.com"} and "/comments/" in p.path.casefold()


def _north_context(url: str, text: str, query: str) -> bool:
    low_url = str(url or "").casefold()
    if "/r/northcyprus/" in low_url:
        return True
    return bool(base.NORTH_RE.search(text) or base.NORTH_RE.search(query))


def classify_index_result(row: dict, query: str):
    url = str(row.get("link") or row.get("url") or "")
    title = clean(row.get("title") or "")
    snippet = clean(row.get("snippet") or row.get("text") or "")
    combined = clean(f"{title} {snippet}")

    if not _reddit_thread_url(url):
        return None, "not_reddit_thread"
    if not _north_context(url, combined, query):
        return None, "no_north_context"
    if SELLER_RE.search(combined):
        return None, "seller_or_listing"

    title_direct = bool(DIRECT_TITLE_RE.search(title))
    title_research = bool(RESEARCH_TITLE_RE.search(title))
    snippet_direct = bool(FIRST_PERSON_BUY_RE.search(snippet))

    # A clear rental-only statement is decisive, including ambiguous titles such
    # as "Looking to buy or rent". Background rent mentions do not kill an
    # explicit first-person plan to buy.
    if RENT_ONLY_RE.search(snippet):
        return None, "rental"
    if RENT_RE.search(title) and not snippet_direct:
        return None, "rental"
    if RENT_RE.search(snippet) and not (title_direct or snippet_direct):
        return None, "rental"

    if PAST_OWNER_RE.search(combined) and not (title_direct or snippet_direct):
        return None, "past_owner"

    # Precision rule: Serper snippets can contain related-content text. Never
    # accept a snippet-only hit unless the title itself is a buyer/research topic.
    if not (title_direct or title_research):
        return None, "title_not_buyer_topic"

    stage = "DIRECT" if title_direct else "RESEARCH"
    if title_research and snippet_direct:
        stage = "DIRECT"

    concrete = bool(CONCRETE_RE.search(combined))
    classification = "HOT" if stage == "DIRECT" and concrete else "WARM"
    intent = 88 if stage == "DIRECT" else 77
    if concrete:
        intent += 6

    return {
        "classification": classification,
        "buyer_stage": stage,
        "intent_score": min(97, intent),
        "credibility_score": 84,
        "market_fit_score": 100,
        "buyer_signal": "reddit_serper_index_direct" if stage == "DIRECT" else "reddit_serper_index_research",
    }, "accepted"


def _serper(query: str) -> list[dict]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        print("NC_REDDIT_INDEX_DISABLED missing SERPER_API_KEY")
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INDEX_LOOKBACK_DAYS)).date().isoformat()
    q = f"{query} after:{cutoff}"
    try:
        r = SESSION.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": q, "num": 10, "hl": "en", "gl": "gb"},
            timeout=25,
        )
        if r.status_code != 200:
            print("NC_REDDIT_INDEX_SERPER_ERROR", r.status_code, r.text[:180])
            return []
        rows = list(r.json().get("organic") or [])
        print(f"NC_REDDIT_INDEX_SERPER_OK results={len(rows)} query={query!r}")
        return rows
    except Exception as exc:
        print("NC_REDDIT_INDEX_SERPER_EXCEPTION", type(exc).__name__, exc)
        return []


def _probe_direct_reddit() -> bool:
    # One cheap probe decides whether the richer comment miner is usable from
    # this runner. GitHub-hosted runners currently receive 403 from Reddit.
    try:
        payload = base._fetch_thread("1k04v1u")
        return bool(payload)
    except Exception as exc:
        print("NC_REDDIT_DIRECT_PROBE_ERROR", type(exc).__name__, exc)
        return False


def _run_index_fallback():
    started = datetime.now(timezone.utc)
    db = main.db()
    queries = INDEX_QUERIES[:max(1, min(INDEX_QUERY_LIMIT, len(INDEX_QUERIES)))]
    stats = {"queries": len(queries), "raw": 0, "unique": 0, "accepted": 0, "new": 0}
    reasons: dict[str, int] = {}
    candidates: dict[str, dict] = {}

    for query in queries:
        for row in _serper(query):
            stats["raw"] += 1
            url = str(row.get("link") or "")
            if not url:
                continue
            key = url.split("?")[0].rstrip("/")
            candidates.setdefault(key, {**row, "_query": query})
        time.sleep(0.1)

    stats["unique"] = len(candidates)
    leads = []
    for url_key, row in candidates.items():
        signal, reason = classify_index_result(row, str(row.get("_query") or ""))
        reasons[reason] = reasons.get(reason, 0) + 1
        if not signal:
            continue
        stats["accepted"] += 1

        title = clean(row.get("title") or "")
        snippet = clean(row.get("snippet") or "")
        # Dedupe by canonical thread + title. This prevents old evergreen threads
        # from repeatedly firing while still allowing newly discovered buyer posts.
        dedupe = hashlib.sha256(f"reddit-index|{url_key}|{title.casefold()}".encode()).hexdigest()
        ref = db.collection(INDEX_COLLECTION).document(dedupe)
        try:
            if ref.get().exists:
                continue
        except Exception as exc:
            print("NC_REDDIT_INDEX_DEDUPE_READ_ERROR", type(exc).__name__, exc)

        lead = {
            **signal,
            "source": "Reddit via Serper Index",
            "market": "north_cyprus",
            "route_to": "Prime Kıbrıs",
            "title": title,
            "text": snippet,
            "url": str(row.get("link") or ""),
            "published_hint": str(row.get("date") or ""),
            "query": str(row.get("_query") or ""),
            "radar_version": VERSION,
            "found_at": started.isoformat(),
        }
        leads.append(lead)
        stats["new"] += 1
        try:
            ref.set({
                "url": lead["url"],
                "title": title,
                "classification": lead["classification"],
                "notified_at": started.isoformat(),
            }, merge=True)
        except Exception as exc:
            print("NC_REDDIT_INDEX_DEDUPE_WRITE_ERROR", type(exc).__name__, exc)

    try:
        scan_id = started.strftime("%Y%m%d%H%M%S")
        db.collection(INDEX_SCAN_COLLECTION).document(scan_id).set({
            **stats,
            "reject_reasons": reasons,
            "version": VERSION,
            "lookback_days": INDEX_LOOKBACK_DAYS,
            "scanned_at": started.isoformat(),
        }, merge=True)
    except Exception as exc:
        print("NC_REDDIT_INDEX_SCAN_WRITE_ERROR", type(exc).__name__, exc)

    leads.sort(key=lambda x: (x["classification"] == "HOT", x["intent_score"]), reverse=True)
    print("NC_REDDIT_INDEX_MINER_COMPLETE", json.dumps({**stats, "reject_reasons": reasons}, ensure_ascii=False))

    if leads:
        lines = [f"🧭 BAY-S NC RESEARCH BUYER INDEX | {len(leads)} YENİ ADAY"]
        for lead in leads[:10]:
            lines.append(
                f"\n{lead['classification']} | {lead['buyer_stage']} | I{lead['intent_score']} C{lead['credibility_score']}"
                f"\n🧵 {lead['title'][:150]}"
                f"\n💬 {lead['text'][:420]}"
                f"\n{lead['url']}"
            )
        main.telegram("\n".join(lines))

    return leads


def run():
    if _probe_direct_reddit():
        print("NC_REDDIT_MODE direct_comment_fetch")
        return base.run()
    print("NC_REDDIT_MODE serper_index_fallback")
    return _run_index_fallback()


if __name__ == "__main__":
    run()
