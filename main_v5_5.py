from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import main as core
import main_v5_3 as v53


VERSION = "5.6-telegram-supply-bot-guard"
v53.VERSION = VERSION
v53.v52.VERSION = VERSION
v53.gate.VERSION = VERSION
v53.gate.v5.VERSION = VERSION
v5 = v53.gate.v5

# ---------------------------------------------------------------------------
# WEB: tune buyer intent from real Serper diagnostics
# ---------------------------------------------------------------------------

# Real buyer phrasing seen in diagnostics, including:
#   "im planning on buying two properties..."
#   "father-in-law wants to buy..."
#   "Looking for property in Northern Cyprus"
v5.DIRECT_PATTERNS.extend([
    re.compile(
        r"\b(?:i|i'm|im|i\s+am|we|we're|we\s+are)\b.{0,55}"
        r"\b(?:planning|plan|thinking|considering)\b.{0,25}"
        r"\b(?:on\s+|about\s+)?(?:buying|purchasing)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:father(?:-in-law)?|mother(?:-in-law)?|wife|husband|partner|parents?|friend)\b"
        r".{0,55}\b(?:wants?|plans?|is\s+looking|are\s+looking)\b"
        r".{0,70}\b(?:buy|purchase|buying|purchasing)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:i(?:'m|\s+am)?\s+)?looking\s+for\s+(?:an?\s+)?"
        r"(?:property|apartment|apartement|flat|house|villa|studio|land)\b",
        re.I,
    ),
])

# Better property-budget detection for forms such as "700-800k euros".
v5.BUDGET_RE = re.compile(
    r"(?:"
    r"[£€$₺₽]\s?\d[\d\s.,]*(?:\s*[-–]\s*[£€$₺₽]?\s?\d[\d\s.,]*)?\s*[kKmM]?|"
    r"\b\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*[kKmM]?\s*"
    r"(?:gbp|eur|euros?|usd|dollars?|try|tl|rub|руб)\b"
    r")",
    re.I,
)

# Serper should prefer fresh pages/posts. This affects only the Serper fallback;
# Exa keeps its own returned dates and the V5 90-day freshness gate.
_original_site_query = v53._site_query


def recent_site_query(query: str, domains: list[str] | None) -> str:
    base = _original_site_query(query, domains)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=v5.WEB_MAX_AGE_DAYS)).date().isoformat()
    return f"{base} after:{cutoff}"


v53._site_query = recent_site_query

# Preserve which North-Cyprus query produced the result so a truncated title such
# as "...in northern ..." can still be safely interpreted in context.
_original_search = core.exa_search


def search_with_context(query: str, include_domains: list[str] | None = None):
    rows = _original_search(query, include_domains)
    for row in rows:
        row["_search_query"] = query
    return rows


core.exa_search = search_with_context

_WEAK_NORTH_CUE = re.compile(
    r"\b(?:northern|north\s+side|turkish\s+side|occupied\s+part|kyrenia|girne|iskele|long\s+beach)\b",
    re.I,
)

_original_classify_web = v5.classify_web


def classify_web_v55(item: dict[str, Any]):
    result = _original_classify_web(item)
    if result is not None:
        return result

    text = v5._blob(item)
    query = str(item.get("_search_query") or "")
    if (
        not v5.NORTH_RE.search(text)
        and v5.NORTH_RE.search(query)
        and _WEAK_NORTH_CUE.search(text)
    ):
        shadow = dict(item)
        shadow["title"] = f"{item.get('title', '')} North Cyprus"
        result = _original_classify_web(shadow)
        if result is not None:
            result["title"] = item.get("title", "")
            result["north_context_bridge"] = True
            result["radar_version"] = VERSION
            return result
    return None


v5.classify_web = classify_web_v55

# ---------------------------------------------------------------------------
# TELEGRAM: accept purchase-specific terse demand, reject short-stay/supply noise
# ---------------------------------------------------------------------------

TG_PURCHASE_QUALIFIER_RE = re.compile(
    r"(?:"
    r"\btitle\s+deed\b|\bdeed\b|\bownership\b|\bfreehold\b|\bpayment\s+plan\b|\bmortgage\b|"
    r"\bтапу\b|\bтитул\w*\b|\bко[чc]ан\w*\b|\bоформлен\w*\s+на\s+имя\s+собственника\b|"
    r"\bпереуступк\w*\b|\bипотек\w*\b|\bрассрочк\w*\b|\bпервоначальн\w*\s+взнос\w*\b|"
    r"\bgrundbuch\b|\beigentum\b|\bzahlungsplan\b|\bhypothek\b|"
    r"\bksi[eę]ga\s+wieczysta\b|\bwłasno\w*\b|\bwlasno\w*\b|\bplan\s+płatno\w*\b|"
    r"\btapu\b|\bkoçan\b|\bkocan\b|\beşdeğer\b|\besdeger\b|\btahsis\b|"
    r"\bsözleşme\s+devri\b|\bsozlesme\s+devri\b"
    r")",
    re.I | re.S,
)

