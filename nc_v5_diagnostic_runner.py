from __future__ import annotations

import re

import main_v5_5 as radar

_seen = 0
_limit = 12
_original = radar.v53.gate.refine_telegram_property_buyer


def _reason(lead):
    text = str(lead.get("message") or "")
    author = str(lead.get("author") or "").strip()
    if radar.TG_BOT_AUTHOR_RE.search(author):
        return "bot_author"
    if radar.TG_STRONG_SUPPLY_RE.search(text):
        return "strong_supply"
    if radar.v53.gate.TG_SUPPLY_RE.search(text):
        return "supply"
    if radar.TG_SHORT_STAY_RE.search(text):
        return "short_stay"
    if radar.v53.gate.TG_RENT_RE.search(text):
        return "rental"
    if not radar.v53.gate.TG_PROPERTY_RE.search(text):
        return "no_property"
    if not radar.v53.TG_TERSE_DEMAND_RE.search(text) and not radar.v53.gate.TG_SELF_BUY_RE.search(text) and not radar.v53.gate.TG_CONSIDERATION_RE.search(text):
        return "no_final_buyer_voice"
    if radar.v53.TG_TERSE_DEMAND_RE.search(text) and not radar.TG_PURCHASE_QUALIFIER_RE.search(text):
        return "terse_without_purchase_qualifier"
    return "inherited_gate_reject"


def diagnostic_refine(lead):
    global _seen
    result = _original(lead)
    if result is None and _seen < _limit:
        _seen += 1
        text = " ".join(str(lead.get("message") or "").split())[:420]
        group = str(lead.get("group") or "")[:90]
        print(f"V5_BUYER_REJECT_SAMPLE n={_seen} reason={_reason(lead)} group={group!r} text={text!r}")
    return result


radar.v53.gate.refine_telegram_property_buyer = diagnostic_refine


if __name__ == "__main__":
    radar.main()
