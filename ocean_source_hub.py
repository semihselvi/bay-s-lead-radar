from __future__ import annotations

import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account

from buyer_intent_core import classify_candidate, clean
from ocean_learning import (
    rank_queries,
    update_query_stats,
    update_source_stats,
    record_person_event,
    load_source_scores,
    learn_discovered_source,
    best_discovered_sources,
)
import global_semantic_buyer_radar as semantic
import reddit_global_comment_rss as reddit_rss

VERSION = "1.0-ocean-source-hub"
NOTIFIED_COLLECTION = "bay_s_ocean_hub_notified"
SCAN_COLLECTION = "bay_s_ocean_hub_scans"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-Ocean-Source-Hub/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
})

DISCOVERY_QUERIES = [
    '"looking to buy property abroad"',
    '"want to buy property abroad"',
    '"second home abroad" buy',
    '"retire abroad" "buy property"',
    '"Mediterranean property" "looking to buy"',
    '"property abroad" budget forum',
    '"off plan" property abroad payment plan',
    '"holiday home abroad" "want to buy"',
    '"buy apartment abroad" forum',
    '"overseas property" "payment plan"',
    '"Immobilie im Ausland kaufen" forum',
    '"nieruchomość za granicą" kupić forum',
    '"köpa bostad utomlands" forum',
    '"comprare casa all estero" forum',
    '"comprar vivienda en el extranjero" foro',
    '"شراء عقار في الخارج" منتدى',
]

BLUESKY_QUERIES = [
    "buy property abroad",
    "buying property abroad",
    "second home abroad",
    "retire abroad property",
    "Mediterranean property buy",
    "overseas property budget",
    "off plan property payment plan",
    "holiday home abroad buy",
    "Immobilie im Ausland kaufen",
    "nieruchomość za granicą kupić",
]

FORUM_HINTS = (
    "forum", "community", "discourse", "phpbb", "xenforo", "smf",
    "expat", "bogleheads", "moneysavingexpert", "city-data",
)

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def now_utc():
    return datetime.now(timezone.utc)


def db_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    creds = service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)


def notify(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
        timeout=20,
    ).raise_for_status()


def canonical_url(value: str) -> str:
    raw = clean(value)
    if not raw:
        return ""
    try:
        p = urlparse(raw)
        return f"{p.scheme or 'https'}://{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"
    except Exception:
        return raw.split("?", 1)[0].rstrip("/")


def candidate_key(item: dict) -> str:
    basis = canonical_url(item.get("url", ""))
    author = clean(item.get("author", "")).casefold()
    text = clean(item.get("text", "")).casefold()[:700]
    return hashlib.sha256(f"{basis}|{author}|{text}".encode("utf-8")).hexdigest()


def bing_rss(query: str, limit: int = 12) -> list[dict]:
    url = "https://www.bing.com/search?format=rss&q=" + quote_plus(query)
    try:
        r = SESSION.get(url, timeout=20)
        if r.status_code != 200:
            print("OCEAN_BING_ERROR", r.status_code, query)
            return []
        root = ET.fromstring(r.content)
        rows = []
        for item in root.findall(".//item")[:limit]:
            rows.append({
                "title": clean(item.findtext("title") or ""),
                "text": clean(BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True)),
                "url": clean(item.findtext("link") or ""),
                "published": clean(item.findtext("pubDate") or ""),
                "source": "Bing RSS Discovery",
                "discovery_query": query,
            })
        print("OCEAN_BING_OK", len(rows), query)
        return rows
    except Exception as exc:
        print("OCEAN_BING_EXCEPTION", type(exc).__name__, exc)
        return []


def semantic_adapter(db=None) -> list[dict]:
    out = []
    ranked = rank_queries(db, list(semantic.EXA_QUERIES))
    for q in ranked:
        qrows = semantic.exa_search(q)
        for row in qrows:
            out.append({
                **row,
                "source": "Exa Semantic",
                "buyer_signal": "semantic_global_purchase",
                "credibility_score": 84,
            })
        update_query_stats(db, q, raw=len(qrows))
    print("OCEAN_SOURCE semantic", len(out))
    return out


def reddit_adapter() -> list[dict]:
    out = []
    for label, url in reddit_rss.FEEDS:
        for row in reddit_rss.fetch_feed(label, url):
            out.append({
                **row,
                "source": "Reddit Comment RSS",
                "buyer_signal": "reddit_global_comment_purchase",
                "credibility_score": 88,
            })
    print("OCEAN_SOURCE reddit_comments", len(out))
    return out


