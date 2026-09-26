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

VERSION = "1.1-web-source-discovery"
MAX_AGE_DAYS = int(os.getenv("RADAR_PUBLIC_WEB_MAX_AGE_DAYS", "45"))
TIMEOUT = int(os.getenv("RADAR_HTTP_TIMEOUT", "20"))
MAX_RESULTS_PER_QUERY = int(os.getenv("RADAR_PUBLIC_WEB_RESULTS_PER_QUERY", "10"))
MAX_FETCHES = int(os.getenv("RADAR_PUBLIC_WEB_MAX_FETCHES", "60"))


SOURCE_ROOTS = {
    "Expat.com": "https://www.expat.com/en/forum/europe/cyprus/",
    "Kibkom": "https://kibkomnorthcyprusforum.com/",
    "BritishExpats": "https://britishexpats.com/forum/",
}

DISCOVERY_MAX_PAGES_PER_SOURCE = int(os.getenv("RADAR_PUBLIC_WEB_DISCOVERY_MAX_PAGES", "40"))
DISCOVERY_MAX_CRAWL_PAGES = int(os.getenv("RADAR_PUBLIC_WEB_DISCOVERY_CRAWL_PAGES", "10"))

SOURCE_QUERIES = {
    "Expat.com": (
        "site:expat.com/en/forum/europe/cyprus \"North Cyprus\" (\"looking to buy\" OR \"buying property\" OR \"want to buy\" OR \"planning to buy\")",
        "site:expat.com/en/forum/europe/cyprus \"Northern Cyprus\" (\"property\" OR \"apartment\" OR \"villa\") (\"looking\" OR \"buy\")",
    ),
    "Kibkom": (
        "site:kibkomnorthcyprusforum.com (\"looking to buy\" OR \"want to buy\" OR \"buying\") (property OR apartment OR villa)",
        "site:kibkomnorthcyprusforum.com (Girne OR Kyrenia OR Iskele OR Famagusta) (\"looking for\" OR \"want to buy\")",
    ),
    "TripAdvisor": (
        "site:tripadvisor.com/ShowTopic (Lapta OR Kyrenia OR \"North Cyprus\") (\"looking to buy\" OR \"thinking of buying\" OR \"want to buy\")",
    ),
    "BritishExpats": (
        "site:britishexpats.com/forum \"North Cyprus\" (\"looking to buy\" OR \"buy property\" OR \"thinking of buying\")",
    ),
    "Quora": (
        "site:quora.com \"North Cyprus\" (\"buy property\" OR \"buy apartment\" OR \"buying a property\")",
    ),
    "Facebook Public": (
        "site:facebook.com/groups \"North Cyprus\" (\"looking to buy\" OR \"want to buy\" OR \"buy apartment\")",
        "site:facebook.com/groups \"Северный Кипр\" (\"хочу купить\" OR \"куплю квартиру\" OR \"ищу квартиру\")",
        "site:facebook.com/groups \"Kuzey Kıbrıs\" (\"ev almak istiyorum\" OR \"daire almak istiyorum\" OR \"satılık daire arıyorum\")",
    ),
    "YouTube Public": (
        "site:youtube.com/watch \"North Cyprus\" (\"buy property\" OR \"buy apartment\")",
        "site:youtube.com/watch \"Северный Кипр\" (\"купить квартиру\" OR \"недвижимость\")",
    ),
}

