from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

import main

VERSION = "1.1-reddit-comment-intent"
LOOKBACK_DAYS = int(os.getenv("NC_REDDIT_COMMENT_LOOKBACK_DAYS", "14"))
QUERY_LIMIT = int(os.getenv("NC_REDDIT_QUERY_LIMIT", "10"))
WATCHLIST_COLLECTION = "bay_s_nc_reddit_watchlist"
NOTIFIED_COLLECTION = "bay_s_nc_reddit_notified"
SCAN_COLLECTION = "bay_s_nc_reddit_scans"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-NC-Reddit-Buyer-Miner/1.1)",
    "Accept-Language": "en-US,en;q=0.9",
})

# Proven North-Cyprus buyer discussions. Old content is never alerted merely for
# being on this list; these are evergreen magnet threads watched for NEW comments.
SEED_THREADS = {
    "1cegsun": "Buying property in North Cyprus",
    "1k04v1u": "Buying property in TRNC",
    "1r7vuj9": "Father-in-law wants to buy an apartment in northern Cyprus",
}

DISCOVERY_QUERIES = [
    'site:reddit.com/r/NorthCyprus "buying property"',
    'site:reddit.com/r/NorthCyprus ("thinking of buying" OR "considering buying") property',
    'site:reddit.com/r/NorthCyprus ("price range" OR "best location") property',
    'site:reddit.com/r/NorthCyprus ("title deed" OR "pre-1974") property',
    'site:reddit.com/r/NorthCyprus ("safe to buy" OR "foreigner buy") property',
    'site:reddit.com/r/cyprus "northern cyprus" "buy apartment"',
    'site:reddit.com/r/cyprus "north cyprus" "buy property"',
    'site:reddit.com/r/expats "north cyprus" property buy',
    'site:reddit.com "north cyprus" ("looking to buy" OR "want to buy") property',
    'site:reddit.com "north cyprus" ("resale" OR "off-plan" OR "payment plan") property',
    'site:reddit.com "north cyprus" ("rental yield" OR "investment") property buyer',
    'site:reddit.com "northern cyprus" ("title deeds" OR "real estate agent") buyer',
]

THREAD_ID_RE = re.compile(
    r"(?:reddit\.com/(?:r/[^/]+/)?comments/|redd\.it/)([a-z0-9]+)",
    re.I,
)

NORTH_RE = re.compile(
    r"\b(?:north(?:ern)?\s+cyprus|trnc|kktc|nordzypern|nord\s*zypern|"
    r"северн\w*\s+кипр\w*|cypr\s+p[oó]łnocny|iskele|İskele|long\s+beach|"
    r"girne|kyrenia|esentepe|gaziveren|famagusta|gazima[ğg]usa|bafra)\b",
    re.I,
)

PROPERTY_RE = re.compile(
    r"\b(?:property|real\s+estate|apartment|apartement|flat|house|home|villa|studio|land|"
    r"title\s+deed|deed|resale|off[- ]?plan|mortgage|payment\s+plan|"
    r"immobilie|wohnung|haus|grundbuch|"
    r"недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|титул\w*|тапу|"
    r"daire|ev|villa|arsa|gayrimenkul|ko[çc]an|tapu|"
    r"nieruchomo\w*|mieszkanie|apartament|dom|willa)\b",
    re.I,
)

DIRECT_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,70}\b(?:want|planning|thinking|considering|interested|ready|hoping)\b"
    r".{0,70}\b(?:buy|buying|purchase|purchasing|invest|investing)\b|"
    r"\b(?:looking\s+to\s+buy|want\s+to\s+buy|planning\s+to\s+buy|considering\s+buying|"
    r"thinking\s+(?:of|about)\s+buying|interested\s+in\s+buying|ready\s+to\s+buy)\b|"
    r"\bmy\s+(?:father|mother|father-in-law|mother-in-law|parents?|husband|wife|partner)\b"
    r".{0,70}\b(?:wants?|plans?|is\s+looking|are\s+looking)\b.{0,60}\b(?:buy|buying|purchase)\b|"
    r"\b(?:я|мы)\b.{0,50}\b(?:хочу|хотим|ищу|ищем|планирую|планируем|думаю|рассматриваю)\b"
    r".{0,90}\b(?:купить|покупк\w*|приобрест\w*)\b|"
    r"\b(?:хочу\s+купить|ищу\s+.*(?:для\s+покупки|на\s+покупку))\b|"
    r"\b(?:ich|wir)\b.{0,55}\b(?:möchte|moechte|wollen|will|suche|suchen|plane|planen|überlege|ueberlege)\b"
    r".{0,90}\b(?:kaufen|erwerben|zum\s+kauf)\b|"
    r"\b(?:ben|biz)\b.{0,55}\b(?:almak\s+istiyorum|almayı\s+düşünüyorum|almayi\s+dusunuyorum|satın\s+almak)\b|"
    r"\b(?:chcę|chce|szukam|planuję|planuje)\b.{0,80}\b(?:kupić|kupic|zakupić|zakupic)\b"
    r")",
    re.I | re.S,
)

