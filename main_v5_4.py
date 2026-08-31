from __future__ import annotations

import re
from typing import Any

import main as core
import main_v5_3 as v53


VERSION = "5.4-signal-diagnostics"
v53.VERSION = VERSION
v53.v52.VERSION = VERSION
v53.gate.VERSION = VERSION
v53.gate.v5.VERSION = VERSION

# This version does not loosen the buyer gate. It exposes why promising-looking
# web/Telegram candidates are being rejected so the next change can be based on
# real messages rather than guesses.

_WEB_LOG_LIMIT = 16
_TG_LOG_LIMIT = 16
_web_logged = 0
_tg_logged = 0

BUY_HINT_RE = re.compile(
    r"(?:\bbuy\w*\b|\bpurchas\w*\b|\blooking\s+for\b|\bwant\w*\b|"
    r"\bкуп\w*\b|\bищ\w*\b|\bпокуп\w*\b|\bприобр\w*\b|"
    r"\bkaufen\b|\bkauf\b|\bsuche\b|\bsuchen\b|"
    r"\bkupi\w*\b|\bszuk\w*\b|\bsatın\s+al\w*\b|\barıyorum\b)",
    re.I,
)


def _clip(text: str, n: int = 360) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


# ---------------------------------------------------------------------------
# WEB diagnostics
# ---------------------------------------------------------------------------

_original_search = core.exa_search


def diagnostic_search(query: str, include_domains: list[str] | None = None):
    rows = _original_search(query, include_domains)
    for row in rows:
        row["_search_query"] = query
    return rows


core.exa_search = diagnostic_search

_original_classify_web = v53.gate.v5.classify_web


def _web_reject_reason(item: dict[str, Any]) -> tuple[str, dict[str, int | bool]]:
    v5 = v53.gate.v5
    text = v5._blob(item)
    low = text.casefold()
    north = bool(v5.NORTH_RE.search(text))
    negative = any(term in low for term in v5.NEGATIVE_PATTERNS)
    recent, has_date = v5._published_recent(item)
    direct_hits = sum(bool(p.search(text)) for p in v5.DIRECT_PATTERNS)
    warm_hits = sum(bool(p.search(text)) for p in v5.WARM_PATTERNS)
    supply_hits = sum(term in low for term in v5.SUPPLY_PATTERNS)
    property_context = bool(v5.PROPERTY_RE.search(text))

    stats: dict[str, int | bool] = {
        "north": north,
        "direct": direct_hits,
        "warm": warm_hits,
        "supply": supply_hits,
        "property": property_context,
        "date": has_date,
    }

    if not north:
        return "no_north_context", stats
    if negative:
        return "negative_status", stats
    if not recent:
        return "stale", stats
    if supply_hits >= 2 and direct_hits == 0:
        return "supply_without_direct_buyer", stats
    if supply_hits >= 3:
        return "heavy_supply_copy", stats
    if direct_hits == 0 and warm_hits == 0:
        return "no_buyer_intent_pattern", stats
    if not property_context and direct_hits == 0:
        return "no_property_context", stats
    if not has_date and direct_hits == 0:
        return "undated_consideration_only", stats
    return "other", stats


def diagnostic_classify_web(item: dict[str, Any]):
    global _web_logged
    result = _original_classify_web(item)
    if result is not None:
        return result

    if _web_logged >= _WEB_LOG_LIMIT:
        return None

    text = v53.gate.v5._blob(item)
    if not (v53.gate.v5.NORTH_RE.search(text) or BUY_HINT_RE.search(text)):
        return None

    reason, stats = _web_reject_reason(item)
    _web_logged += 1
    print(
        "V5.4 WEB_REJECT "
        f"#{_web_logged} reason={reason} stats={stats} "
        f"query={_clip(item.get('_search_query', ''), 120)} | "
        f"title={_clip(item.get('title', ''), 180)} | "
        f"snippet={_clip(item.get('text', ''), 320)} | "
        f"url={item.get('url', '')}"
    )
    return None


v53.gate.v5.classify_web = diagnostic_classify_web


# ---------------------------------------------------------------------------
# Telegram diagnostics
# ---------------------------------------------------------------------------

_original_refine = v53.gate.refine_telegram_property_buyer


def _tg_reject_reason(text: str) -> str:
    gate = v53.gate
    if not gate.TG_PROPERTY_RE.search(text):
        return "no_property"

    self_buy = bool(gate.TG_SELF_BUY_RE.search(text))
    consideration = bool(gate.TG_CONSIDERATION_RE.search(text))
    terse = bool(v53.TG_TERSE_DEMAND_RE.search(text))
    rent = bool(gate.TG_RENT_RE.search(text))
    supply = bool(gate.TG_SUPPLY_RE.search(text))
    purchase_budget = v53._purchase_scale_budget(text)

    if rent and not self_buy:
        return "rent_only"
    if supply and not self_buy:
        return "seller_listing"
    if self_buy:
        return "strict_self_buy_unexpected_reject"
    if consideration:
        return "consideration_blocked"
    if terse and not purchase_budget:
        return "terse_without_purchase_scale_budget"
    if terse:
        return "terse_other"
    return "no_final_buyer_signal"


def diagnostic_refine(lead: dict[str, Any]):
    global _tg_logged
    result = _original_refine(lead)
    if result is not None:
        return result

    if _tg_logged < _TG_LOG_LIMIT:
        text = str(lead.get("message") or "")
        _tg_logged += 1
        print(
            "V5.4 TG_REJECT "
            f"#{_tg_logged} reason={_tg_reject_reason(text)} "
            f"group={_clip(lead.get('group', ''), 100)} | "
            f"message={_clip(text, 420)} | "
            f"url={lead.get('url', '')}"
        )
    return None


v53.gate.refine_telegram_property_buyer = diagnostic_refine


def main() -> None:
    v53.gate.v5.main()


if __name__ == "__main__":
    main()
