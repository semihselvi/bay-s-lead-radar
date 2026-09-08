from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests


_EXA_RECOVERABLE_STATUS = {402, 429}
_TAVILY_RECOVERABLE_STATUS = {429, 432, 433}
_SITE_RE = re.compile(r"\bsite:([a-z0-9.-]+)(?:/[^\s)]*)?", re.I)


class ProviderRecoverableError(RuntimeError):
    """Quota/rate-limit condition where the next provider may be used safely."""


def _lookback_days(lane: str) -> int:
    env_name = "HOME_RADAR_LOOKBACK_DAYS" if lane == "home" else "ABROAD_RADAR_LOOKBACK_DAYS"
    try:
        return max(1, min(int(os.getenv(env_name, "7")), 90))
    except ValueError:
        return 7


def _fallback_result_limit() -> int:
    try:
        return max(1, min(int(os.getenv("RADAR_FALLBACK_MAX_RESULTS", "5")), 10))
    except ValueError:
        return 5


def _fallback_query_limit() -> int:
    try:
        return max(1, min(int(os.getenv("RADAR_FALLBACK_QUERY_LIMIT", "2")), 10))
    except ValueError:
        return 2


def _configured_query_count(lane: str) -> int:
    env_name = "HOME_RADAR_QUERY_LIMIT" if lane == "home" else "ABROAD_RADAR_QUERY_LIMIT"
    try:
        return max(1, min(int(os.getenv(env_name, "10")), 50))
    except ValueError:
        return 10


def _provider_query(query: str) -> tuple[str, list[str]]:
    domains: list[str] = []
    for match in _SITE_RE.finditer(query):
        domain = match.group(1).lower().removeprefix("www.")
        if domain and domain not in domains:
            domains.append(domain)
    cleaned = _SITE_RE.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query, domains


def _response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    return str(payload)[:300]


def exa_search(profile: str, query: str, lane: str) -> list[dict]:
    key = os.getenv("EXA_API_KEY", "").strip()
    if not key:
        raise ProviderRecoverableError("EXA_API_KEY missing")

    clean_query, domains = _provider_query(query)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_lookback_days(lane))
    payload: dict[str, Any] = {
        "query": clean_query,
        "type": "auto",
        "numResults": _fallback_result_limit(),
        "startPublishedDate": cutoff.strftime("%Y-%m-%dT00:00:00.000Z"),
        "contents": {"text": True},
    }
    if domains:
        payload["includeDomains"] = domains

    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Exa network error: {exc}") from exc

    if response.status_code in _EXA_RECOVERABLE_STATUS:
        detail = _response_detail(response)
        if response.status_code == 402 and "invalid api key" in detail.casefold():
            raise RuntimeError(f"Exa HTTP 402: {detail}")
        raise ProviderRecoverableError(f"Exa HTTP {response.status_code}: {detail}")
    if response.status_code != 200:
        raise RuntimeError(f"Exa HTTP {response.status_code}: {_response_detail(response)}")

    rows = []
    for item in response.json().get("results", []) or []:
        rows.append({
            "source": "Exa",
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "text": item.get("text", ""),
            "published": item.get("publishedDate", ""),
            "author": item.get("author", "") or "",
            "discovery_query": query,
        })
    print(f"FALLBACK_EXA_OK lane={lane} profile={profile} results={len(rows)} query={query!r}")
    return rows


def tavily_search(profile: str, query: str, lane: str) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise ProviderRecoverableError("TAVILY_API_KEY missing")

    clean_query, domains = _provider_query(query)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_lookback_days(lane))
    payload: dict[str, Any] = {
        "query": clean_query,
        "search_depth": "basic",
        "max_results": _fallback_result_limit(),
        "topic": "general",
        "start_date": cutoff.date().isoformat(),
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    if domains:
        payload["include_domains"] = domains

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Tavily network error: {exc}") from exc

    if response.status_code in _TAVILY_RECOVERABLE_STATUS:
        raise ProviderRecoverableError(
            f"Tavily HTTP {response.status_code}: {_response_detail(response)}"
        )
    if response.status_code != 200:
        raise RuntimeError(f"Tavily HTTP {response.status_code}: {_response_detail(response)}")

    rows = []
    for item in response.json().get("results", []) or []:
        rows.append({
            "source": "Tavily",
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "text": item.get("content", ""),
            "published": item.get("published_date", "") or "",
            "author": "",
            "discovery_query": query,
        })
    print(f"FALLBACK_TAVILY_OK lane={lane} profile={profile} results={len(rows)} query={query!r}")
    return rows


class FallbackProviderChain:
    def __init__(
        self,
        lane: str,
        postprocess: Callable[[str, list[dict]], list[dict]] | None = None,
        providers: list[tuple[str, Callable[[str, str, str], list[dict]]]] | None = None,
    ) -> None:
        self.lane = lane
        self.postprocess = postprocess
        self.providers = providers or [("exa", exa_search), ("tavily", tavily_search)]
        self.disabled: set[str] = set()
        self.degraded_logged = False
        self.query_index = 0
        self.query_budget = _fallback_query_limit()
        self.query_count = _configured_query_count(lane)
        slot = int(datetime.now(timezone.utc).timestamp() // (6 * 3600))
        self.window_start = (slot * self.query_budget) % self.query_count

    def _query_selected(self, index: int) -> bool:
        if self.query_budget >= self.query_count:
            return True
        selected = {(self.window_start + i) % self.query_count for i in range(self.query_budget)}
        return index % self.query_count in selected

    def __call__(self, profile: str, query: str) -> list[dict]:
        index = self.query_index
        self.query_index += 1
        if not self._query_selected(index):
            print(
                f"FALLBACK_QUERY_SKIPPED lane={self.lane} profile={profile} "
                f"index={index} budget={self.query_budget}/{self.query_count}"
            )
            return []

        for name, search_fn in self.providers:
            if name in self.disabled:
                continue
            try:
                rows = search_fn(profile, query, self.lane)
            except ProviderRecoverableError as exc:
                self.disabled.add(name)
                print(
                    f"SEARCH_PROVIDER_SKIPPED lane={self.lane} provider={name} "
                    f"reason={exc} action=try_next_provider"
                )
                continue
            if self.postprocess:
                rows = self.postprocess(profile, rows)
            return rows

        if not self.degraded_logged:
            self.degraded_logged = True
            print(
                f"SEARCH_FALLBACK_EXHAUSTED lane={self.lane} "
                "workflow_status=degraded_not_failed"
            )
        return []
