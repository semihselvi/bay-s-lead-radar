from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup


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

    return {"engine": engine, "posts": posts}
