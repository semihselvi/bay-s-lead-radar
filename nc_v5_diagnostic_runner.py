from __future__ import annotations

import re

import main_v5_5 as radar

# Russian users spell Arabköy in several declined/transliterated forms
# (Арабкёй / Арабкёе). Production runs use this wrapper, so normalize that
# locality before classification without broadening generic buyer intent.
radar.TG_LOCALITY_RE = re.compile(
    radar.TG_LOCALITY_RE.pattern + r"|\bарабк[её](?:й|е)?\b",
    re.I,
)

_tg_seen = 0
_tg_limit = 12
_web_seen = 0
_web_limit = 12
_original_tg = radar.v53.gate.refine_telegram_property_buyer
_original_web = radar.v5.classify_web


def _tg_reason(lead):
    text = str(lead.get("message") or "")
    author = str(lead.get("author") or "").strip()
    if radar.TG_BOT_AUTHOR_RE.search(author):
        return "bot_author"
    if radar.TG_SERVICE_REQUEST_RE.search(text):
        return "service_request"
    if radar.TG_STRONG_SUPPLY_RE.search(text):
        return "strong_supply"
    if radar.v53.gate.TG_SUPPLY_RE.search(text):
        return "supply"
    if radar.TG_SHORT_STAY_RE.search(text):
        return "short_stay"
    if radar.v53.gate.TG_RENT_RE.search(text):
        return "rental"
    if radar._likely_monthly_scale(text):
        return "likely_rental_amount"
    if not radar.v53.gate.TG_PROPERTY_RE.search(text):
        return "no_property"
    if not radar.v53.TG_TERSE_DEMAND_RE.search(text) and not radar.v53.gate.TG_SELF_BUY_RE.search(text) and not radar.v53.gate.TG_CONSIDERATION_RE.search(text):
        return "no_final_buyer_voice"
    if radar.v53.TG_TERSE_DEMAND_RE.search(text) and not radar.TG_PURCHASE_QUALIFIER_RE.search(text):
        if radar._specific_ambiguous_property_demand(text):
            return "qualification_candidate"
        return "terse_without_purchase_qualifier"
    return "inherited_gate_reject"


def diagnostic_refine(lead):
    global _tg_seen
    result = _original_tg(lead)
    if result is None and _tg_seen < _tg_limit:
        _tg_seen += 1
        text = " ".join(str(lead.get("message") or "").split())[:420]
        group = str(lead.get("group") or "")[:90]
        print(f"V5_BUYER_REJECT_SAMPLE n={_tg_seen} reason={_tg_reason(lead)} group={group!r} text={text!r}")
    return result


def _web_reason(item):
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    raw = str(item.get("text") or "")
    hard = f"{title} {raw[:3200]}"
    if radar._web_listing_url(url):
        return "listing_url"
    if radar._WEB_RENTAL_RE.search(hard):
        return "rental_copy"
    if radar._WEB_LISTING_RE.search(hard):
        return "listing_copy"

    primary = dict(item)
    primary["text"] = raw[:2600]
    blob = radar.v5._blob(primary)
    low = blob.casefold()
    if not radar.v5.NORTH_RE.search(blob):
        query = str(item.get("_search_query") or "")
        if not (radar.v5.NORTH_RE.search(query) and radar._WEAK_NORTH_CUE.search(blob)):
            return "no_north_context"
    if any(term in low for term in radar.v5.NEGATIVE_PATTERNS):
        return "negative_or_past_buyer"
    recent, has_date = radar.v5._published_recent(primary)
    if not recent:
        return "stale"
    direct = sum(bool(p.search(blob)) for p in radar.v5.DIRECT_PATTERNS)
    warm = sum(bool(p.search(blob)) for p in radar.v5.WARM_PATTERNS)
    supply = sum(term in low for term in radar.v5.SUPPLY_PATTERNS)
    if supply >= 2 and direct == 0:
        return "supply"
    if supply >= 3:
        return "strong_supply"
    if direct == 0 and warm == 0:
        return "no_buyer_or_research_intent"
    if not radar.v5.PROPERTY_RE.search(blob) and direct == 0:
        return "no_property_context"
    if not has_date and direct == 0:
        return "undated_research_only"
    return "strict_classifier"


def diagnostic_web(item):
    global _web_seen
    result = _original_web(item)
    if result is None and _web_seen < _web_limit:
        _web_seen += 1
        title = " ".join(str(item.get("title") or "").split())[:180]
        url = str(item.get("url") or "")[:220]
        query = str(item.get("_search_query") or "")[:150]
        print(
            f"V5_WEB_REJECT_SAMPLE n={_web_seen} reason={_web_reason(item)} "
            f"query={query!r} title={title!r} url={url!r}"
        )
    return result


radar.v53.gate.refine_telegram_property_buyer = diagnostic_refine
radar.v5.classify_web = diagnostic_web


if __name__ == "__main__":
    radar.main()
