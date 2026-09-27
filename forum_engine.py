from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

try:
    from forumscraper import extractor as _fs_extractor, outputs as _fs_outputs
except Exception:
    _fs_extractor = None
    _fs_outputs = None


FORUM_SIGNATURES = (
    ("xenforo", re.compile(r"(?:xenforo|data-xf-|class=[\"'][^\"']*message-body)", re.I)),
    ("phpbb", re.compile(r"(?:phpbb|class=[\"'][^\"']*postbody|viewtopic\.php\?f=)", re.I)),
    ("vbulletin", re.compile(r"(?:vbulletin|postbit|showthread\.php\?t=)", re.I)),
    ("invision", re.compile(r"(?:ipsType_richText|ipsComment|invision community)", re.I)),
    ("smf", re.compile(r"(?:simple machines|topic=\d+|class=[\"'][^\"']*post_wrapper)", re.I)),
    ("discourse", re.compile(r"(?:discourse|topic-post|data-post-id)", re.I)),
)

POST_SELECTORS = (
    "article.message",
    "article.topic-post",
    "div.post",
    "div.post_wrapper",
    "div.ipsComment",
    "li.ipsComment",
    "article[data-post-id]",
    "[id^='post_']",
    "[id^='post-']",
)

TEXT_SELECTORS = (
    ".message-body",
    ".bbWrapper",
    ".content",
    ".postbody",
    ".post_content",
    ".ipsType_richText",
    ".cooked",
    ".entry-content",
)

AUTHOR_SELECTORS = (
    ".username",
    ".author",
    ".message-name",
    ".ipsType_break",
    ".poster",
    "[itemprop='author']",
)

DATE_SELECTORS = (
    "time[datetime]",
    "[data-time]",
    "[data-timestamp]",
    "[itemprop='datePublished']",
    ".date",
    ".postdate",
)


def detect_forum_engine(html: str) -> str:
    raw = str(html or "")
    for name, pattern in FORUM_SIGNATURES:
        if pattern.search(raw):
            return name
    return "generic"


def _text(node: Any) -> str:
    if node is None:
        return ""
    try:
        return " ".join(node.get_text(" ", strip=True).split())
    except Exception:
        return ""


def _parse_dt(node: Any) -> str:
    if node is None:
        return ""
    for attr in ("datetime", "data-time", "data-timestamp", "content", "title"):
        value = str(node.get(attr) or "").strip() if hasattr(node, "get") else ""
        if not value:
            continue
        if value.isdigit():
            try:
                ts = int(value)
                if ts > 10_000_000_000:
                    ts //= 1000
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except Exception:
                pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return ""


def _first(node: Any, selectors: tuple[str, ...]) -> Any:
    for selector in selectors:
        found = node.select_one(selector)
        if found is not None:
            return found
    return None




def _clean_html_text(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        return " ".join(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True).split())
    except Exception:
        return " ".join(raw.split())


def _forumscraper_posts(html: str, url: str) -> dict[str, Any]:
    """Best-effort universal forum fallback using TUVIMEN/forumscraper.

    The already-downloaded HTML is supplied to avoid a second network request.
    Any parser failure is swallowed so the lightweight native parser remains
    the safe default.
    """
    if _fs_extractor is None or _fs_outputs is None or not url or not html:
        return {"engine": "", "posts": []}

    try:
        ex = _fs_extractor(
            requests={
                "timeout": 20,
                "retry": 0,
            }
        )
        result = ex.guess(
            url,
            html,
            output=_fs_outputs.data | _fs_outputs.threads,
            requests={"retry": 0},
        )
    except Exception:
        return {"engine": "", "posts": []}

    if not isinstance(result, dict):
        return {"engine": "", "posts": []}

    data = result.get("data") or {}
    threads = data.get("threads") or []
    if not threads:
        return {"engine": "", "posts": []}

    thread = threads[0] if isinstance(threads[0], dict) else {}
    format_version = str(thread.get("format_version") or "")
    engine = format_version.split("-", 1)[0] if format_version else "forumscraper"

    out: list[dict[str, Any]] = []
    for index, post in enumerate(thread.get("posts") or []):
        if not isinstance(post, dict):
            continue
        text = _clean_html_text(post.get("text") or "")
        if len(text) < 20:
            continue
        post_id = str(post.get("id") or "")
        author = str(post.get("user") or post.get("author") or "").strip()
        published = str(post.get("date") or post.get("published") or "").strip()
        stable = f"{url}|{post_id or index}|{text[:160]}"
        out.append({
            "post_id": post_id,
            "author": author,
            "published": published,
            "text": text,
            "fingerprint": hashlib.sha256(stable.encode("utf-8", "ignore")).hexdigest(),
        })
        if len(out) >= 120:
            break

    return {"engine": engine or "forumscraper", "posts": out}


