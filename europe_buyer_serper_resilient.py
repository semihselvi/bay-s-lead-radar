from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

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


def run() -> list[dict]:
    home_profile = os.getenv("HOME_RADAR_PROFILE", "").strip()
    abroad_profile = os.getenv("ABROAD_RADAR_PROFILE", "").strip()

    if home_profile:
        import europe_home_buyer_radar as app

        fallback = FallbackProviderChain("home", postprocess=_home_postprocess(app))
        app.serper_search = resilient_serper(app.serper_search, "home", fallback=fallback)
        return app.run()

    if abroad_profile:
        # Keep the existing source-verification layer. It calls the original search
        # function through this module-level reference. Fallback rows therefore pass
        # through the same Reddit permalink verification/hypothetical guards.
        import europe_abroad_buyer_radar_verified as app

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