# Research-stage intent is valuable when the user is clearly evaluating a purchase.
RESEARCH_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,60}\b(?:looking\s+into|researching|trying\s+to\s+understand|curious\s+about)\b|"
    r"\b(?:is\s+it\s+safe\s+to\s+buy|how\s+safe\s+is\s+it\s+to\s+buy|can\s+foreigners?\s+buy)\b|"
    r"\b(?:what|which)\b.{0,45}\b(?:title\s+deed|deed|area|location|project|developer|agent|lawyer)\b|"
    r"\b(?:price\s+range|best\s+(?:area|location)|good\s+(?:agent|lawyer)|recommended\s+(?:area|agent|lawyer))\b|"
    r"\b(?:resale|off[- ]?plan|title\s+deed|pre[- ]?1974|exchange\s+title|payment\s+plan|mortgage|rental\s+yield)\b"
    r".{0,100}\b(?:buy|buying|purchase|investment|investing|property|apartment|house|villa)\b|"
    r"\b(?:buy|buying|purchase|investment|investing)\b.{0,100}"
    r"\b(?:title\s+deed|pre[- ]?1974|exchange\s+title|resale|off[- ]?plan|payment\s+plan|rental\s+yield)\b"
    r")",
    re.I | re.S,
)

CONCRETE_RE = re.compile(
    r"(?:"
    r"[£€$]\s*\d[\d\s,.-]*(?:k|m)?|\b\d{2,4}\s*k\b|\bbudget\b|\bmy\s+budget\b|"
    r"\b1\s*\+\s*[01]\b|\b2\s*\+\s*[01]\b|\b3\s*\+\s*[01]\b|"
    r"\bstudio\b|\bapartment\b|\bvilla\b|\bhouse\b|"
    r"\bthis\s+(?:month|year)\b|\bnext\s+(?:month|year)\b|\bsoon\b|"
    r"\bviewing\b|\bmake\s+an\s+offer\b|\bpayment\s+plan\b|\bmortgage\b|\bcash\s+buyer\b"
    r")",
    re.I,
)

SELLER_RE = re.compile(
    r"(?:"
    r"\bi\s+(?:work|am)\s+(?:in|as).{0,30}\breal\s+estate\b|\breal\s+estate\s+agent\b|"
    r"\bestate\s+agent\b|\brealtor\b|\bbroker\b|\bdeveloper\b|\bmy\s+client\b|"
    r"\bcontact\s+me\b|\bdm\s+me\b|\bwhatsapp\b|\bfor\s+sale\b|\bi\s+am\s+selling\b|"
    r"\bwe\s+have\s+(?:units?|properties|apartments?|villas?)\b|"
    r"\bагент\w*\b|\bриэлтор\w*\b|\bзастройщик\w*\b|\bпишите\s+мне\b|\bпродаю\b|"
    r"\bemlak\s+danışman\w*\b|\bsatılık\s+ilan\b"
    r")",
    re.I | re.S,
)

RENT_RE = re.compile(
    r"(?:\blooking\s+to\s+rent\b|\bfor\s+rent\b|\brenting\b|\brental\s+only\b|"
    r"\bper\s+month\b|\bmonthly\s+rent\b|\bаренд\w*\b|\bснять\b|\bсниму\b|"
    r"\bkiralık\b|\bkiralam\w*\b|\bzu\s+mieten\b|\bmietwohnung\b)",
    re.I,
)

