from __future__ import annotations

import re

import nc_v5_batch_quality_guard as batch_guard

radar = batch_guard.radar

# Human-reviewed false positive: "Ищу дом ... на 1 день" is an explicit
# short-term rental request, not a buy/rent ambiguity worth qualifying.
_EXTRA_SHORT_STAY = (
    r"(?:"
    r"\bна\s+\d+\s+(?:день|дня|дней|сутки|суток|ночь|ночи|ночей)\b|"
    r"\bна\s+сутки\b|\bна\s+один\s+день\b"
    r")"
)
radar.TG_SHORT_STAY_RE = re.compile(
    rf"(?:{radar.TG_SHORT_STAY_RE.pattern}|{_EXTRA_SHORT_STAY})",
    re.I | re.S,
)

# Import the existing diagnostic wrapper only after all quality patches so its
# reject-reason instrumentation sees the same production rules.
import nc_v5_diagnostic_runner as diagnostics  # noqa: E402,F401


# ---------------------------------------------------------------------------
# PURCHASE-ONLY ALERT MODE
# ---------------------------------------------------------------------------
# Semih currently wants actionable property BUYERS only. Rental, roommate,
# shared-rental and buy/rent-ambiguous demand may remain in Firestore for later
# analysis, but it must not reach Telegram or count as an actionable alert.
PURCHASE_ONLY_VERSION = "5.10-purchase-only-alerts"
radar.VERSION = PURCHASE_ONLY_VERSION
radar.v53.VERSION = PURCHASE_ONLY_VERSION
radar.v53.v52.VERSION = PURCHASE_ONLY_VERSION
radar.v53.gate.VERSION = PURCHASE_ONLY_VERSION
radar.v5.VERSION = PURCHASE_ONLY_VERSION


def purchase_only_lead(lead: dict):
    """Return a final verified purchase lead, otherwise None.

    The final production gate already rejects explicit rent/short-stay/supply.
    We additionally reject the old qualification lane because "looking for a
    flat/villa" without an explicit purchase signal is not useful right now.
    """
    refined = radar.v53.gate.refine_telegram_property_buyer(dict(lead))
    if refined is None:
        return None
    if refined.get("buyer_signal") == "needs_purchase_confirmation":
        return None
    return refined


_original_tg_scan = radar.core.telegram_buyer_scan


async def telegram_buyer_scan_purchase_only(db_client, started):
    result = await _original_tg_scan(db_client, started)
    filtered = []
    for lead in result.get("new_leads") or []:
        refined = purchase_only_lead(lead)
        if refined is None:
            print(
                "PURCHASE_ONLY_SKIP",
                f"author={lead.get('author','')!r}",
                f"group={lead.get('group','')!r}",
            )
            continue
        filtered.append(refined)

    out = dict(result)
    out["new_leads"] = filtered
    out["hot_warm"] = len(filtered)
    return out


radar.core.telegram_buyer_scan = telegram_buyer_scan_purchase_only


_original_backfill = radar.v5.backfill_unnotified_telegram


def backfill_purchase_only(db_client, started):
    filtered = []
    for lead in _original_backfill(db_client, started):
        refined = purchase_only_lead(lead)
        if refined is not None:
            filtered.append(refined)
        else:
            print(
                "PURCHASE_ONLY_RECOVERY_SKIP",
                f"author={lead.get('author','')!r}",
                f"group={lead.get('group','')!r}",
            )
    return filtered


radar.v5.backfill_unnotified_telegram = backfill_purchase_only


_original_notify = radar.v5.notify_telegram_lead


def notify_purchase_only(lead: dict, prefix: str = "NEW") -> bool:
    refined = purchase_only_lead(lead)
    if refined is None:
        print(
            "PURCHASE_ONLY_NOTIFY_BLOCKED",
            f"prefix={prefix}",
            f"author={lead.get('author','')!r}",
        )
        return False
    return _original_notify(refined, prefix)


radar.v5.notify_telegram_lead = notify_purchase_only


if __name__ == "__main__":
    radar.main()
