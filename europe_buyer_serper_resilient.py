from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from europe_buyer_search_fallback import (
    FallbackProviderChain,
    ProviderRecoverableError,
    exa_search,
    tavily_search,
)


_CREDIT_ERROR_MARKERS = (
    "serper http 402",
    "serper_http_402",
    "not enough credits",
    "insufficient credits",
)

_GLOBAL_DISCOVERY_DOMAINS = {
    "reddit.com",
    "old.reddit.com",
    "expat.com",
    "expatforum.com",
    "internations.org",
    "nomadgate.com",
    "bogleheads.org",
    "moneysavingexpert.com",
}

_REDDIT_COUNTRY_PATHS = {
    "germany_abroad": ("/r/germany/",),
    "netherlands_abroad": ("/r/netherlands/",),
    "belgium_abroad": ("/r/belgium/",),
    "switzerland_abroad": ("/r/switzerland/",),
}

_HOME_REDDIT_COUNTRY_PATHS = {
    "germany_home": ("/r/germany/", "/r/berlin/", "/r/munich/"),
    "netherlands_home": ("/r/netherlandshousing/", "/r/netherlands/", "/r/amsterdam/"),
    "belgium_home": ("/r/belgium/", "/r/brussels/"),
    "switzerland_home": ("/r/swisspersonalfinance/", "/r/switzerland/", "/r/askswitzerland/"),
}

_HOME_BRIDGE_DOMAINS = {
    "germany_home": {
        "gutefrage.net", "finanztip.de", "hausbau-forum.de", "wertpapier-forum.de", "wiwi-treff.de",
    },
    "netherlands_home": {"tweakers.net", "forum.fok.nl", "fok.nl", "investeerders.nl"},
    "belgium_home": {"pim.be", "bouwinfo.be"},
    "switzerland_home": {"englishforum.ch", "beobachter.ch"},
}

_PAST_PURCHASE_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\s+(?:have\s+)?(?:already\s+)?(?:bought|purchased)\b|"
    r"\b(?:already\s+bought|already\s+purchased|purchase\s+completed)\b|"
    r"\b(?:ich\s+habe|wir\s+haben)\b.{0,80}\bgekauft\b|"
    r"\b(?:ik\s+heb|wij\s+hebben|we\s+hebben)\b.{0,80}\bgekocht\b|"
    r"\bj['’]ai\s+achet[ée]\b|\bnous\s+avons\s+achet[ée]\b"
    r")",
    re.I | re.S,
)


def is_serper_credit_error(error: BaseException | str) -> bool:
    text = str(error or "").casefold()
    return any(marker in text for marker in _CREDIT_ERROR_MARKERS)


def resilient_serper(
    original: Callable[..., list[dict]],
    lane: str,
    fallback: Callable[..., list[dict]] | None = None,
) -> Callable[..., list[dict]]:
    """Use Serper normally, then switch the process to fallback providers on quota exhaustion.

    Only Serper credit exhaustion is swallowed. Other Serper failures still raise.
    Optional fallback providers may treat their own quota/rate-limit conditions as
    recoverable; configuration, HTTP 5xx, malformed requests and network failures remain
    visible failures.
    """
    disabled = False

    def wrapped(*args: Any, **kwargs: Any) -> list[dict]:
        nonlocal disabled
        if disabled:
            if fallback:
                return fallback(*args, **kwargs)
            print(f"SERPER_SKIPPED lane={lane} reason=credits_exhausted_for_run")
            return []
        try:
            return original(*args, **kwargs)
        except RuntimeError as exc:
            if not is_serper_credit_error(exc):
                raise
            disabled = True
            print(
                f"SERPER_CREDITS_EXHAUSTED lane={lane} action=switch_to_fallback "
                "workflow_status=degraded_not_failed"
            )
            if fallback:
                return fallback(*args, **kwargs)
            return []

    return wrapped


def _home_postprocess(app):
    def postprocess(profile: str, rows: list[dict]) -> list[dict]:
        out: list[dict] = []
        verified_count = 0
        dropped_count = 0
        for item in rows:
            url = str(item.get("url") or "")
            if not app.is_reddit_post(url):
                out.append(item)
                continue
            verified, reason = app.fetch_reddit_post(item)
            if verified is None:
                dropped_count += 1
                print(
                    "HOME_REDDIT_VERIFY_DROP",
                    f"profile={profile}",
                    f"reason={reason}",
                    f"url={url}",
                )
                continue
            verified_count += 1
            out.append(verified)
        if verified_count or dropped_count:
            print(
                "HOME_FALLBACK_REDDIT_VERIFY_SUMMARY",
                f"profile={profile}",
                f"verified={verified_count}",
                f"dropped={dropped_count}",
            )
        return out

    return postprocess