TG_SHORT_STAY_RE = re.compile(
    r"(?:"
    r"\bfrom\b.{0,45}\bto\b.{0,45}\b(?:september|october|november|december|january|february|march|april|may|june|july|august)\b|"
    r"\bfor\s+\d+\s+(?:nights?|days?|weeks?)\b|\bcheck[- ]?in\b|\bcheck[- ]?out\b|"
    r"\bс\s+\d{1,2}\s+по\s+\d{1,2}\s+(?:сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|август\w*)\b|"
    r"\bна\s+завтра\b|\bна\s+\d+\s+(?:дн\w*|ноч\w*|недел\w*)\b|"
    r"\bпосут\w*\b|\bпроживани\w*\b.{0,80}\bс\s+\d{1,2}\s+по\s+\d{1,2}\b"
    r")",
    re.I | re.S,
)

# Buyer radar must never promote automated listing publishers. A Telegram account
# ending in "bot" is not a human buyer even if its advert contains words such as
# "нужно" and a purchase-scale price.
TG_BOT_AUTHOR_RE = re.compile(r"^@?[a-z0-9_]*bot$", re.I)

# Strong supply/advertising language observed in real false positives. These are
# checked BEFORE the older terse-demand classifier because seller copy such as
# "клиенту нужно продать виллу" can otherwise look like "нужно ... виллу" demand.
TG_STRONG_SUPPLY_RE = re.compile(
    r"(?:"
    r"\bсрочн\w*.{0,30}\bпродаж\w*\b|"
    r"\bнов\w*\s+объявлен\w*\b|"
    r"\bклиент\w*.{0,80}\b(?:нужно|надо|хочет|хотят)\b.{0,60}\bпродать\b|"
    r"\b(?:продажа|продаю|продаем|продаём|продать)\b.{0,70}\b(?:вилл\w*|квартир\w*|апартамент\w*|дом\w*|недвижимост\w*)\b|"
    r"\bpulsemarket\b|"
    r"\bбольше\s+фотографий\b|\bсмотреть\s+на\s+сайте\b|"
    r"\bподключить\s+алерт\w*\b|\bполучать\s+новые\s+объявлен\w*\b|"
    r"\bновое\s+объявление\b.{0,120}\b(?:цена|контакт)\s*[:：]"
    r")",
    re.I | re.S,
)

# Extend the shared seller gate as well so every V5 Telegram path recognises the
# common Russian noun form "продажа", not only "продаётся/продам".
v53.gate.TG_SUPPLY_RE = re.compile(
    v53.gate.TG_SUPPLY_RE.pattern
    + r"|\b(?:срочная\s+)?продаж\w*\b|\bпродаю\b|\bпродать\b.{0,80}\b(?:вилл\w*|квартир\w*|апартамент\w*|дом\w*)\b",
    re.I | re.S,
)

_original_refine = v53.refine_with_budgeted_demand


def refine_telegram_v55(lead: dict[str, Any]):
    text = str(lead.get("message") or "")
    author = str(lead.get("author") or "").strip()

    # Hard precision gates MUST run before the inherited classifier.
    if TG_BOT_AUTHOR_RE.search(author):
        return None
    if TG_STRONG_SUPPLY_RE.search(text):
        return None
    if v53.gate.TG_SUPPLY_RE.search(text):
        return None
    if TG_SHORT_STAY_RE.search(text):
        return None

    result = _original_refine(lead)
    if result is not None:
        return result

    if str(lead.get("market") or "") != "north_cyprus":
        return None

    if v53.gate.TG_RENT_RE.search(text):
        return None
    if not v53.gate.TG_PROPERTY_RE.search(text):
        return None
    if not v53.TG_TERSE_DEMAND_RE.search(text):
        return None
    if not TG_PURCHASE_QUALIFIER_RE.search(text):
        return None

    out = dict(lead)
    has_budget = v53._purchase_scale_budget(text)
    out["classification"] = "HOT" if has_budget else "WARM"
    out["buyer_signal"] = "purchase_qualified_demand"
    out["telegram_score"] = max(int(out.get("telegram_score") or 0), 76 if has_budget else 64)
    out["budget_detected"] = has_budget
    out["radar_version"] = VERSION
    return out


v53.gate.refine_telegram_property_buyer = refine_telegram_v55


def main() -> None:
    v5.main()


if __name__ == "__main__":
    main()
