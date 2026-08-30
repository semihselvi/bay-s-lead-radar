from __future__ import annotations

import re
from typing import Any

import main as core
import main_v5 as v5


VERSION = "5.1.1-self-buyer-gate"
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

# A direct buyer must speak as the buyer. Generic transaction words inside a
# seller advert (e.g. "you can purchase remotely") are intentionally excluded.
TG_SELF_BUY_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,45}\b(?:want|looking|planning|plan|considering|ready|hoping|would\s+like|need)\b"
    r".{0,90}\b(?:buy|purchase|buying|purchasing)\b|"
    r"\b(?:looking\s+to\s+buy|want\s+to\s+buy|planning\s+to\s+buy|ready\s+to\s+buy|seeking\s+to\s+buy)\b|"
    r"\bcash\s+buyer\b|"
    r"\b(?:я|мы)\b.{0,45}\b(?:хочу|хотим|планирую|планируем|ищу|ищем|готов\w*)\b"
    r".{0,110}\b(?:купить|приобрести|покупк\w*)\b|"
    r"\bкуплю\b.{0,120}\b(?:недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|участ\w*|земл\w*)\b|"
    r"\bищу\b.{0,120}\b(?:недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*)\b"
    r".{0,100}\b(?:купить|для\s+покупк\w*)\b|"
    r"\b(?:ich|wir)\b.{0,45}\b(?:suche|suchen|möchte|moechte|möchten|moechten|will|wollen|plane|planen)\b"
    r".{0,140}\b(?:kaufen|erwerben|zum\s+kauf)\b|"
    r"\bsuche\b.{0,120}\b(?:immobilie|wohnung|haus|villa|apartment)\w*\b.{0,100}\b(?:zum\s+kauf|zu\s+kaufen)\b|"
    r"\b(?:ja|my)\b.{0,45}\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b"
    r".{0,140}\b(?:kupić|kupic|zakupić|zakupic)\b|"
    r"\bszukam\b.{0,120}\b(?:nieruchomość|nieruchomosci|mieszkanie|apartament|willa|dom)\w*\b"
    r".{0,100}\b(?:do\s+kupienia|kupić|kupic)\b|"
    r"\b(?:ben|biz)\b.{0,45}\b(?:istiyorum|istiyoruz|düşünüyorum|dusunuyorum|arıyorum|ariyorum)\b"
    r".{0,120}\b(?:satın\s+al|almak)\b|"
    r"\b(?:satın\s+almak\s+istiyorum|satın\s+almak\s+istiyoruz|ev\s+almak\s+istiyorum|daire\s+almak\s+istiyorum|alıcıyım)\b"
    r")",
    re.I | re.S,
)

TG_CONSIDERATION_RE = re.compile(
    r"(?:\bwhere\s+should\s+(?:i|we)\s+buy\b|\bwhich\s+(?:area|region).{0,80}\b(?:should\s+)?(?:i|we).{0,50}\bbuy\b|"
    r"\bcan\s+foreigners?\s+buy\b|\bis\s+it\s+safe\s+to\s+buy\b|"
    r"\bгде\s+(?:лучше\s+)?купить\b|\bстоит\s+ли\s+покупать\b|\bкак\s+купить\b|"
    r"\bможно\s+ли\s+иностранц\w*.{0,60}\bкупить\b|"
    r"\bwelche\s+region.{0,80}\b(?:sollte|kann)\s+ich.{0,60}\bkaufen\b|\bwo\s+sollte\s+ich\s+kaufen\b|"
    r"\bgdzie\s+(?:najlepiej\s+)?kupi(?:ć|c)\b|\bczy\s+cudzoziemiec.{0,60}\bkupi(?:ć|c)\b|"
    r"\bhangi\s+bölge.{0,80}\b(?:satın\s+al|almak)\b|\byabancılar?.{0,60}\b(?:ev|daire|gayrimenkul).{0,60}\balabilir\b)",
    re.I | re.S,
)

TG_RENT_RE = re.compile(
    r"(?:\bfor\s+rent\b|\blooking\s+to\s+rent\b|\brental\b|\bmonthly\b|\bper\s+month\b|"
    r"\bаренд\w*\b|\bсниму\b|\bснять\b|\bсда[её]тся\b|\bв\s+месяц\b|\bпосуточ\w*\b|"
    r"\bkiralık\b|\baylık\b|\bgünlük\b|\bmieten\b|\bmiete\b|\bwynajem\w*\b|\bwynająć\b)",
    re.I,
)

