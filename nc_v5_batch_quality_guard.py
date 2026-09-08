from __future__ import annotations

import re

import main_v5_5 as radar

VERSION = "5.9-nonproperty-and-semantic-dedupe"
radar.VERSION = VERSION
radar.v53.VERSION = VERSION
radar.v53.v52.VERSION = VERSION
radar.v53.gate.VERSION = VERSION
radar.v5.VERSION = VERSION

# Flea-market/forum posts can contain both a North-Cyprus location and a property
# word as incidental context ("for a large apartment", "lying around at home").
# The object actually being sought is sometimes a household/school item. Those
# messages must never enter the property buyer or buy/rent qualification lanes.
TG_NON_PROPERTY_GOODS_RE = re.compile(
    r"(?:"
    r"\bробот[-\s]?пылесос\w*\b|\bпылесос\w*\b|\bшкольн\w*\s+форм\w*\b|"
    r"\bформ[ауые]\b.{0,45}\b(?:школ|сын|доч|ребен|ребён)\w*\b|"
    r"\bтелефон\w*\b|\bсмартфон\w*\b|\bноутбук\w*\b|\bкомпьютер\w*\b|"
    r"\bвелосипед\w*\b|\bколяск\w*\b|\bхолодильник\w*\b|\bстиральн\w*\s+машин\w*\b|"
    r"\bмебел\w*\b|\bдиван\w*\b|\bстол\w*\b|\bкресл\w*\b|\bтелевизор\w*\b|"
    r"\brobot\s+vacuum\b|\bschool\s+uniform\b|\bphone\b|\blaptop\b|\bbicycle\b|"
    r"\bokul\s+formas[ıi]\b|\brobot\s+s[üu]p[üu]rge\b"
    r")",
    re.I | re.S,
)

_RU_PROPERTY_OBJECT = (
    r"(?:недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|"
    r"дом(?:\b|ом\b|у\b|е\b)|участ\w*|земл\w*|жиль[её]\w*|"
    r"[0-6]\s*\+\s*[0-3]|caesar\s+resort|royal\s+sun(?:\s+elite)?|"
    r"grand\s+sapphire|four\s+seasons|riverside\s+life|isatis|elysium)"
)

# A genuine property purchase overrides the goods guard. Keep the purchase object
# close to the verb so an unrelated word such as Russian "дома" (at home) cannot
# turn "I will buy a school uniform" into a house buyer. Unit configs/projects
# are valid purchase objects too: "Куплю 1+1 в Royal Sun" is a real buyer.
TG_DIRECT_PROPERTY_PURCHASE_RE = re.compile(
    rf"(?:"
    rf"\bкуплю\b.{{0,110}}\b{_RU_PROPERTY_OBJECT}\b|"
    rf"\b(?:хочу|хотим|планирую|планируем|рассматриваю|рассматриваем)\b.{{0,70}}"
    rf"\b(?:купить|покупк\w*)\b(?:.{{0,100}}\b{_RU_PROPERTY_OBJECT}\b)?|"
    r"\b(?:looking|planning|want(?:ing)?|ready|considering)\b.{0,60}\b(?:buy|buying|purchase)\b"
    r".{0,90}\b(?:property|apartment|flat|house|villa|studio|land)\b|"
    r"\b(?:sat[ıi]n\s+almak|almak)\b.{0,80}\b(?:daire|ev|villa|arsa|gayrimenkul|konut)\b"
    r")",
    re.I | re.S,
)


def is_nonproperty_goods_request(text: str) -> bool:
    own = " ".join(str(text or "").split())
    return bool(TG_NON_PROPERTY_GOODS_RE.search(own) and not TG_DIRECT_PROPERTY_PURCHASE_RE.search(own))


_base_refine = radar.v53.gate.refine_telegram_property_buyer


def _safe_direct_property_fallback(lead: dict, text: str):
    if str(lead.get("market") or "") != "north_cyprus":
        return None
    if not TG_DIRECT_PROPERTY_PURCHASE_RE.search(text):
        return None
    if radar.TG_SERVICE_REQUEST_RE.search(text):
        return None
    if radar.TG_STRONG_SUPPLY_RE.search(text) or radar.v53.gate.TG_SUPPLY_RE.search(text):
        return None
    if radar.TG_SHORT_STAY_RE.search(text) or radar.v53.gate.TG_RENT_RE.search(text):
        return None

    out = dict(lead)
    out["classification"] = "HOT" if (radar.v5.BUDGET_RE.search(text) or radar.v5.TIME_RE.search(text)) else "WARM"
    out["buyer_signal"] = "self_purchase_object_verified"
    out["telegram_score"] = max(int(out.get("telegram_score") or 0), 72 if out["classification"] == "HOT" else 62)
    out["radar_version"] = VERSION
    return out


def refine_telegram_batch_guard(lead):
    text = str(lead.get("message") or "")
    if is_nonproperty_goods_request(text):
        return None
    result = _base_refine(lead)
    if result is not None:
        return result
    return _safe_direct_property_fallback(lead, text)


# Expose the patched final gate both where production calls it and where the
# existing regression suite calls the V5.5 helper directly.
radar.refine_telegram_v55 = refine_telegram_batch_guard
radar.v53.gate.refine_telegram_property_buyer = refine_telegram_batch_guard

# Same person often cross-posts the same request to several Telegram groups. Do
# not send the same request twice during one radar run. Returning True for a
# duplicate tells the existing main loop to mark that source message notified,
# preventing its backfill from resurfacing later in the same run.
_SEMANTIC_SEEN: dict[str, list[set[str]]] = {}


def _semantic_tokens(value: str) -> set[str]:
    text = str(value or "").casefold().replace("ё", "е")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^0-9a-zа-яçğıöşü+]+", " ", text, flags=re.I)
    stop = {
        "и", "в", "на", "с", "для", "или", "а", "но", "по", "от", "до", "у", "из",
        "the", "a", "an", "and", "or", "for", "in", "on", "to", "from",
    }
    return {tok for tok in text.split() if len(tok) >= 2 and tok not in stop}


def semantic_cross_group_duplicate(lead: dict) -> bool:
    author = str(lead.get("author") or "").strip().casefold()
    if not author or author in {"-", "unknown", "none"}:
        return False
    tokens = _semantic_tokens(lead.get("message") or "")
    if len(tokens) < 4:
        return False
    prior = _SEMANTIC_SEEN.setdefault(author, [])
    for seen in prior:
        union = tokens | seen
        if not union:
            continue
        similarity = len(tokens & seen) / len(union)
        containment = len(tokens & seen) / min(len(tokens), len(seen))
        if similarity >= 0.78 or containment >= 0.88:
            return True
    prior.append(tokens)
    return False


_base_notify = radar.v5.notify_telegram_lead


def notify_semantic_guard(lead: dict, prefix: str = "NEW") -> bool:
    if semantic_cross_group_duplicate(lead):
        print(
            "V5_SEMANTIC_DUPLICATE_SKIPPED",
            f"author={lead.get('author','')!r}",
            f"group={lead.get('group','')!r}",
        )
        return True
    return _base_notify(lead, prefix)


radar.v5.notify_telegram_lead = notify_semantic_guard


def main() -> None:
    radar.main()


if __name__ == "__main__":
    main()