PAST_OWNER_RE = re.compile(
    r"(?:\bi\s+(?:already\s+)?bought\b|\bwe\s+(?:already\s+)?bought\b|\bi\s+purchased\b|"
    r"\bwe\s+purchased\b|\bi\s+own\s+(?:a|an)\b|\bmy\s+property\s+in\b|"
    r"\bкупил\b|\bкупили\b|\bsatın\s+aldım\b|\bsatin\s+aldim\b|\bgekauft\b)",
    re.I,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean(text: str) -> str:
    return " ".join(str(text or "").split())


def extract_thread_id(url: str) -> str:
    m = THREAD_ID_RE.search(str(url or ""))
    return m.group(1).lower() if m else ""


def classify_comment(body: str, thread_title: str, thread_text: str = ""):
    body = clean(body)
    context = clean(f"{thread_title} {thread_text}")
    if not body or not NORTH_RE.search(context):
        return None, "no_north_context"
    if SELLER_RE.search(body):
        return None, "seller_or_agent"
    if RENT_RE.search(body) and not DIRECT_RE.search(body):
        return None, "rental"
    direct = bool(DIRECT_RE.search(body))
    research = bool(RESEARCH_RE.search(body))
    if PAST_OWNER_RE.search(body) and not direct:
        return None, "past_owner"
    if not (direct or research):
        return None, "no_buyer_intent"
    if not (PROPERTY_RE.search(body) or PROPERTY_RE.search(context)):
        return None, "no_property_context"

    concrete = bool(CONCRETE_RE.search(body))
    stage = "DIRECT" if direct else "RESEARCH"
    classification = "HOT" if direct and concrete else "WARM"
    intent = 86 if direct else 76
    if concrete:
        intent += 7
    if re.search(r"\b(?:title\s+deed|pre[- ]?1974|payment\s+plan|mortgage|budget|price\s+range)\b", body, re.I):
        intent += 4

    return {
        "classification": classification,
        "buyer_stage": stage,
        "intent_score": min(98, intent),
        "credibility_score": 92,
        "market_fit_score": 100,
        "buyer_signal": "reddit_verified_direct" if direct else "reddit_verified_research",
    }, "accepted"


def _serper_urls(query: str) -> list[str]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = SESSION.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": 10, "hl": "en", "gl": "gb"},
            timeout=25,
        )
        if r.status_code != 200:
            print("NC_REDDIT_SERPER_ERROR", r.status_code, r.text[:180])
            return []
        urls = [str(x.get("link") or "") for x in (r.json().get("organic") or [])]
        print(f"NC_REDDIT_SERPER_OK results={len(urls)} query={query!r}")
        return urls
    except Exception as exc:
        print("NC_REDDIT_SERPER_EXCEPTION", type(exc).__name__, exc)
        return []


def _exa_urls(query: str) -> list[str]:
    if not os.getenv("EXA_API_KEY", "").strip():
        return []
    try:
        rows = main.exa_search(query, ["reddit.com"])
        urls = [str(x.get("url") or "") for x in rows]
        print(f"NC_REDDIT_EXA_OK results={len(urls)} query={query!r}")
        return urls
    except Exception as exc:
        print("NC_REDDIT_EXA_EXCEPTION", type(exc).__name__, exc)
        return []


def discover_threads(db) -> dict[str, str]:
    threads = dict(SEED_THREADS)
    queries = DISCOVERY_QUERIES[:max(1, min(QUERY_LIMIT, len(DISCOVERY_QUERIES)))]
    for query in queries:
        for url in _serper_urls(query) + _exa_urls(query):
            tid = extract_thread_id(url)
            if tid:
                threads.setdefault(tid, "")
        time.sleep(0.15)

    if db:
        for tid, title in threads.items():
            try:
                db.collection(WATCHLIST_COLLECTION).document(tid).set({
                    "thread_id": tid,
                    "title_hint": title,
                    "last_discovered_at": now_utc().isoformat(),
                    "status": "active",
                }, merge=True)
            except Exception as exc:
                print("NC_REDDIT_WATCHLIST_WRITE_ERROR", tid, exc)

        try:
            for doc in db.collection(WATCHLIST_COLLECTION).limit(120).stream():
                data = doc.to_dict() or {}
                if data.get("status") == "active" and data.get("thread_id"):
                    threads.setdefault(str(data["thread_id"]), str(data.get("title_hint") or ""))
        except Exception as exc:
            print("NC_REDDIT_WATCHLIST_READ_ERROR", exc)

    print(f"NC_REDDIT_THREADS total={len(threads)}")
    return threads


def _fetch_thread(thread_id: str):
    urls = [
        f"https://www.reddit.com/comments/{thread_id}.json",
        f"https://old.reddit.com/comments/{thread_id}.json",
    ]
    params = {"sort": "new", "limit": 500, "raw_json": 1}
    for url in urls:
        try:
            r = SESSION.get(url, params=params, timeout=25)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) >= 2:
                    return data
            print("NC_REDDIT_FETCH_STATUS", thread_id, r.status_code)
        except Exception as exc:
            print("NC_REDDIT_FETCH_ERROR", thread_id, type(exc).__name__, exc)
        time.sleep(0.4)
    return None


def _walk_comments(children):
    for node in children or []:
        if not isinstance(node, dict) or node.get("kind") != "t1":
            continue
        data = node.get("data") or {}
        yield data
        replies = data.get("replies")
        if isinstance(replies, dict):
            more = (((replies.get("data") or {}).get("children")) or [])
            yield from _walk_comments(more)