# Strong seller/listing structure. One of these signals is enough to reject a
# message unless there is explicit first-person buyer intent.
TG_SUPPLY_RE = re.compile(
    r"(?:\bfor\s+sale\b|\bavailable\s+(?:now|unit|units|apartment|apartments|villa|villas)\b|"
    r"\bproperty\s+(?:code|id|ref(?:erence)?)\b|\blisting\s+(?:id|ref(?:erence)?)\b|"
    r"\bprice\s+from\b|\bbook\s+(?:a\s+)?viewing\b|\bremote\s+purchase\b|"
    r"\bпрода[её]тся\b|\bпродам\b|\bкод\s+объекта\b|\bid\s+объекта\b|\bномер\s+объекта\b|"
    r"\bготов[а-яё]*\s+к\s+проживанию\b|\bприобрест\w*\s+удал[её]нно\b|"
    r"\bонлайн.{0,80}\b(?:просмотр|посетить|квартир|апартамент)\b|"
    r"\bzu\s+verkaufen\b|\bobjekt(?:nummer|nr\.?|code)\b|\bmakler\b|"
    r"\bna\s+sprzedaż\b|\bnumer\s+oferty\b|\bbiuro\s+nieruchomości\b|"
    r"\bsatılık\b|\bportföy\s+no\b|\bilan\s+no\b|\bproje\s+kodu\b)",
    re.I | re.S,
)


# The core scanner is still used for safe Telegram traversal/dedupe. Keep its
# candidate net broad enough to catch buyers, but remove generic seller-language
# triggers such as bare "приобрести".
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
    r"\bкуплю\b",
    r"\bищу\b.{0,120}\b(?:купить|для покупк\w*)\b",
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
    r"\bгде (?:лучше )?купить\b",
    r"\bстоит ли покупать\b",
    r"\bкак купить\b",
    r"\bwelche region\b",
    r"\bgdzie kupi(?:ć|c)\b",
    r"\bhangi bölge\b",
]

core.TG_CONTEXT = [
    r"\bwhere should i buy\b",
    r"\bwhich (?:area|region)\b",
    r"\bcan foreigners? buy\b",
    r"\bгде (?:лучше )?купить\b",
    r"\bстоит ли покупать\b",
    r"\bкак купить\b",
    r"\bможно ли иностранц\w*.{0,60}\bкупить\b",
    r"\bwelche region\b",
    r"\bwo sollte ich kaufen\b",
    r"\bgdzie kupi(?:ć|c)\b",
    r"\bhangi bölge\b",
]


def refine_telegram_property_buyer(lead: dict[str, Any]) -> dict[str, Any] | None:
    if str(lead.get("market") or "") != "north_cyprus":
        return None

    text = str(lead.get("message") or "")
    if not TG_PROPERTY_RE.search(text):
        return None

    self_buy = bool(TG_SELF_BUY_RE.search(text))
    consideration = bool(TG_CONSIDERATION_RE.search(text))
    if not self_buy and not consideration:
        return None

    # Seller/listing copy cannot become a buyer lead merely because it contains
    # words such as purchase/buy. Explicit first-person demand can override this.
    if TG_SUPPLY_RE.search(text) and not self_buy:
        return None

    # Rental-only demand is not a purchase lead. A genuine buyer may mention that
    # they currently rent, so explicit self-buy intent wins over background rent.
    if TG_RENT_RE.search(text) and not self_buy:
        return None

    seller_matches = lead.get("seller_matches") or []
    if seller_matches and not self_buy:
        return None

    out = dict(lead)
    out["buyer_signal"] = "self_purchase" if self_buy else "purchase_consideration"
    out["radar_version"] = VERSION

    score = int(out.get("telegram_score") or 0)
    has_budget = bool(v5.BUDGET_RE.search(text))
    has_timing = bool(v5.TIME_RE.search(text))
    if self_buy and (has_budget or has_timing):
        out["classification"] = "HOT"
        out["telegram_score"] = max(score, 76)
    else:
        out["classification"] = "WARM"
        out["telegram_score"] = max(score, 58 if self_buy else 48)
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
    print(f"V5.1.1 TELEGRAM SELF-BUYER GATE: raw={len(raw)} | accepted={len(filtered)} | rejected={rejected}")
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
    print(f"V5.1.1 BACKFILL SELF-BUYER GATE: raw={len(raw)} | accepted={len(filtered)}")
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
