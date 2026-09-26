from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import deque
from typing import Iterable

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; PrimeKibrisLeadRadar/6.24; +https://primekibris.com)"

FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/json",
}

THREAD_HINT_RE = re.compile(
    r"(?:forum|thread|topic|discussion|question|post|property|real-estate|"
    r"north-cyprus|northern-cyprus|kyrenia|girne|iskele|famagusta|magusa|"
    r"apartment|villa|house|buy|buying|relocat|expat)",
    re.I,
)

ASSET_RE = re.compile(
    r"\.(?:jpg|jpeg|png|gif|webp|svg|css|js|ico|woff2?|ttf|pdf|zip|mp4|mp3)(?:$|[?#])",
    re.I,
)


def _norm_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urllib.parse.urlsplit(raw)
    except Exception:
        return ""
    if p.scheme not in {"http", "https"} or not p.netloc:
        return ""
    clean = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
    return clean


def same_site(url: str, root_url: str) -> bool:
    try:
        a = urllib.parse.urlsplit(url).netloc.casefold().removeprefix("www.")
        b = urllib.parse.urlsplit(root_url).netloc.casefold().removeprefix("www.")
        return bool(a and b and a == b)
    except Exception:
        return False


def discover_html_feeds(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for node in soup.select('link[rel~="alternate"][href]'):
        typ = str(node.get("type") or "").split(";", 1)[0].strip().casefold()
        if typ and typ not in FEED_TYPES:
            continue
        href = urllib.parse.urljoin(base_url, str(node.get("href") or ""))
        href = _norm_url(href)
        if href and href not in seen:
            seen.add(href)
            out.append(href)
    return out


def discover_robots_sitemaps(text: str, root_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().casefold() != "sitemap":
            continue
        url = _norm_url(urllib.parse.urljoin(root_url, value.strip()))
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def parse_sitemap(xml_text: str, sitemap_url: str) -> tuple[list[str], list[str]]:
    pages: list[str] = []
    nested: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return pages, nested

    tag = root.tag.rsplit("}", 1)[-1].casefold()
    for loc_node in root.findall(".//{*}loc"):
        loc = _norm_url((loc_node.text or "").strip())
        if not loc:
            continue
        if tag == "sitemapindex":
            nested.append(loc)
        elif tag == "urlset":
            pages.append(loc)
    return pages, nested


def parse_feed_urls(xml_text: str, feed_url: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()

    for node in root.findall(".//item/link"):
        val = _norm_url((node.text or "").strip())
        if val and val not in seen:
            seen.add(val)
            out.append(val)

    for node in root.findall(".//{*}entry/{*}link"):
        href = _norm_url(str(node.get("href") or ""))
        if href and href not in seen:
            seen.add(href)
            out.append(href)

    return out


def extract_internal_links(html: str, base_url: str, root_url: str) -> list[str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = urllib.parse.urljoin(base_url, str(node.get("href") or ""))
        href = _norm_url(href)
        if not href or not same_site(href, root_url) or ASSET_RE.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def relevant_url(url: str) -> bool:
    return bool(THREAD_HINT_RE.search(urllib.parse.unquote(str(url or ""))))


def _get(session: requests.Session, url: str, timeout: int) -> requests.Response:
    return session.get(
        url,
        headers={"User-Agent": UA},
        timeout=timeout,
        allow_redirects=True,
    )


def discover_urls(
    root_url: str,
    *,
    timeout: int = 15,
    max_sitemaps: int = 6,
    max_pages: int = 80,
    max_crawl_pages: int = 12,
) -> dict:
    root_url = _norm_url(root_url)
    result = {
        "root": root_url,
        "feeds": [],
        "sitemaps": [],
        "feed_urls": [],
        "sitemap_urls": [],
        "crawl_urls": [],
        "errors": [],
    }
    if not root_url:
        result["errors"].append("invalid_root")
        return result

    session = requests.Session()
    parsed = urllib.parse.urlsplit(root_url)
    site_base = f"{parsed.scheme}://{parsed.netloc}"

    homepage_html = ""
    try:
        resp = _get(session, root_url, timeout)
        resp.raise_for_status()
        homepage_html = resp.text
        result["feeds"] = discover_html_feeds(homepage_html, str(resp.url))
    except Exception as exc:
        result["errors"].append(f"home:{type(exc).__name__}")

    for candidate in (
        f"{site_base}/feed",
        f"{site_base}/feed/",
        f"{site_base}/rss",
        f"{site_base}/rss.xml",
        f"{site_base}/feed.xml",
        f"{site_base}/atom.xml",
    ):
        if candidate not in result["feeds"]:
            result["feeds"].append(candidate)

    try:
        robots = _get(session, f"{site_base}/robots.txt", timeout)
        if robots.ok:
            result["sitemaps"].extend(discover_robots_sitemaps(robots.text, site_base))
    except Exception as exc:
        result["errors"].append(f"robots:{type(exc).__name__}")

    for candidate in (f"{site_base}/sitemap.xml", f"{site_base}/sitemap_index.xml"):
        if candidate not in result["sitemaps"]:
            result["sitemaps"].append(candidate)

    feed_urls: list[str] = []
    for feed in list(dict.fromkeys(result["feeds"]))[:8]:
        try:
            resp = _get(session, feed, timeout)
            if not resp.ok:
                continue
            ctype = str(resp.headers.get("content-type") or "").casefold()
            if "xml" not in ctype and "<rss" not in resp.text[:500].casefold() and "<feed" not in resp.text[:500].casefold():
                continue
            for url in parse_feed_urls(resp.text, str(resp.url)):
                if same_site(url, root_url) and relevant_url(url):
                    feed_urls.append(url)
        except Exception as exc:
            result["errors"].append(f"feed:{type(exc).__name__}")

    sitemap_queue = deque(list(dict.fromkeys(result["sitemaps"])))
    seen_sitemaps: set[str] = set()
    sitemap_urls: list[str] = []
    while sitemap_queue and len(seen_sitemaps) < max_sitemaps and len(sitemap_urls) < max_pages:
        sm = sitemap_queue.popleft()
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)
        try:
            resp = _get(session, sm, timeout)
            if not resp.ok:
                continue
            pages, nested = parse_sitemap(resp.text, str(resp.url))
            for child in nested:
                if same_site(child, root_url) and child not in seen_sitemaps:
                    sitemap_queue.append(child)
            for url in pages:
                if same_site(url, root_url) and relevant_url(url):
                    sitemap_urls.append(url)
                    if len(sitemap_urls) >= max_pages:
                        break
        except Exception as exc:
            result["errors"].append(f"sitemap:{type(exc).__name__}")

    crawl_urls: list[str] = []
    if homepage_html:
        queue = deque(extract_internal_links(homepage_html, root_url, root_url))
        seen_crawl: set[str] = {root_url}
        while queue and len(seen_crawl) <= max_crawl_pages:
            url = queue.popleft()
            if url in seen_crawl:
                continue
            seen_crawl.add(url)
            if relevant_url(url):
                crawl_urls.append(url)
            if len(seen_crawl) >= max_crawl_pages:
                break
            try:
                resp = _get(session, url, timeout)
                if not resp.ok or "text/html" not in str(resp.headers.get("content-type") or ""):
                    continue
                for link in extract_internal_links(resp.text, str(resp.url), root_url):
                    if link not in seen_crawl:
                        queue.append(link)
            except Exception:
                continue

    result["feed_urls"] = list(dict.fromkeys(feed_urls))[:max_pages]
    result["sitemap_urls"] = list(dict.fromkeys(sitemap_urls))[:max_pages]
    result["crawl_urls"] = list(dict.fromkeys(crawl_urls))[:max_pages]
    return result



def parse_feed_entries(xml_text: str) -> list[dict]:
    """Return RSS/Atom entries with URL, title, published date and inline text."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    out: list[dict] = []

    for item in root.findall(".//item"):
        link = _norm_url((item.findtext("link") or "").strip())
        if not link:
            continue
        title = " ".join((item.findtext("title") or "").split())
        published = " ".join(
            (
                item.findtext("pubDate")
                or item.findtext("{*}date")
                or item.findtext("date")
                or ""
            ).split()
        )
        description = " ".join((item.findtext("description") or "").split())
        content = ""
        for child in list(item):
            if child.tag.rsplit("}", 1)[-1].casefold() in {"encoded", "content"}:
                content = " ".join((child.text or "").split())
                if content:
                    break
        out.append({
            "url": link,
            "title": title,
            "published": published,
            "text": content or description,
        })

    for entry in root.findall(".//{*}entry"):
        link = ""
        for node in entry.findall("{*}link"):
            href = _norm_url(str(node.get("href") or ""))
            rel = str(node.get("rel") or "alternate").casefold()
            if href and rel in {"alternate", ""}:
                link = href
                break
        if not link:
            continue
        title = " ".join((entry.findtext("{*}title") or "").split())
        published = " ".join(
            (
                entry.findtext("{*}published")
                or entry.findtext("{*}updated")
                or ""
            ).split()
        )
        text = " ".join(
            (
                entry.findtext("{*}content")
                or entry.findtext("{*}summary")
                or ""
            ).split()
        )
        out.append({
            "url": link,
            "title": title,
            "published": published,
            "text": text,
        })

    return out


def fetch_feed_entries(feed_url: str, *, timeout: int = 15) -> list[dict]:
    session = requests.Session()
    resp = _get(session, feed_url, timeout)
    resp.raise_for_status()
    return parse_feed_entries(resp.text)


def extract_listing_thread_links(
    html: str,
    base_url: str,
    *,
    include_pattern: str | re.Pattern | None = None,
    limit: int = 80,
) -> list[str]:
    """Extract unique thread-like links from a forum listing page."""
    pattern = re.compile(include_pattern, re.I) if isinstance(include_pattern, str) else include_pattern
    soup = BeautifulSoup(str(html or ""), "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = _norm_url(urllib.parse.urljoin(base_url, str(node.get("href") or "")))
        if not href or href in seen:
            continue
        if pattern and not pattern.search(href):
            continue
        seen.add(href)
        out.append(href)
        if len(out) >= limit:
            break
    return out


def fetch_listing_thread_links(
    listing_url: str,
    *,
    timeout: int = 15,
    include_pattern: str | re.Pattern | None = None,
    limit: int = 80,
) -> list[str]:
    session = requests.Session()
    resp = _get(session, listing_url, timeout)
    resp.raise_for_status()
    return extract_listing_thread_links(
        resp.text,
        str(resp.url),
        include_pattern=include_pattern,
        limit=limit,
    )

def merged_candidate_urls(result: dict) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in ("feed_urls", "sitemap_urls", "crawl_urls"):
        for url in result.get(key, []) or []:
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out