def bluesky_adapter(db=None) -> list[dict]:
    out = []
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    for q in rank_queries(db, list(BLUESKY_QUERIES)):
        try:
            r = SESSION.get(endpoint, params={"q": q, "limit": 50, "sort": "latest"}, timeout=25)
            if r.status_code != 200:
                print("OCEAN_BLUESKY_ERROR", r.status_code, q)
                continue
            posts = r.json().get("posts", []) or []
            for row in posts:
                record = row.get("record") or {}
                author = row.get("author") or {}
                uri = str(row.get("uri") or "")
                rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
                handle = str(author.get("handle") or "")
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else ""
                out.append({
                    "source": "Bluesky Public Search",
                    "title": "",
                    "text": clean(record.get("text") or ""),
                    "url": url,
                    "author": handle,
                    "published": record.get("createdAt") or row.get("indexedAt") or "",
                    "discovery_query": q,
                    "buyer_signal": "bluesky_purchase_intent",
                    "credibility_score": 86,
                })
            update_query_stats(db, q, raw=len(posts))
        except Exception as exc:
            print("OCEAN_BLUESKY_EXCEPTION", q, type(exc).__name__, exc)
    print("OCEAN_SOURCE bluesky", len(out))
    return out


def _source_key_from_url(url: str) -> tuple[str, str]:
    try:
        p = urlparse(url)
        host = p.netloc.casefold().removeprefix("www.")
        path = p.path.casefold()
        if "reddit.com" in host and "/r/" in path:
            parts = [x for x in p.path.split("/") if x]
            if len(parts) >= 2 and parts[0].lower() == "r":
                return f"reddit:r/{parts[1]}", "reddit"
        if host in YOUTUBE_HOSTS:
            return f"youtube:{host}", "youtube"
        return f"domain:{host}", "domain"
    except Exception:
        return "", ""


def learned_source_expansion_queries(db) -> list[str]:
    queries = []
    for row in best_discovered_sources(db, limit=12):
        key = str(row.get("source_key") or "")
        stype = str(row.get("source_type") or "")
        if stype == "reddit" and key.startswith("reddit:r/"):
            subreddit = key.split("reddit:r/", 1)[1]
            queries.extend([
                f'site:reddit.com/r/{subreddit} "buy property abroad"',
                f'site:reddit.com/r/{subreddit} "second home abroad"',
                f'site:reddit.com/r/{subreddit} "retire abroad" property',
            ])
        elif stype == "domain" and key.startswith("domain:"):
            host = key.split("domain:", 1)[1]
            queries.extend([
                f'site:{host} "buy property abroad"',
                f'site:{host} "second home abroad"',
            ])
    # preserve order, dedupe
    return list(dict.fromkeys(q for q in queries if q))


