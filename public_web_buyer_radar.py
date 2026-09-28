from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from bs4 import BeautifulSoup
import trafilatura

import nc_v6_broad_radar as v6
import web_source_discovery as discovery
import forum_engine
import adaptive_radar_learning as learning
import crawl4ai_radar_adapter as crawl4ai_adapter

VERSION = "1.7-productive-source-focus"
MAX_AGE_DAYS = int(os.getenv("RADAR_PUBLIC_WEB_MAX_AGE_DAYS", "45"))
TIMEOUT = int(os.getenv("RADAR_HTTP_TIMEOUT", "20"))
MAX_RESULTS_PER_QUERY = int(os.getenv("RADAR_PUBLIC_WEB_RESULTS_PER_QUERY", "10"))
MAX_FETCHES = int(os.getenv("RADAR_PUBLIC_WEB_MAX_FETCHES", "84"))
SOURCE_FETCH_QUOTA = int(os.getenv("RADAR_PUBLIC_WEB_SOURCE_FETCH_QUOTA", "12"))
DIRECT_FEED_ENTRY_LIMIT = int(os.getenv("RADAR_PUBLIC_WEB_DIRECT_FEED_LIMIT", "20"))


SOURCE_ROOTS = {
    "Expat.com": "https://www.expat.com/en/forum/europe/cyprus/",
    "Kibkom": "https://kibkomnorthcyprusforum.com/",
    "BritishExpats": "https://britishexpats.com/forum/cyprus-117/",
}

DIRECT_FEEDS = {
    # Public first-party / community feeds. These are evaluated before broad search.
    "BritishExpats": "https://britishexpats.com/forum/external.php?type=rss2&forumids=117",
    "Reddit NorthCyprus Posts": "https://www.reddit.com/r/NorthCyprus/new/.rss",
    "Reddit NorthCyprus Comments": "https://www.reddit.com/r/NorthCyprus/comments/.rss",
    "Reddit Cyprus Comments": "https://www.reddit.com/r/cyprus/comments/.rss",
}

SOURCE_IMPLICIT_NC = {
    "Kibkom",
    "Reddit NorthCyprus Posts",
    "Reddit NorthCyprus Comments",
}

DIRECT_FORUM_LISTINGS = {
    # Dedicated North Cyprus sub-forum.
    "Expat.com": {
        "url": "https://www.expat.com/en/forum/europe/cyprus/north-cyprus/",
        "include_pattern": r"/en/forum/europe/cyprus/north-cyprus/\d+[-/]",
    },
}

DISCOVERY_MAX_PAGES_PER_SOURCE = int(os.getenv("RADAR_PUBLIC_WEB_DISCOVERY_MAX_PAGES", "40"))
DISCOVERY_MAX_CRAWL_PAGES = int(os.getenv("RADAR_PUBLIC_WEB_DISCOVERY_CRAWL_PAGES", "10"))