def discover_forum_threads(
    root_url: str,
    *,
    limit: int = 40,
    timeout: int = 20,
) -> dict[str, Any]:
    """Discover public thread URLs from a supported forum root."""
    if _fs_extractor is None or _fs_outputs is None or not root_url:
        return {"engine": "", "threads": [], "error": "forumscraper_unavailable"}

    try:
        ex = _fs_extractor(requests={"timeout": timeout, "retry": 0})
        result = ex.guess(
            root_url,
            output=_fs_outputs.urls,
            requests={"retry": 0, "timeout": timeout},
            pages_max=1,
            pages_forums_max=3,
            pages_threads_max=max(1, min(int(limit), 80)),
            thread_pages_max=1,
        )
    except Exception as exc:
        return {"engine": "", "threads": [], "error": f"{type(exc).__name__}:{exc}"}

    if not isinstance(result, dict):
        return {"engine": "", "threads": [], "error": "no_result"}

    urls = result.get("urls") or {}
    raw_threads = urls.get("threads") or []
    seen: set[str] = set()
    threads: list[str] = []
    for value in raw_threads:
        url = str(value or "").strip()
        if not url or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        threads.append(url)
        if len(threads) >= max(1, int(limit)):
            break

    scraper = result.get("scraper")
    engine = scraper.__class__.__name__.casefold() if scraper is not None else ""
    if not engine:
        method = result.get("scraper-method")
        engine = getattr(method, "__qualname__", "") or getattr(method, "__name__", "") or "forumscraper"

    return {"engine": engine, "threads": threads, "error": ""}

def extract_forum_posts(html: str, url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    engine = detect_forum_engine(html)
    nodes: list[Any] = []
    seen_ids: set[int] = set()
    for selector in POST_SELECTORS:
        for node in soup.select(selector):
            ident = id(node)
            if ident in seen_ids:
                continue
            seen_ids.add(ident)
            nodes.append(node)

    # Some forums expose no obvious post wrapper. Keep a conservative article fallback.
    if not nodes:
        nodes = list(soup.select("article"))[:50]

    posts: list[dict[str, Any]] = []
    for index, node in enumerate(nodes[:80]):
        text_node = _first(node, TEXT_SELECTORS)
        text = _text(text_node or node)
        if len(text) < 20:
            continue

        author = _text(_first(node, AUTHOR_SELECTORS))
        dt_node = _first(node, DATE_SELECTORS)
        published = _parse_dt(dt_node)

        post_id = ""
        for attr in ("data-content", "data-post-id", "id"):
            raw = str(node.get(attr) or "").strip()
            if raw:
                post_id = raw
                break
        stable = f"{url}|{post_id or index}|{text[:160]}"
        posts.append({
            "post_id": post_id,
            "author": author,
            "published": published,
            "text": text,
            "fingerprint": hashlib.sha256(stable.encode("utf-8", "ignore")).hexdigest(),
        })

    # If the lightweight parser could not recover structured posts, try the
    # universal forum parser. This covers XenForo/phpBB/vBulletin/SMF/Invision
    # without maintaining site-specific selectors for each forum.
    if not posts:
        fallback = _forumscraper_posts(html, url)
        if fallback.get("posts"):
            return fallback

    return {"engine": engine, "posts": posts}