def _thread_meta(payload):
    try:
        post = payload[0]["data"]["children"][0]["data"]
        title = clean(post.get("title") or "")
        selftext = clean(post.get("selftext") or "")
        permalink = str(post.get("permalink") or "")
        return title, selftext, permalink
    except Exception:
        return "", "", ""


def _comment_permalink(data, thread_id: str) -> str:
    p = str(data.get("permalink") or "")
    if p.startswith("/"):
        return "https://www.reddit.com" + p
    cid = str(data.get("id") or "")
    return f"https://www.reddit.com/comments/{thread_id}/_/{cid}/" if cid else ""


def run():
    started = now_utc()
    cutoff = started - timedelta(days=LOOKBACK_DAYS)
    db = main.db()
    threads = discover_threads(db)

    stats = {
        "threads": len(threads), "fetched": 0, "comments_recent": 0,
        "accepted": 0, "new": 0, "fetch_errors": 0,
    }
    reasons: dict[str, int] = {}
    new_leads = []

    for thread_id in threads:
        payload = _fetch_thread(thread_id)
        if not payload:
            stats["fetch_errors"] += 1
            continue
        stats["fetched"] += 1
        title, selftext, _ = _thread_meta(payload)
        if not title or not NORTH_RE.search(f"{title} {selftext}"):
            continue

        comments = (((payload[1].get("data") or {}).get("children")) or [])
        for data in _walk_comments(comments):
            cid = str(data.get("id") or "").strip()
            author = str(data.get("author") or "").strip()
            body = clean(data.get("body") or "")
            created = data.get("created_utc")
            if not cid or not body or author in {"[deleted]", "AutoModerator"}:
                continue
            try:
                dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
            except Exception:
                continue
            if dt < cutoff:
                continue
            stats["comments_recent"] += 1

            signal, reason = classify_comment(body, title, selftext)
            reasons[reason] = reasons.get(reason, 0) + 1
            if not signal:
                continue
            stats["accepted"] += 1

            dedupe = hashlib.sha256(f"reddit-comment|{cid}".encode()).hexdigest()
            ref = db.collection(NOTIFIED_COLLECTION).document(dedupe)
            try:
                if ref.get().exists:
                    continue
            except Exception as exc:
                print("NC_REDDIT_DEDUPE_READ_ERROR", cid, exc)

            lead = {
                **signal,
                "source": "Reddit Comment",
                "market": "north_cyprus",
                "route_to": "Prime Kıbrıs",
                "thread_id": thread_id,
                "comment_id": cid,
                "thread_title": title,
                "author": author,
                "text": body,
                "published": dt.isoformat(),
                "url": _comment_permalink(data, thread_id),
                "radar_version": VERSION,
                "found_at": started.isoformat(),
            }
            new_leads.append(lead)
            stats["new"] += 1
            try:
                ref.set({
                    "comment_id": cid,
                    "thread_id": thread_id,
                    "author": author,
                    "url": lead["url"],
                    "classification": lead["classification"],
                    "notified_at": started.isoformat(),
                }, merge=True)
            except Exception as exc:
                print("NC_REDDIT_DEDUPE_WRITE_ERROR", cid, exc)

        time.sleep(0.35)

    try:
        scan_id = started.strftime("%Y%m%d%H%M%S")
        db.collection(SCAN_COLLECTION).document(scan_id).set({
            **stats, "reject_reasons": reasons, "lookback_days": LOOKBACK_DAYS,
            "version": VERSION, "scanned_at": started.isoformat(),
        }, merge=True)
    except Exception as exc:
        print("NC_REDDIT_SCAN_WRITE_ERROR", exc)

    new_leads.sort(key=lambda x: (x["classification"] == "HOT", x["intent_score"]), reverse=True)
    print("NC_REDDIT_BUYER_MINER_COMPLETE", json.dumps({**stats, "reject_reasons": reasons}, ensure_ascii=False))

    if new_leads:
        lines = [f"🧲 BAY-S NC REDDIT BUYER MINER | {len(new_leads)} YENİ GERÇEK KİŞİ"]
        for lead in new_leads[:10]:
            lines.append(
                f"\n{lead['classification']} | {lead['buyer_stage']} | @{lead['author']} | "
                f"I{lead['intent_score']} C{lead['credibility_score']}"
                f"\n🧵 {clean(lead['thread_title'])[:120]}"
                f"\n💬 {clean(lead['text'])[:420]}"
                f"\n{lead['url']}"
            )
        main.telegram("\n".join(lines))

    return new_leads


if __name__ == "__main__":
    run()
