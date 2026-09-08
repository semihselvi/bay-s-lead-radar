from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


_CREDIT_ERROR_MARKERS = (
    "serper http 402",
    "serper_http_402",
    "not enough credits",
    "insufficient credits",
)


def is_serper_credit_error(error: BaseException | str) -> bool:
    text = str(error or "").casefold()
    return any(marker in text for marker in _CREDIT_ERROR_MARKERS)


def resilient_serper(original: Callable[..., list[dict]], lane: str) -> Callable[..., list[dict]]:
    """Disable Serper for the rest of one process after a credit-exhaustion response.

    Scheduled radars should degrade to an empty discovery result instead of failing
    every GitHub Actions job when the external search quota is exhausted. Other
    errors still raise normally so real code/network failures remain visible.
    """
    disabled = False

    def wrapped(*args: Any, **kwargs: Any) -> list[dict]:
        nonlocal disabled
        if disabled:
            print(f"SERPER_SKIPPED lane={lane} reason=credits_exhausted_for_run")
            return []
        try:
            return original(*args, **kwargs)
        except RuntimeError as exc:
            if not is_serper_credit_error(exc):
                raise
            disabled = True
            print(
                f"SERPER_CREDITS_EXHAUSTED lane={lane} action=disable_for_run "
                "workflow_status=degraded_not_failed"
            )
            return []

    return wrapped


def run() -> list[dict]:
    home_profile = os.getenv("HOME_RADAR_PROFILE", "").strip()
    abroad_profile = os.getenv("ABROAD_RADAR_PROFILE", "").strip()

    if home_profile:
        import europe_home_buyer_radar as app

        app.serper_search = resilient_serper(app.serper_search, "home")
        return app.run()

    if abroad_profile:
        # Keep the existing source-verification layer. It calls the original
        # Serper function through this module-level reference, so wrapping that
        # reference preserves all Reddit/source quality checks.
        import europe_abroad_buyer_radar_verified as app

        app._ORIGINAL_SERPER = resilient_serper(app._ORIGINAL_SERPER, "abroad")
        return app.run()

    raise SystemExit("Set HOME_RADAR_PROFILE or ABROAD_RADAR_PROFILE")


if __name__ == "__main__":
    run()