def discover_surface_urls(db=None) -> tuple[list[str], list[str]]:
    youtube: list[str] = []
    forums: list[str] = []
    seen = set()
    max_queries = int(os.getenv("OCEAN_DISCOVERY_QUERY_LIMIT", "10"))
    learned_queries = learned_source_expansion_queries(db)
    ranked = rank_queries(db, list(DISCOVERY_QUERIES) + learned_queries)
    for q in ranked[:max_queries]:
        qrows = bing_rss(q)
        update_query_stats(db, q, raw=len(qrows))
        for row in qrows:
            url = clean(row.get("url", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                host = urlparse(url).netloc.casefold()
                path = urlparse(url).path.casefold()
            except Exception:
                continue
            if host in YOUTUBE_HOSTS and ("/watch" in path or host == "youtu.be"):
                youtube.append(url)
            elif any(h in host or h in path for h in FORUM_HINTS):
                forums.append(url)
    ylimit = int(os.getenv("OCEAN_YOUTUBE_VIDEO_LIMIT", "12"))
    flimit = int(os.getenv("OCEAN_FORUM_URL_LIMIT", "10"))
    print("OCEAN_DISCOVERY_SURFACES", json.dumps({"youtube": len(youtube), "forums": len(forums)}))
    return youtube[:ylimit], forums[:flimit]


def youtube_adapter(video_urls: list[str]) -> list[dict]:
    try:
        from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_RECENT
    except Exception as exc:
        print("OCEAN_YOUTUBE_DISABLED", type(exc).__name__, exc)
        return []

    out = []
    per_video = int(os.getenv("OCEAN_YOUTUBE_COMMENTS_PER_VIDEO", "120"))
    downloader = YoutubeCommentDownloader()
    for url in video_urls:
        try:
            count = 0
            for row in downloader.get_comments_from_url(url, sort_by=SORT_BY_RECENT):
                if count >= per_video:
                    break
                text = clean(row.get("text") or "")
                if not text:
                    continue
                out.append({
                    "source": "YouTube Comment",
                    "title": "",
                    "text": text,
                    "url": url,
                    "author": clean(row.get("author") or ""),
                    "published": str(row.get("time_parsed") or row.get("time") or ""),
                    "buyer_signal": "youtube_comment_purchase_intent",
                    "credibility_score": 80,
                })
                count += 1
            print("OCEAN_YOUTUBE_VIDEO_OK", count, url)
        except Exception as exc:
            print("OCEAN_YOUTUBE_VIDEO_ERROR", type(exc).__name__, url, exc)
    print("OCEAN_SOURCE youtube_comments", len(out))
    return out


def _extract_forum_record(obj: dict, fallback_url: str) -> dict:
    # forum-dl extractors do not all emit identical field names; normalize common forms.
    content = (
        obj.get("content") or obj.get("text") or obj.get("body") or obj.get("message")
        or obj.get("raw") or obj.get("description") or ""
    )
    title = obj.get("title") or obj.get("subject") or obj.get("thread_title") or ""
    author = obj.get("author") or obj.get("username") or obj.get("user") or ""
    if isinstance(author, dict):
        author = author.get("name") or author.get("username") or ""
    url = obj.get("url") or obj.get("permalink") or obj.get("link") or fallback_url
    published = obj.get("date") or obj.get("created_at") or obj.get("published") or ""
    return {
        "source": "forum-dl",
        "title": clean(title),
        "text": clean(content),
        "url": clean(url),
        "author": clean(author),
        "published": clean(published),
        "buyer_signal": "forum_post_purchase_intent",
        "credibility_score": 86,
    }


def forum_adapter(urls: list[str]) -> list[dict]:
    out = []
    timeout = int(os.getenv("OCEAN_FORUM_DL_TIMEOUT", "35"))
    for url in urls:
        try:
            p = subprocess.run(
                ["forum-dl", "-q", "--textify", "--no-files", "-f", "jsonl", "-o", "-", url],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if p.returncode != 0:
                print("OCEAN_FORUM_DL_ERROR", p.returncode, url, p.stderr[-240:])
                continue
            added = 0
            for line in p.stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                row = _extract_forum_record(obj, url)
                if row["text"]:
                    out.append(row)
                    added += 1
            print("OCEAN_FORUM_DL_OK", added, url)
        except subprocess.TimeoutExpired:
            print("OCEAN_FORUM_DL_TIMEOUT", url)
        except FileNotFoundError:
            print("OCEAN_FORUM_DL_DISABLED executable_missing")
            break
        except Exception as exc:
            print("OCEAN_FORUM_DL_EXCEPTION", type(exc).__name__, url, exc)
    print("OCEAN_SOURCE forums", len(out))
    return out


def run():
    started = now_utc()
    db = db_client()
    youtube_urls, forum_urls = discover_surface_urls(db)

    raw = []
    source_errors = []
    adapters = [
        ("semantic", lambda: semantic_adapter(db)),
        ("reddit_comments", reddit_adapter),
        ("bluesky", lambda: bluesky_adapter(db)),
        ("youtube_comments", lambda: youtube_adapter(youtube_urls)),
        ("forums", lambda: forum_adapter(forum_urls)),
    ]
    source_counts = {}
    for name, fn in adapters:
        try:
            rows = fn()
            source_counts[name] = len(rows)
            raw.extend(rows)
        except Exception as exc:
            source_counts[name] = 0
            source_errors.append(f"{name}:{type(exc).__name__}")
            print("OCEAN_ADAPTER_ERROR", name, type(exc).__name__, exc)

    unique = {}
    for row in raw:
        key = candidate_key(row)
        unique.setdefault(key, row)

    reasons = Counter()
    qualified = []
    by_source = defaultdict(int)
    for row in unique.values():
        lead, reason = classify_candidate(row)
        reasons[reason] += 1
        if lead:
            qualified.append(lead)
            by_source[lead.get("source", "unknown")] += 1

    new = []
    for lead in qualified:
        skey, stype = _source_key_from_url(str(lead.get("url") or ""))
        if skey:
            learn_discovered_source(
                db,
                source_key=skey,
                source_type=stype,
                url=str(lead.get("url") or ""),
                qualified=1,
                new=0,
            )

    for lead in qualified:
        journey = record_person_event(db, lead)
        lead["journey_score"] = int(journey.get("journey_score") or lead.get("intent_score") or 0)
        lead["journey_events"] = int(journey.get("events") or 1)
        lead["journey_sources"] = journey.get("sources") or [lead.get("source", "")]

        key = candidate_key(lead)
        if db:
            ref = db.collection(NOTIFIED_COLLECTION).document(key)
            try:
                if ref.get().exists:
                    continue
            except Exception as exc:
                print("OCEAN_DEDUPE_READ_ERROR", type(exc).__name__, exc)
            try:
                ref.set({
                    "source": lead.get("source", ""),
                    "url": lead.get("url", ""),
                    "author": lead.get("author", ""),
                    "classification": lead.get("classification", ""),
                    "journey_score": lead.get("journey_score"),
                    "journey_events": lead.get("journey_events"),
                    "notified_at": started.isoformat(),
                }, merge=True)
            except Exception as exc:
                print("OCEAN_DEDUPE_WRITE_ERROR", type(exc).__name__, exc)
        new.append(lead)
        skey, stype = _source_key_from_url(str(lead.get("url") or ""))
        if skey:
            learn_discovered_source(
                db,
                source_key=skey,
                source_type=stype,
                url=str(lead.get("url") or ""),
                qualified=0,
                new=1,
            )

    for source_name, raw_count in source_counts.items():
        q_count = int(by_source.get({
            "semantic": "Exa Semantic",
            "reddit_comments": "Reddit Comment RSS",
            "bluesky": "Bluesky Public Search",
            "youtube_comments": "YouTube Comment",
            "forums": "forum-dl",
        }.get(source_name, source_name), 0))
        n_count = sum(1 for lead in new if lead.get("source") == {
            "semantic": "Exa Semantic",
            "reddit_comments": "Reddit Comment RSS",
            "bluesky": "Bluesky Public Search",
            "youtube_comments": "YouTube Comment",
            "forums": "forum-dl",
        }.get(source_name, source_name))
        update_source_stats(db, source_name, raw=raw_count, qualified=q_count, new=n_count)

    stats = {
        "version": VERSION,
        "raw": len(raw),
        "unique": len(unique),
        "qualified": len(qualified),
        "new": len(new),
        "source_counts": source_counts,
        "qualified_by_source": dict(by_source),
        "reject_reasons": dict(reasons),
        "source_errors": source_errors,
        "youtube_urls": len(youtube_urls),
        "forum_urls": len(forum_urls),
        "source_learning_scores": load_source_scores(db),
        "journey_hot": sum(1 for x in new if int(x.get("journey_score") or 0) >= 95),
        "learned_sources": best_discovered_sources(db, limit=12),
    }

    if db:
        try:
            db.collection(SCAN_COLLECTION).document(started.strftime("%Y%m%d%H%M%S")).set({
                **stats, "scanned_at": started.isoformat()
            }, merge=True)
        except Exception as exc:
            print("OCEAN_SCAN_WRITE_ERROR", type(exc).__name__, exc)

    print("OCEAN_SOURCE_HUB_COMPLETE", json.dumps(stats, ensure_ascii=False))

    if new:
        lines = [f"🌊 OCEAN SOURCE HUB | {len(new)} YENİ BUYER"]
        for lead in sorted(new, key=lambda x: (int(x.get("journey_score") or 0), x["classification"] == "HOT", x["intent_score"]), reverse=True)[:12]:
            lines.append(
                f"\n{lead['classification']} | {lead.get('source','')} | I{lead['intent_score']} J{lead.get('journey_score', lead['intent_score'])} C{lead['credibility_score']}"
                f"\n👤 {clean(lead.get('author',''))[:80]}"
                f"\n{clean(lead.get('text',''))[:420]}"
                f"\n{lead.get('url','')}"
            )
        notify("\n".join(lines))
    return new


if __name__ == "__main__":
    run()