SOURCE_QUERIES = {
    "Expat.com": (
        "site:expat.com/en/forum/europe/cyprus \"North Cyprus\" (\"looking to buy\" OR \"buying property\" OR \"want to buy\" OR \"planning to buy\")",
        "site:expat.com/en/forum/europe/cyprus \"Northern Cyprus\" (property OR apartment OR villa) (\"looking to buy\" OR \"thinking of buying\" OR \"interested in buying\")",
    ),
    "Expat.com Spain": (
        "site:expat.com/en/forum/europe/spain (\"North Cyprus\" OR \"Northern Cyprus\") (\"buy property\" OR \"looking to buy\" OR \"buy apartment\")",
    ),
    "Expat.com France": (
        "site:expat.com/en/forum/europe/france (\"North Cyprus\" OR \"Northern Cyprus\" OR \"Chypre du Nord\") (\"buy property\" OR \"looking to buy\" OR \"acheter\")",
    ),
    "Kibkom": (
        "site:kibkomnorthcyprusforum.com (\"looking to buy\" OR \"want to buy\" OR \"buying\") (property OR apartment OR villa)",
        "site:kibkomnorthcyprusforum.com (Girne OR Kyrenia OR Iskele OR Famagusta) (\"looking for\" OR \"want to buy\")",
    ),
    "Reddit NorthCyprus": (
        "site:reddit.com/r/NorthCyprus (\"looking to buy\" OR \"want to buy\" OR \"planning on buying\" OR \"buying property\")",
        "site:reddit.com/r/NorthCyprus (apartment OR villa OR property) (budget OR title OR deed OR payment plan) buy",
    ),
    "Reddit Cyprus": (
        "site:reddit.com/r/cyprus (\"North Cyprus\" OR \"Northern Cyprus\") (\"looking to buy\" OR \"want to buy\" OR \"buying property\")",
    ),
    "BritishExpats": (
        "site:britishexpats.com/forum \"North Cyprus\" (\"looking to buy\" OR \"buy property\" OR \"thinking of buying\")",
    ),
    "TripAdvisor": (
        "site:tripadvisor.com/ShowTopic (Lapta OR Kyrenia OR \"North Cyprus\") (\"looking to buy\" OR \"thinking of buying\" OR \"want to buy\")",
    ),
}
BUY_ANCHOR_RE = re.compile(
    r"(?:"
    r"looking\s+to\s+buy|want(?:ing)?\s+to\s+buy|planning\s+to\s+buy|"
    r"thinking\s+of\s+buying|considering\s+buying|interested\s+in\s+buying|"
    r"buy(?:ing)?\s+(?:a\s+)?(?:property|apartment|flat|house|villa|studio)|"
    r"(?:looking\s+for|seeking)\s+(?:a\s+|an\s+)?(?:new\s+build|property|apartment|flat|house|villa|bungalow)|"
    r"house\s+hunting|property\s+hunting|"
    r"хочу\s+купить|хотим\s+купить|куплю|планир\w*\s+купить|"
    r"ищу\s+.{0,80}(?:для\s+покупк\w*|купить)|"
    r"(?:ev|daire|villa)\s+almak\s+istiyorum|"
    r"(?:ev|daire|villa)\s+satın\s+almak\s+istiyorum|"
    r"satılık\s+(?:ev|daire|villa)\s+arıyorum"
    r")",
    re.I | re.S,
)

SELLER_PAGE_RE = re.compile(
    r"(?:"
    r"our\s+properties|contact\s+our\s+sales|book\s+a\s+viewing|"
    r"available\s+units|for\s+sale\s+from|property\s+developer|"
    r"estate\s+agency|real\s+estate\s+agency|"
    r"наши\s+объекты|отдел\s+продаж|агентство\s+недвижимости|"
    r"satış\s+ofisi|gayrimenkul\s+danışman"
    r")",
    re.I,
)

DATE_META_KEYS = (
    "article:published_time",
    "datePublished",
    "date",
    "pubdate",
    "publishdate",
    "timestamp",
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _parse_date(value: str) -> datetime | None:
    raw = _norm(value)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Forums such as Expat.com expose human relative dates instead of ISO dates.
    low = raw.casefold()
    now = datetime.now(timezone.utc)
    if low in {"today", "just now"}:
        return now
    if low == "yesterday":
        return now - timedelta(days=1)

    m = re.search(
        r"\b(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago\b",
        low,
    )
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    if unit == "second":
        return now - timedelta(seconds=amount)
    if unit == "minute":
        return now - timedelta(minutes=amount)
    if unit == "hour":
        return now - timedelta(hours=amount)
    if unit == "day":
        return now - timedelta(days=amount)
    if unit == "week":
        return now - timedelta(weeks=amount)
    if unit == "month":
        return now - timedelta(days=amount * 30)
    if unit == "year":
        return now - timedelta(days=amount * 365)
    return None


def bing_rss(query: str) -> list[dict[str, Any]]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PrimeKibrisLeadRadar/1.0)"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    out: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:MAX_RESULTS_PER_QUERY]:
        link = _norm(item.findtext("link") or "")
        if not link:
            continue
        out.append({
            "title": _norm(item.findtext("title") or ""),
            "url": link,
            "snippet": _norm(item.findtext("description") or ""),
            "rss_published": _norm(item.findtext("pubDate") or ""),
        })
    return out


