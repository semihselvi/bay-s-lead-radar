from __future__ import annotations

import asyncio
import os
from typing import Any

_FETCH_BUDGET = int(os.getenv("RADAR_CRAWL4AI_RUN_BUDGET", "40"))
_PER_CALL = int(os.getenv("RADAR_CRAWL4AI_PER_CALL", "4"))
_USED = 0
_CACHE: dict[str, str] = {}


def _markdown_text(result: Any) -> str:
    md = getattr(result, "markdown", None)
    if isinstance(md, str):
        return md
    if md is not None:
        for attr in ("fit_markdown", "raw_markdown", "markdown_with_citations"):
            value = getattr(md, attr, None)
            if isinstance(value, str) and value.strip():
                return value
    for attr in ("cleaned_html", "html"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return ""


async def _crawl(urls: list[str]) -> dict[str, str]:
    from crawl4ai import AsyncWebCrawler

    out: dict[str, str] = {}
    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun_many(urls=urls)
        for url, result in zip(urls, results):
            if not getattr(result, "success", True):
                out[url] = ""
                continue
            text = _markdown_text(result)
            out[url] = " ".join(text.split())[:12000]
    return out


def enrich_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fetch a small number of search-result URLs with Crawl4AI.

    This is deliberately budgeted. It is used only when the search snippet
    itself is too weak to establish North-Cyprus/buyer context.
    """
    global _USED

    stats = {"requested": 0, "fetched": 0, "cache": 0, "failed": 0}
    if not rows or _USED >= _FETCH_BUDGET:
        return rows, stats

    candidates: list[str] = []
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        if url in _CACHE:
            stats["cache"] += 1
            continue
        candidates.append(url)
        if len(candidates) >= min(_PER_CALL, _FETCH_BUDGET - _USED):
            break

    stats["requested"] = len(candidates)
    if candidates:
        try:
            fetched = asyncio.run(_crawl(candidates))
        except Exception:
            fetched = {url: "" for url in candidates}

        for url in candidates:
            text = str(fetched.get(url) or "")
            _CACHE[url] = text
            _USED += 1
            if text:
                stats["fetched"] += 1
            else:
                stats["failed"] += 1

    enriched = []
    for row in rows:
        item = dict(row)
        url = str(item.get("url") or "").strip()
        page_text = _CACHE.get(url, "")
        if page_text:
            item["text"] = f"{item.get('text','')} {page_text[:10000]}".strip()
            item["source"] = f"{item.get('source') or 'Web'} + Crawl4AI"
            item["_crawl4ai_enriched"] = True
        enriched.append(item)
    return enriched, stats