BUY_ANCHOR_RE = re.compile(
    r"(?:"
    r"looking\s+to\s+buy|want(?:ing)?\s+to\s+buy|planning\s+to\s+buy|"
    r"thinking\s+of\s+buying|considering\s+buying|interested\s+in\s+buying|"
    r"buy(?:ing)?\s+(?:a\s+)?(?:property|apartment|flat|house|villa|studio)|"
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

    return {
        "url": str(response.url),
        "title": title,
        "text": text[:120000],
        "published": _page_published(soup),
        "extractor": "trafilatura" if extracted else "beautifulsoup",
    }


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


def classify_window(window: str) -> tuple[dict[str, Any] | None, str]:
    if SELLER_PAGE_RE.search(window) and not BUY_ANCHOR_RE.search(window):
        return None, "seller_page"
    if not v6.has_nc_geo(window):
        return None, "no_north_context"
    signal, reason = v6.classify_text(
        window,
        group="",
        author="",
        explicit_geo=True,
    )
    if signal is None:
        return None, reason
    if signal.get("intent_type") != "BUYER":
        return None, "not_buyer"
    return signal, "accepted"


def _lead_id(url: str, window: str) -> str:
    stable = f"public-web|{url}|{hashlib.sha256(window.casefold().encode('utf-8', 'ignore')).hexdigest()}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


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
        debug[source] = {
            "feeds": len(result.get("feeds", []) or []),
            "sitemaps": len(result.get("sitemaps", []) or []),
            "feed_urls": len(result.get("feed_urls", []) or []),
            "sitemap_urls": len(result.get("sitemap_urls", []) or []),
            "crawl_urls": len(result.get("crawl_urls", []) or []),
            "candidate_urls": len(urls),
            "errors": list(result.get("errors", []) or [])[:8],
        }
        for url in urls:
            rows.append({
                "source": source,
                "title": "",
                "url": url,
                "snippet": "",
                "rss_published": "",
                "discovery": "native_feed_sitemap_crawl",
            })
    return rows, debug


def run() -> None:
    os.environ["RADAR_SALES_ONLY"] = "1"
    db = v6.core.db()
    stats = Counter()
    rejects = Counter()
    source_stats = Counter()
    discovery_stats = Counter()
    discovery_rows, discovery_debug = discover_source_rows()
    seen_urls: set[str] = set()
    seen_windows: set[str] = set()
    fetched = 0
    accepted: list[dict[str, Any]] = []

    # First-party discovery: RSS/Atom, sitemap and bounded internal crawl.
    # These URLs do not depend on Bing/Google indexing.
    for row in discovery_rows:
        source = str(row.get("source") or "Public Web")
        url = str(row.get("url") or "")
        if not url or url in seen_urls or fetched >= MAX_FETCHES:
            continue
        seen_urls.add(url)
        fetched += 1
        discovery_stats["native_candidate_urls"] += 1

        try:
            page = fetch_page(url)
        except Exception as exc:
            rejects[f"native_fetch_{type(exc).__name__}"] += 1
            continue

        stats["pages"] += 1
        discovery_stats[f"extractor_{page.get('extractor','unknown')}"] += 1
        page_text = f"{page.get('title','')} {page.get('text','')}"
        windows = extract_candidate_windows(page_text)
        if not windows:
            rejects["native_no_buyer_anchor"] += 1
            continue

        freshness, age_days = _freshness(page.get("published"))
        if freshness == "stale":
            rejects["native_stale"] += 1
            continue

        for window in windows:
            wkey = hashlib.sha256(window.casefold().encode("utf-8", "ignore")).hexdigest()
            if wkey in seen_windows:
                rejects["duplicate_window"] += 1
                continue
            seen_windows.add(wkey)

            signal, reason = classify_window(window)
            if signal is None:
                rejects[f"native_{reason}"] += 1
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
                "author": "",
                "message": window,
                "text": window,
                "url": page.get("url") or url,
                "market": "north_cyprus",
                "route_to": "Prime Kıbrıs",
                "found_at": datetime.now(timezone.utc).isoformat(),
                "message_time": page.get("published").isoformat() if page.get("published") else "",
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
                stats["review_unknown_age"] += 1
                discovery_stats["native_review_unknown_age"] += 1
                continue

            ref.set(lead, merge=True)
            accepted.append(lead)
            stats["new"] += 1
            discovery_stats["native_new"] += 1

    for source, queries in SOURCE_QUERIES.items():
        for query in queries:
            stats["queries"] += 1
            try:
                rows = bing_rss(query)
            except Exception as exc:
                rejects[f"search_{type(exc).__name__}"] += 1
                continue
            stats["search_rows"] += len(rows)

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
                page_text = f"{page.get('title','')} {page.get('text','')}"
                windows = extract_candidate_windows(page_text)
                if not windows:
                    rejects["no_buyer_anchor"] += 1
                    continue

                freshness, age_days = _freshness(page.get("published"))
                if freshness == "stale":
                    rejects["stale"] += 1
                    continue

                for window in windows:
                    wkey = hashlib.sha256(window.casefold().encode("utf-8", "ignore")).hexdigest()
                    if wkey in seen_windows:
                        rejects["duplicate_window"] += 1
                        continue
                    seen_windows.add(wkey)

                    signal, reason = classify_window(window)
                    if signal is None:
                        rejects[reason] += 1
                        continue

                    stats["valid_buyers"] += 1
                    source_stats[source] += 1
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
                        "author": "",
                        "message": window,
                        "text": window,
                        "url": page.get("url") or url,
                        "market": "north_cyprus",
                        "route_to": "Prime Kıbrıs",
                        "found_at": datetime.now(timezone.utc).isoformat(),
                        "message_time": page.get("published").isoformat() if page.get("published") else "",
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
                        stats["review_unknown_age"] += 1
                        continue

                    ref.set(lead, merge=True)
                    accepted.append(lead)
                    stats["new"] += 1

    for lead in accepted:
        if v6.notify_lead(lead, "PUBLIC WEB"):
            try:
                db.collection(v6.core.COLLECTION).document(lead["lead_id"]).set(
                    {"v6_notified_at": datetime.now(timezone.utc).isoformat()},
                    merge=True,
                )
            except Exception:
                pass

    report = {
        "version": VERSION,
        "queries": stats["queries"],
        "search_rows": stats["search_rows"],
        "pages": stats["pages"],
        "valid_buyers": stats["valid_buyers"],
        "new": stats["new"],
        "known": stats["known"],
        "review_unknown_age": stats["review_unknown_age"],
        "accepted_by_source": dict(source_stats),
        "discovery_stats": dict(discovery_stats),
        "discovery_debug": discovery_debug,
        "reject_reasons": dict(rejects),
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


if __name__ == "__main__":
    run()