def _page_published(soup: BeautifulSoup) -> datetime | None:
    for key in DATE_META_KEYS:
        selectors = (
            f'meta[property="{key}"]',
            f'meta[name="{key}"]',
            f'meta[itemprop="{key}"]',
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if node and node.get("content"):
                dt = _parse_date(str(node.get("content")))
                if dt:
                    return dt
    time_node = soup.select_one("time[datetime]")
    if time_node and time_node.get("datetime"):
        return _parse_date(str(time_node.get("datetime")))
    return None


def _fallback_page_from_row(row: dict[str, Any], url: str) -> dict[str, Any]:
    title = _norm(row.get("title") or "")
    snippet = _norm(
        BeautifulSoup(str(row.get("snippet") or ""), "html.parser").get_text(" ", strip=True)
    )
    return {
        "url": url,
        "title": title,
        "text": _norm(f"{title} {snippet}"),
        "published": _parse_date(str(row.get("rss_published") or "")),
        "extractor": "feed_or_search_snippet",
        "forum_engine": "generic",
        "forum_posts": [],
    }


def fetch_page(url: str) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PrimeKibrisLeadRadar/1.1)"},
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = _norm(soup.title.get_text(" ", strip=True) if soup.title else "")

    extracted = ""
    try:
        extracted = trafilatura.extract(
            response.text,
            url=str(response.url),
            include_comments=True,
            include_tables=False,
            include_links=False,
            favor_recall=True,
            deduplicate=True,
        ) or ""
    except Exception:
        extracted = ""

    if extracted:
        text = _norm(extracted)
    else:
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        text = _norm(soup.get_text(" ", strip=True))

    forum = forum_engine.extract_forum_posts(response.text, str(response.url))
    return {
        "url": str(response.url),
        "title": title,
        "text": text[:120000],
        "published": _page_published(soup),
        "extractor": "trafilatura" if extracted else "beautifulsoup",
        "forum_engine": forum.get("engine", "generic"),
        "forum_posts": forum.get("posts", []),
    }



def _page_units(page: dict[str, Any]) -> list[dict[str, Any]]:
    posts = list(page.get("forum_posts") or [])
    units: list[dict[str, Any]] = []
    for post in posts:
        text = _norm(post.get("text") or "")
        if not text:
            continue
        published = _parse_date(str(post.get("published") or ""))
        units.append({
            "text": text,
            "author": str(post.get("author") or ""),
            "published": published,
            "post_id": str(post.get("post_id") or ""),
            "kind": "forum_post",
        })
    if units:
        return units
    return [{
        "text": f"{page.get('title','')} {page.get('text','')}",
        "author": "",
        "published": page.get("published"),
        "post_id": "",
        "kind": "page",
    }]


def _capture_concern(
    db: Any,
    *,
    source: str,
    url: str,
    text: str,
    published: datetime | None,
    stats: Counter,
) -> None:
    signal = learning.concern_signal(text, has_north_context=v6.has_nc_geo(text))
    if not signal:
        return
    try:
        learning.save_concern(
            db,
            source=source,
            url=url,
            text=text,
            labels=signal["labels"],
            score=signal["score"],
            published=published.isoformat() if published else "",
        )
        stats["concerns"] += 1
    except Exception:
        stats["concern_save_error"] += 1

