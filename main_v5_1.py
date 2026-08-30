from __future__ import annotations

import re
from typing import Any

import main as core
import main_v5 as v5


VERSION = "5.1-property-buyer-gate"
v5.VERSION = VERSION

# GitHub Actions is consistently blocked/rate-limited by Reddit RSS. Keep Reddit
# coverage through Exa's reddit.com domain instead of spending time on 403/429s.
v5.REDDIT_QUERIES = []
v5.EXA_QUERIES = list(v5.EXA_QUERIES) + [
    ("North Cyprus Reddit looking to buy property apartment villa", ["reddit.com"]),
    ("Northern Cyprus Reddit considering buying property moving", ["reddit.com"]),
    ("Северный Кипр Reddit хочу купить недвижимость квартиру", ["reddit.com"]),
]


TG_PROPERTY_RE = re.compile(
    r"\b(?:real\s+estate|property|apartment|flat|house|villa|studio|home|land|plot|"
    r"immobilie|wohnung|haus|grundst(?:u|ü)ck|"
    r"недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|участ\w*|земл\w*|жиль[её]\w*|"
    r"nieruchomo(?:ść|sci|ści)\w*|mieszkan\w*|apartament\w*|will\w*|dom\w*|działk\w*|dzialk\w*|"
    r"gayrimenkul|emlak|daire|konut|arsa|ev|villa)\b",
    re.I,
)

TG_DIRECT_BUY_RE = re.compile(
    r"(?:\blooking\s+to\s+buy\b|\bwant\s+to\s+buy\b|\bplanning\s+to\s+buy\b|"
    r"\bready\s+to\s+buy\b|\bcash\s+buyer\b|\bseeking\s+to\s+buy\b|"
    r"\binterested\s+in\s+buying\b|\bwant\s+to\s+purchase\b|"
    r"\bхочу\s+купить\b|\bхотим\s+купить\b|\bготов\w*\s+купить\b|"
    r"\bпланир\w*\s+купить\b|\bприобрест\w*\b|\bпокупк\w*\b|"
    r"\bкуплю\b|"
    r"\b(?:ich|wir)\b.{0,50}\b(?:kaufen|erwerben)\b|\bzum\s+kauf\b|\bzu\s+kaufen\b|"
    r"\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,80}\b(?:kupić|kupic|zakupić|zakupic)\b|"
    r"\bdo\s+kupienia\b|"
    r"\bsatın\s+al(?:mak|acağım|acagim|mak\s+istiyorum|mak\s+istiyoruz)?\b|"
    r"\balmak\s+istiyorum\b|\balmak\s+istiyoruz\b|\balıcıyım\b)",
    re.I | re.S,
)

TG_CONSIDERATION_RE = re.compile(
    r"(?:\bwhere\s+should\s+(?:i|we)\s+buy\b|\bwhich\s+(?:area|region).{0,80}\bbuy\b|"
    r"\bcan\s+foreigners?\s+buy\b|\bmortgage\b|"
    r"\bгде\s+(?:лучше\s+)?купить\b|\bстоит\s+ли\s+покупать\b|\bкак\s+купить\b|"
    r"\bипотек\w*\b|\bрассрочк\w*\b|\bпервоначальн\w*\s+взнос\w*\b|"
    r"\bwelche\s+region.{0,80}\bkaufen\b|\bwo\s+sollte\s+ich\s+kaufen\b|"
    r"\bgdzie\s+kupi(?:ć|c)\b|\bczy\s+cudzoziemiec.{0,60}\bkupi(?:ć|c)\b|"
    r"\bhangi\s+bölge.{0,80}\b(?:satın\s+al|almak)\b|\bkonut\s+kredisi\b)",
    re.I | re.S,
)

TG_RENT_RE = re.compile(
    r"(?:\bfor\s+rent\b|\blooking\s+to\s+rent\b|\brental\b|\bmonthly\b|\bper\s+month\b|"
    r"\bаренд\w*\b|\bсниму\b|\bснять\b|\bсда[её]тся\b|\bв\s+месяц\b|\bпосуточ\w*\b|"
    r"\bkiralık\b|\baylık\b|\bgünlük\b|\bmieten\b|\bmiete\b|\bwynajem\w*\b|\bwynająć\b)",
    re.I,
)