def strict_home_target_match(base, profile: str, item: dict, text: str) -> tuple[bool, bool]:
    """Verify that a HOME lead actually belongs to the requested country market.

    Search-query wording is discovery context, not person/location evidence. Global
    sources such as Expat.com and generic Reddit cannot inherit Germany/NL/BE/CH from
    the query. A matching country subreddit or clearly country-specific forum may act
    as a conservative bridge when the post text omits the country name.
    """
    spec = base.PROFILES[profile]
    if spec["target_re"].search(text):
        return True, True

    query = str(item.get("discovery_query") or "")
    if not base.query_targets_profile(profile, query):
        return False, False

    url = str(item.get("url") or "")
    domain = base.domain_of(url)
    try:
        path = urlsplit(url).path.casefold()
    except Exception:
        path = ""

    if domain in {"reddit.com", "old.reddit.com"} or domain.endswith(".reddit.com"):
        allowed_paths = _HOME_REDDIT_COUNTRY_PATHS.get(profile, ())
        return any(token in path for token in allowed_paths), False

    allowed_domains = _HOME_BRIDGE_DOMAINS.get(profile, set())
    bridge = any(domain == d or domain.endswith("." + d) for d in allowed_domains)
    return bridge, False


def is_past_purchase(text: str) -> bool:
    return bool(_PAST_PURCHASE_RE.search(str(text or "")))


def _patch_home_precision(app) -> None:
    original_classify = app.classify

    def classify(profile: str, item: dict):
        text = app.clean(f"{item.get('title','')} {item.get('text','')}")
        if is_past_purchase(text):
            return None, "past_purchase"

        spec = app.PROFILES[profile]
        if not spec["target_re"].search(text):
            matched, _explicit = strict_home_target_match(app, profile, item, text)
            if not matched:
                return None, "target_unverified"

        return original_classify(profile, item)

    app.classify = classify


def strict_abroad_audience_match(base, profile: str, item: dict, text: str) -> tuple[bool, bool]:
    """Require real evidence that the poster belongs to the requested resident market.

    A search query containing Germany/Belgium/etc. is discovery context, not evidence
    about the person. Global communities such as Expat.com and generic Reddit therefore
    require an explicit residence/nationality statement in the result text. Country-
    specific forums and matching country subreddits may still act as a conservative
    context bridge.
    """
    spec = base.PROFILES[profile]
    if profile == "golden_visa":
        return True, True

    explicit = bool(spec["audience_re"].search(text))
    if explicit:
        return True, True

    query = str(item.get("discovery_query") or "")
    if not spec["query_anchor"].search(query):
        return False, False

    url = str(item.get("url") or "")
    domain = base.domain_of(url)
    try:
        path = urlsplit(url).path.casefold()
    except Exception:
        path = ""

    if domain in {"reddit.com", "old.reddit.com"}:
        allowed_paths = _REDDIT_COUNTRY_PATHS.get(profile, ())
        if any(token in path for token in allowed_paths):
            return True, False
        return False, False

    bridge_domains = {
        d for d in spec["bridge_domains"]
        if d not in _GLOBAL_DISCOVERY_DOMAINS
    }
    bridge = any(domain == d or domain.endswith("." + d) for d in bridge_domains)
    return bridge, False


def _canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        host = parts.netloc.casefold().removeprefix("www.")
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.casefold() or "https", host, path, "", ""))
    except Exception:
        return raw.split("?", 1)[0].rstrip("/").casefold()


def cross_profile_abroad_lead_key(original_key, profile: str, lead: dict) -> str:
    """Deduplicate the same resident-buyer page across Germany/NL/BE/CH radars."""
    if profile == "golden_visa":
        return original_key(profile, lead)
    canonical = _canonical_url(lead.get("url", ""))
    if canonical:
        basis = f"abroad_resident|{canonical}"
    else:
        text = " ".join(str(lead.get("text") or "").casefold().split())[:320]
        basis = f"abroad_resident|{text}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _patch_abroad_precision(app) -> None:
    base = app.base
    original_key = base.lead_key

    def audience_match(profile: str, item: dict, text: str) -> tuple[bool, bool]:
        return strict_abroad_audience_match(base, profile, item, text)

    def lead_key(profile: str, lead: dict) -> str:
        return cross_profile_abroad_lead_key(original_key, profile, lead)

    base.audience_match = audience_match
    base.lead_key = lead_key


def run() -> list[dict]:
    home_profile = os.getenv("HOME_RADAR_PROFILE", "").strip()
    abroad_profile = os.getenv("ABROAD_RADAR_PROFILE", "").strip()

    if home_profile:
        import europe_home_buyer_radar as app

        _patch_home_precision(app)
        fallback = FallbackProviderChain("home", postprocess=_home_postprocess(app))
        app.serper_search = resilient_serper(app.serper_search, "home", fallback=fallback)
        return app.run()

    if abroad_profile:
        # Keep the existing source-verification layer. It calls the original search
        # function through this module-level reference. Fallback rows therefore pass
        # through the same Reddit permalink verification/hypothetical guards.
        import europe_abroad_buyer_radar_verified as app

        _patch_abroad_precision(app)
        fallback = FallbackProviderChain("abroad")
        app._ORIGINAL_SERPER = resilient_serper(
            app._ORIGINAL_SERPER,
            "abroad",
            fallback=fallback,
        )
        return app.run()

    raise SystemExit("Set HOME_RADAR_PROFILE or ABROAD_RADAR_PROFILE")


if __name__ == "__main__":
    run()