def extract_candidate_windows(text: str, radius: int = 650) -> list[str]:
    raw = _norm(text)
    if not raw:
        return []
    windows: list[str] = []
    seen: set[str] = set()
    for match in BUY_ANCHOR_RE.finditer(raw):
        start = max(0, match.start() - radius)
        end = min(len(raw), match.end() + radius)
        window = _norm(raw[start:end])
        key = hashlib.sha256(window.casefold().encode("utf-8", "ignore")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        windows.append(window)
        if len(windows) >= 8:
            break
    return windows


def _freshness(published: datetime | None) -> tuple[str, int | None]:
    if published is None:
        return "unknown", None
    age = max(0, int((datetime.now(timezone.utc) - published).total_seconds() // 86400))
    if age <= 7:
        return "0_7d", age
    if age <= MAX_AGE_DAYS:
        return "8_45d", age
    return "stale", age


def classify_window(window: str, *, implicit_north_cyprus: bool = False) -> tuple[dict[str, Any] | None, str]:
    if SELLER_PAGE_RE.search(window) and not BUY_ANCHOR_RE.search(window):
        return None, "seller_page"
    if not implicit_north_cyprus and not v6.has_nc_geo(window):
        return None, "no_north_context"
    signal, reason = v6.classify_text(
        window,
        group="",
        author="",
        explicit_geo=implicit_north_cyprus or v6.has_nc_geo(window),
    )
    if signal is None:
        return None, reason
    if signal.get("intent_type") != "BUYER":
        return None, "not_buyer"
    return signal, "accepted"


def _lead_id(url: str, window: str) -> str:
    stable = f"public-web|{url}|{hashlib.sha256(window.casefold().encode('utf-8', 'ignore')).hexdigest()}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def discover_forumscraper_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    debug: dict[str, Any] = {}

    for source, root in SOURCE_ROOTS.items():
        result = forum_engine.discover_forum_threads(
            root,
            limit=int(os.getenv("RADAR_FORUM_THREAD_LIMIT", "30") or "30"),
            timeout=min(TIMEOUT, 20),
        )
        debug[source] = {
            "engine": result.get("engine") or "",
            "threads": len(result.get("threads") or []),
            "error": result.get("error") or "",
        }
        for url in result.get("threads") or []:
            rows.append({
                "source": source,
                "title": "",
                "url": url,
                "snippet": "",
                "rss_published": "",
                "discovery": "forumscraper_thread_discovery",
            })
    return rows, debug


def discover_direct_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    debug: dict[str, Any] = {}

    for source, feed_url in DIRECT_FEEDS.items():
        try:
            entries = discovery.fetch_feed_entries(feed_url, timeout=min(TIMEOUT, 15))
        except Exception as exc:
            debug[f"{source}:feed"] = {"error": f"{type(exc).__name__}:{exc}"}
            continue
        debug[f"{source}:feed"] = {"entries": len(entries), "url": feed_url}
        for entry in entries[:DIRECT_FEED_ENTRY_LIMIT]:
            inline_text = BeautifulSoup(
                str(entry.get("text") or ""), "html.parser"
            ).get_text(" ", strip=True)
            rows.append({
                "source": source,
                "title": entry.get("title") or "",
                "url": entry.get("url") or "",
                "snippet": _norm(inline_text),
                "rss_published": entry.get("published") or "",
                "discovery": "direct_rss",
                "implicit_nc": source.startswith("Reddit NorthCyprus"),
            })

    for source, cfg in DIRECT_FORUM_LISTINGS.items():
        try:
            urls = discovery.fetch_listing_thread_links(
                cfg["url"],
                timeout=min(TIMEOUT, 15),
                include_pattern=cfg.get("include_pattern"),
                limit=80,
            )
        except Exception as exc:
            debug[f"{source}:listing"] = {"error": f"{type(exc).__name__}:{exc}"}
            continue
        debug[f"{source}:listing"] = {"threads": len(urls), "url": cfg["url"]}
        for url in urls:
            rows.append({
                "source": source,
                "title": "",
                "url": url,
                "snippet": "",
                "rss_published": "",
                "discovery": "direct_forum_listing",
                "implicit_nc": "north-cyprus" in str(cfg.get("url") or "").casefold(),
            })

    return rows, debug


def discover_source_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    debug: dict[str, Any] = {}
    for source, root in SOURCE_ROOTS.items():
        try:
            result = discovery.discover_urls(
                root,
                timeout=min(TIMEOUT, 15),
                max_pages=DISCOVERY_MAX_PAGES_PER_SOURCE,
                max_crawl_pages=DISCOVERY_MAX_CRAWL_PAGES,
            )
        except Exception as exc:
            debug[source] = {"error": f"{type(exc).__name__}:{exc}"}
            continue

        urls = discovery.merged_candidate_urls(result)
        crawl_urls: list[str] = []
        crawl_stats: dict[str, Any] = {}
        if len(urls) < DISCOVERY_MAX_PAGES_PER_SOURCE:
            try:
                discovered, crawl_stats = crawl4ai_adapter.discover_urls(
                    root,
                    max_depth=int(os.getenv("RADAR_CRAWL4AI_DISCOVERY_DEPTH", "2") or "2"),
                    max_pages=int(os.getenv("RADAR_CRAWL4AI_DISCOVERY_MAX_PAGES", "40") or "40"),
                )
                for url in discovered:
                    if discovery.same_site(url, root) and discovery.relevant_url(url):
                        crawl_urls.append(url)
            except Exception as exc:
                crawl_stats = {"error": f"{type(exc).__name__}:{exc}"}

        merged = list(dict.fromkeys([*urls, *crawl_urls]))
        debug[source] = {
            "feeds": len(result.get("feeds", []) or []),
            "sitemaps": len(result.get("sitemaps", []) or []),
            "feed_urls": len(result.get("feed_urls", []) or []),
            "sitemap_urls": len(result.get("sitemap_urls", []) or []),
            "crawl_urls": len(result.get("crawl_urls", []) or []),
            "crawl4ai_urls": len(crawl_urls),
            "crawl4ai_stats": crawl_stats,
            "candidate_urls": len(merged),
            "errors": list(result.get("errors", []) or [])[:8],
        }
        for url in merged:
            rows.append({
                "source": source,
                "title": "",
                "url": url,
                "snippet": "",
                "rss_published": "",
                "discovery": "crawl4ai_deep_discovery" if url in crawl_urls and url not in urls else "native_feed_sitemap_crawl",
            })
    return rows, debug


def run() -> None:
    os.environ["RADAR_SALES_ONLY"] = "1"
    db = v6.core.db()
    stats = Counter()
    rejects = Counter()
    source_stats = Counter()
    source_scan_counts = Counter()
    source_new_counts = Counter()
    source_fetch_attempts = Counter()
    discovery_stats = Counter()
    forum_rows, forum_debug = discover_forumscraper_rows()
    direct_rows, direct_debug = discover_direct_rows()
    discovery_rows, discovery_debug = discover_source_rows()
    # Productive/direct sources must consume the fetch budget before broad crawling.
    discovery_rows = direct_rows + forum_rows + discovery_rows
    discovery_debug = {
        "forumscraper": forum_debug,
        "direct": direct_debug,
        "generic": discovery_debug,
    }
    discovery_stats["forumscraper_rows"] = len(forum_rows)
    seen_urls: set[str] = set()
    seen_windows: set[str] = set()
    near_windows = learning.NearDuplicateIndex(threshold=92.0, min_chars=50, max_items=500)
    fetched = 0
    accepted: list[dict[str, Any]] = []
    review_candidates: list[dict[str, Any]] = []

    # First-party discovery: RSS/Atom, sitemap and bounded internal crawl.
    # These URLs do not depend on Bing/Google indexing.
    for row in discovery_rows:
        source = str(row.get("source") or "Public Web")
        url = str(row.get("url") or "")
        if not url or url in seen_urls or fetched >= MAX_FETCHES:
            continue
        if source_fetch_attempts[source] >= SOURCE_FETCH_QUOTA:
            discovery_stats["source_quota_skipped"] += 1
            continue
        seen_urls.add(url)
        fetched += 1
        source_fetch_attempts[source] += 1
        discovery_stats["native_candidate_urls"] += 1

        try:
            page = fetch_page(url)
        except Exception as exc:
            rejects[f"native_fetch_{type(exc).__name__}"] += 1
            page = _fallback_page_from_row(row, url)
            if not page.get("text"):
                continue
            discovery_stats["native_feed_fallback"] += 1

        stats["pages"] += 1
        discovery_stats[f"extractor_{page.get('extractor','unknown')}"] += 1
        discovery_stats[f"forum_engine_{page.get('forum_engine','generic')}"] += 1
        source_scan_counts[source] += 1
        units = _page_units(page)
        any_windows = False

        for unit in units:
            unit_text = str(unit.get("text") or "")
            unit_published = unit.get("published")
            _capture_concern(
                db,
                source=source,
                url=str(page.get("url") or url),
                text=unit_text,
                published=unit_published,
                stats=discovery_stats,
            )
            windows = extract_candidate_windows(unit_text)
            if not windows:
                continue
            any_windows = True

            freshness, age_days = _freshness(unit_published)
            if freshness == "stale":
                rejects["native_stale"] += 1
                continue

            for window in windows:
                wkey = hashlib.sha256(window.casefold().encode("utf-8", "ignore")).hexdigest()
                if wkey in seen_windows:
                    rejects["duplicate_window"] += 1
                    continue
                seen_windows.add(wkey)
    
                signal, reason = classify_window(
                    window,
                    implicit_north_cyprus=bool(row.get("implicit_nc")) or source in SOURCE_IMPLICIT_NC,
                )
                if signal is None:
                    rejects[f"native_{reason}"] += 1
                    continue
                if near_windows.is_duplicate(window):
                    rejects["near_duplicate_buyer_window"] += 1
                    continue
    
                stats["valid_buyers"] += 1
                source_stats[source] += 1
                discovery_stats["native_valid_buyers"] += 1
                lead_id = _lead_id(str(page.get("url") or url), window)
                ref = db.collection(v6.core.COLLECTION).document(lead_id)
                snap = ref.get()
                if snap.exists:
                    previous = snap.to_dict() or {}
                    if previous.get("v5_notified_at") or previous.get("v6_notified_at"):
                        stats["known"] += 1
                        discovery_stats["native_known"] += 1
                        continue
    
                lead = {
                    **signal,
                    "lead_id": lead_id,
                    "source": source,
                    "platform": source,
                    "source_type": "public_web_native_discovery",
                    "group": source,
                    "title": page.get("title") or "",
                    "author": str(unit.get("author") or ""),
                    "message": window,
                    "text": window,
                    "url": page.get("url") or url,
                    "market": "north_cyprus",
                    "route_to": "Prime Kıbrıs",
                    "found_at": datetime.now(timezone.utc).isoformat(),
                    "message_time": unit_published.isoformat() if unit_published else "",
                    "message_age_days": age_days if age_days is not None else "",
                    "freshness": freshness,
                    "classification": "HOT" if freshness == "0_7d" and signal.get("lead_class") == "HOT BUYER" else "WARM",
                    "radar_version": VERSION,
                    "why_selected": ", ".join(signal.get("lead_reasons") or []),
                    "discovery_method": row.get("discovery"),
                    "content_extractor": page.get("extractor"),
                }
    
                if freshness == "unknown":
                    lead["classification"] = "REVIEW"
                    lead["lead_class"] = "REVIEW"
                    lead["review_reason"] = "unknown_page_age"
                    db.collection("bay_s_public_web_review").document(lead_id).set(lead, merge=True)
                    review_candidates.append(lead)
                    stats["review_unknown_age"] += 1
                    discovery_stats["native_review_unknown_age"] += 1
                    continue
    
                ref.set(lead, merge=True)
                accepted.append(lead)
                stats["new"] += 1
                source_new_counts[source] += 1
                discovery_stats["native_new"] += 1
    
    learned_web_terms = learning.read_learned_query_terms(
        db,
        surface="web",
        limit=int(os.getenv("RADAR_LEARNED_WEB_QUERIES", "10") or "10"),
    )
    runtime_source_queries = dict(SOURCE_QUERIES)
    if learned_web_terms:
        runtime_source_queries["Demand Language"] = tuple(learned_web_terms)
    discovery_stats["learned_web_queries"] = len(learned_web_terms)

    for source, queries in runtime_source_queries.items():
        query_history = learning.read_query_history(
            db,
            queries,
            collection="bay_s_radar_web_query_yield",
        )
        ranked_queries = learning.rank_queries(queries, query_history)
        for query in ranked_queries:
            stats["queries"] += 1
            qstat = {
                "raw": 0,
                "north_context": 0,
                "valid": 0,
                "unique": 0,
                "new": 0,
                "near_duplicate": 0,
            }
            try:
                rows = bing_rss(query)
            except Exception as exc:
                rejects[f"search_{type(exc).__name__}"] += 1
                continue
            stats["search_rows"] += len(rows)
            qstat["raw"] = len(rows)

            for row in rows:
                url = str(row.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if fetched >= MAX_FETCHES:
                    break

                fetched += 1
                try:
                    page = fetch_page(url)
                except Exception as exc:
                    rejects[f"fetch_{type(exc).__name__}"] += 1
                    # Snippet fallback still allows discovery, but unknown-age
                    # snippet matches are stored as REVIEW only, never notified.
                    page = {
                        "url": url,
                        "title": row.get("title") or "",
                        "text": f"{row.get('title','')} {row.get('snippet','')}",
                        "published": _parse_date(str(row.get("rss_published") or "")),
                    }

                stats["pages"] += 1
                discovery_stats[f"extractor_{page.get('extractor','snippet_fallback')}"] += 1
                discovery_stats[f"forum_engine_{page.get('forum_engine','generic')}"] += 1
                source_scan_counts[source] += 1
                units = _page_units(page)
                any_windows = False

                for unit in units:
                    unit_text = str(unit.get("text") or "")
                    unit_published = unit.get("published")
                    _capture_concern(
                        db,
                        source=source,
                        url=str(page.get("url") or url),
                        text=unit_text,
                        published=unit_published,
                        stats=discovery_stats,
                    )
                    windows = extract_candidate_windows(unit_text)
                    if not windows:
                        continue
                    any_windows = True

                    freshness, age_days = _freshness(unit_published)
                    if freshness == "stale":
                        rejects["stale"] += 1
                        continue

                    for window in windows:
                        wkey = hashlib.sha256(window.casefold().encode("utf-8", "ignore")).hexdigest()
                        if wkey in seen_windows:
                            rejects["duplicate_window"] += 1
                            continue
                        seen_windows.add(wkey)
                        if v6.has_nc_geo(window):
                            qstat["north_context"] += 1
    
                        signal, reason = classify_window(window)
                        if signal is None:
                            rejects[reason] += 1
                            continue
                        if near_windows.is_duplicate(window):
                            rejects["near_duplicate_buyer_window"] += 1
                            qstat["near_duplicate"] += 1
                            continue
    
                        stats["valid_buyers"] += 1
                        source_stats[source] += 1
                        qstat["valid"] += 1
                        qstat["unique"] += 1
                        lead_id = _lead_id(str(page.get("url") or url), window)
                        ref = db.collection(v6.core.COLLECTION).document(lead_id)
                        snap = ref.get()
                        if snap.exists:
                            previous = snap.to_dict() or {}
                            if previous.get("v5_notified_at") or previous.get("v6_notified_at"):
                                stats["known"] += 1
                                continue
    
                        lead = {
                            **signal,
                            "lead_id": lead_id,
                            "source": source,
                            "platform": source,
                            "source_type": "public_web_buyer_window",
                            "group": source,
                            "title": page.get("title") or row.get("title") or "",
                            "author": str(unit.get("author") or ""),
                            "message": window,
                            "text": window,
                            "url": page.get("url") or url,
                            "market": "north_cyprus",
                            "route_to": "Prime Kıbrıs",
                            "found_at": datetime.now(timezone.utc).isoformat(),
                            "message_time": unit_published.isoformat() if unit_published else "",
                            "message_age_days": age_days if age_days is not None else "",
                            "freshness": freshness,
                            "classification": "HOT" if freshness == "0_7d" and signal.get("lead_class") == "HOT BUYER" else "WARM",
                            "radar_version": VERSION,
                            "why_selected": ", ".join(signal.get("lead_reasons") or []),
                        }
    
                        # Unknown-age pages are retained for audit but not pushed as
                        # sales alerts. Search indices frequently surface old forum
                        # threads with a new crawl date.
                        if freshness == "unknown":
                            lead["classification"] = "REVIEW"
                            lead["lead_class"] = "REVIEW"
                            lead["review_reason"] = "unknown_page_age"
                            db.collection("bay_s_public_web_review").document(lead_id).set(lead, merge=True)
                            review_candidates.append(lead)
                            stats["review_unknown_age"] += 1
                            continue
    
                        ref.set(lead, merge=True)
                        accepted.append(lead)
                        stats["new"] += 1
                        source_new_counts[source] += 1
                        qstat["new"] += 1

            try:
                learning.update_query_yield(
                    db,
                    query,
                    qstat,
                    collection="bay_s_radar_web_query_yield",
                )
            except Exception:
                discovery_stats["web_query_yield_save_error"] += 1
    
    for lead in accepted:
        if v6.notify_lead(lead, "PUBLIC WEB"):
            try:
                db.collection(v6.core.COLLECTION).document(lead["lead_id"]).set(
                    {"v6_notified_at": datetime.now(timezone.utc).isoformat()},
                    merge=True,
                )
            except Exception:
                pass

    for source in sorted(set(source_scan_counts) | set(source_stats) | set(source_new_counts)):
        try:
            learning.update_source_yield(
                db,
                source,
                scanned=source_scan_counts[source],
                valid=source_stats[source],
                new=source_new_counts[source],
            )
        except Exception:
            discovery_stats["source_yield_save_error"] += 1

    report = {
        "version": VERSION,
        "forum_rows": len(forum_rows),
        "direct_rows": len(direct_rows),
        "queries": stats["queries"],
        "search_rows": stats["search_rows"],
        "pages": stats["pages"],
        "valid_buyers": stats["valid_buyers"],
        "new": stats["new"],
        "known": stats["known"],
        "review_unknown_age": stats["review_unknown_age"],
        "accepted_by_source": dict(source_stats),
        "scanned_by_source": dict(source_scan_counts),
        "new_by_source": dict(source_new_counts),
        "discovery_stats": dict(discovery_stats),
        "discovery_debug": discovery_debug,
        "reject_reasons": dict(rejects),
        "review_leads": [
            {
                "source": x.get("source"),
                "author": x.get("author"),
                "title": x.get("title"),
                "url": x.get("url"),
                "message": str(x.get("message") or "")[:500],
            }
            for x in review_candidates[:10]
        ],
        "new_leads": [
            {
                "source": x.get("source"),
                "title": x.get("title"),
                "url": x.get("url"),
                "lead_class": x.get("lead_class"),
                "message_age_days": x.get("message_age_days"),
                "message": str(x.get("message") or "")[:500],
            }
            for x in accepted[:20]
        ],
    }
    print("PUBLIC_WEB_BUYER_RADAR", json.dumps(report, ensure_ascii=False))

    try:
        crawl4ai_total = 0
        crawl4ai_parts = []
        generic_debug = (discovery_debug.get("generic") or {}) if isinstance(discovery_debug, dict) else {}
        for source, row in generic_debug.items():
            count = int((row or {}).get("crawl4ai_urls", 0) or 0)
            crawl4ai_total += count
            if count:
                crawl4ai_parts.append(f"{source}:{count}")

        top_rejects = ", ".join(f"{k}:{v}" for k, v in rejects.most_common(6)) or "-"
        source_hits = ", ".join(f"{k}:{v}" for k, v in source_stats.most_common(6)) or "-"
        review_lines = []
        for lead in review_candidates[:3]:
            review_lines.append(
                "\nREVIEW | tarih doğrulanamadı"
                f" | {str(lead.get('source') or '')[:60]}"
                f"\n👤 {str(lead.get('author') or '-')[:80]}"
                f"\n{str(lead.get('message') or '')[:360]}"
                f"\n{str(lead.get('url') or '')[:500]}"
            )

        core_msg = (
            "🌐 PRIME RADAR | PUBLIC WEB\n\n"
            f"Crawl4AI yeni URL: {crawl4ai_total}"
            + (f" ({', '.join(crawl4ai_parts[:6])})" if crawl4ai_parts else "")
            + "\n"
            f"Taranan sayfa: {stats['pages']} | Geçerli BUYER: {stats['valid_buyers']}\n"
            f"Yeni: {stats['new']} | Bilinen: {stats['known']} | REVIEW: {stats['review_unknown_age']}\n"
            f"Kaynak BUYER: {source_hits}\n"
            f"Eleme: {top_rejects}"
            + "".join(review_lines)
        )
        v6.core.telegram(core_msg[:3900])
    except Exception as exc:
        print("PUBLIC_WEB_TELEGRAM_DEBUG_ERROR", type(exc).__name__, str(exc))


if __name__ == "__main__":
    run()