# Replace the permissive core buyer triggers for this V5 test only. In particular,
# generic words such as "budget" or bare "куплю" no longer create a real-estate
# lead unless the message also contains real-estate context and passes the V5 gate.
core.TG_BUY = [
    r"\blooking to buy\b",
    r"\bwant to buy\b",
    r"\bplanning to buy\b",
    r"\bready to buy\b",
    r"\bcash buyer\b",
    r"\bseeking to buy\b",
    r"\binterested in buying\b",
    r"\bхочу купить\b",
    r"\bхотим купить\b",
    r"\bготов\w* купить\b",
    r"\bпланир\w* купить\b",
    r"\bприобрест\w*\b",
    r"\bкуплю\b",
    r"\bsuche\b.{0,100}\b(?:zum kauf|zu kaufen)\b",
    r"\b(?:ich|wir)\b.{0,80}\b(?:kaufen|erwerben)\b",
    r"\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,100}\b(?:kupić|kupic|zakupić|zakupic)\b",
    r"\bsatın almak\b",
    r"\balmak istiyorum\b",
    r"\balmak istiyoruz\b",
]

core.TG_WEAK = [
    r"\bwhere should i buy\b",
    r"\bwhich area\b",
    r"\bmortgage\b",
    r"\bгде купить\b",
    r"\bстоит ли покупать\b",
    r"\bипотек\w*\b",
    r"\bрассрочк\w*\b",
    r"\bwelche region\b",
    r"\bgdzie kupi(?:ć|c)\b",
    r"\bhangi bölge\b",
    r"\bkonut kredisi\b",
]

core.TG_CONTEXT = [
    r"\bwhere should i buy\b",
    r"\bwhich (?:area|region)\b",
    r"\bcan foreigners? buy\b",
    r"\bгде (?:лучше )?купить\b",
    r"\bстоит ли покупать\b",
    r"\bкак купить\b",
    r"\bипотек\w*\b",
    r"\bрассрочк\w*\b",
    r"\bпервоначальн\w* взнос\w*\b",
    r"\bwelche region\b",
    r"\bwo sollte ich kaufen\b",
    r"\bgdzie kupi(?:ć|c)\b",
    r"\bhangi bölge\b",
    r"\bkonut kredisi\b",
]


def refine_telegram_property_buyer(lead: dict[str, Any]) -> dict[str, Any] | None:
    if str(lead.get("market") or "") != "north_cyprus":
        return None

    text = str(lead.get("message") or "")
    if not TG_PROPERTY_RE.search(text):
        return None

    direct = bool(TG_DIRECT_BUY_RE.search(text))
    consideration = bool(TG_CONSIDERATION_RE.search(text))
    if not direct and not consideration:
        return None

    # Rental-only demand is not a purchase lead. A message that explicitly says it
    # intends to buy can still pass even if it mentions renting as background.
    if TG_RENT_RE.search(text) and not direct:
        return None

    seller_matches = lead.get("seller_matches") or []
    if seller_matches and not direct:
        return None

    out = dict(lead)
    out["buyer_signal"] = "direct_purchase" if direct else "purchase_consideration"
    out["radar_version"] = VERSION

    score = int(out.get("telegram_score") or 0)
    has_budget = bool(v5.BUDGET_RE.search(text))
    has_timing = bool(v5.TIME_RE.search(text))
    if direct and (has_budget or has_timing):
        out["classification"] = "HOT"
        out["telegram_score"] = max(score, 72)
    else:
        out["classification"] = "WARM"
        out["telegram_score"] = max(score, 52 if direct else 45)
    return out


_original_scan = core.telegram_buyer_scan


async def strict_telegram_buyer_scan(db_client, started):
    result = await _original_scan(db_client, started)
    raw = list(result.get("new_leads") or [])
    filtered = []
    rejected = 0
    for lead in raw:
        refined = refine_telegram_property_buyer(lead)
        if refined is None:
            rejected += 1
            continue
        filtered.append(refined)
    result["new_leads"] = filtered
    result["hot_warm"] = len(filtered)
    result["v5_property_rejected"] = rejected
    print(f"V5.1 TELEGRAM PROPERTY GATE: raw={len(raw)} | accepted={len(filtered)} | rejected={rejected}")
    return result


core.telegram_buyer_scan = strict_telegram_buyer_scan

_original_backfill = v5.backfill_unnotified_telegram


def strict_backfill(db_client, started):
    raw = _original_backfill(db_client, started)
    filtered = []
    for lead in raw:
        refined = refine_telegram_property_buyer(lead)
        if refined is not None:
            filtered.append(refined)
    print(f"V5.1 BACKFILL PROPERTY GATE: raw={len(raw)} | accepted={len(filtered)}")
    return filtered


v5.backfill_unnotified_telegram = strict_backfill

_original_notify = v5.notify_telegram_lead


def strict_notify(lead: dict[str, Any], prefix: str = "NEW") -> bool:
    refined = refine_telegram_property_buyer(lead)
    if refined is None:
        return False
    lead.clear()
    lead.update(refined)
    return _original_notify(lead, prefix)


v5.notify_telegram_lead = strict_notify


def main() -> None:
    v5.main()


if __name__ == "__main__":
    main()
