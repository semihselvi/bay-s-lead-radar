from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import main as core
import main_v5_3 as v53


VERSION = "5.8-qualification-aware-buyer-radar"
v53.VERSION = VERSION
v53.v52.VERSION = VERSION
v53.gate.VERSION = VERSION
v53.gate.v5.VERSION = VERSION
v5 = v53.gate.v5

# ---------------------------------------------------------------------------
# WEB: precision-first buyer intent from real user discussions only
# ---------------------------------------------------------------------------

# Keep only purchase-explicit expansions. A bare phrase such as "looking for an
# apartment" is intentionally NOT direct buyer intent because it is also common
# in rental demand and property listings.
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
# Exa keeps its own returned dates and the V5 freshness gate.
_original_site_query = v53._site_query


def recent_site_query(query: str, domains: list[str] | None) -> str:
    base = _original_site_query(query, domains)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=v5.WEB_MAX_AGE_DAYS)).date().isoformat()
    return f"{base} after:{cutoff}"


v53._site_query = recent_site_query

# Preserve which North-Cyprus query produced the result so a genuinely truncated
# forum title can still be interpreted in query context.
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

# Hard web rejects. Buyer radar must never classify portal inventory or rental
# adverts as people intending to buy.
_WEB_RENTAL_RE = re.compile(
    r"(?:"
    r"\bfor\s+rent\b|\bflats?\s+for\s+rent\b|\bapartments?\s+for\s+rent\b|"
    r"\bhouses?\s+for\s+rent\b|\bmonthly\s+rent\b|\bper\s+month\b|"
    r"\bnot\s+negotiable\b.{0,80}\bper\s+month\b|"
    r"\bà\s+louer\b|\ba\s+louer\b|\bzu\s+mieten\b|\bmietwohnung\b|"
    r"\bаренд\w*\b|\bснять\b|\bсниму\b|\bkiralık\b|\bkiralam\w*\b"
    r")",
    re.I | re.S,
)

_WEB_LISTING_RE = re.compile(
    r"(?:"
    r"\bagency\s+report\b|\breal\s+estate\s+agency\b|\bestate\s+agent\b|"
    r"\bproperty\s+features\s*[:：]|\bvideo\s+walkthrough\s+available\b|"
    r"\bviews?\s+agency\s+report\b|\bnot\s+negotiable\b|"
    r"\bcovered\s+veranda\b|\binternal\s+area\b.{0,30}\bsqm\b|"
    r"\bcontact\s+(?:the\s+)?(?:agent|agency)\b|\bproperty\s+reference\b"
    r")",
    re.I | re.S,
)

# Expat.com's /housing/ area is a classifieds inventory surface, not a user
# discussion forum. It can contain sale/rent adverts whose page chrome mentions
# North Cyprus and whose numeric rent is mistaken for buyer budget.
def _web_listing_url(url: str) -> bool:
    low = str(url or "").casefold()
    if "expat.com/" in low and "/housing/" in low:
        return True
    return any(token in low for token in (
        "/flats-for-rent/", "/flat-for-rent/", "/apartments-for-rent/",
        "/apartment-for-rent/", "/houses-for-rent/", "/house-for-rent/",
        "/properties-for-rent/", "/property-for-rent/",
    ))


_original_classify_web = v5.classify_web


def classify_web_v55(item: dict[str, Any]):
    url = str(item.get("url") or "")
    raw_text = str(item.get("text") or "")
    title = str(item.get("title") or "")

    # Reject obvious inventory/rental pages before any buyer regex can fire.
    hard_text = f"{title} {raw_text[:3200]}"
    if _web_listing_url(url):
        return None
    if _WEB_RENTAL_RE.search(hard_text):
        return None
    if _WEB_LISTING_RE.search(hard_text):
        return None

    # Exa can return a whole page including footer/navigation/related-content text.
    # Classify only the title + first part of the page so unrelated footer phrases
    # cannot inject "North Cyprus" or buyer language into a South Cyprus listing.
    primary = dict(item)
    primary["text"] = raw_text[:2600]
    primary_text = v5._blob(primary)

    result = _original_classify_web(primary)
    if result is not None:
        result["radar_version"] = VERSION
        return result

    query = str(item.get("_search_query") or "")
    if (
        not v5.NORTH_RE.search(primary_text)
        and v5.NORTH_RE.search(query)
        and _WEAK_NORTH_CUE.search(primary_text)
    ):
        shadow = dict(primary)
        shadow["title"] = f"{title} North Cyprus"
        result = _original_classify_web(shadow)
        if result is not None:
            result["title"] = title
            result["north_context_bridge"] = True
            result["radar_version"] = VERSION
            return result
    return None


v5.classify_web = classify_web_v55

# ---------------------------------------------------------------------------
# TELEGRAM: buyer leads + a separate qualification lane for valuable ambiguity
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

TG_BOT_AUTHOR_RE = re.compile(r"^@?[a-z0-9_]*bot$", re.I)

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

# Requests for a tradesperson/service often contain a property word later in the
# sentence ("plumber ... our apartment") and used to enter the buyer candidate net.
TG_SERVICE_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:ищу|ищем|нужен|нужна|нужно)\b.{0,90}\b(?:сантехник\w*|электрик\w*|мастер\w*|"
    r"ремонтник\w*|клининг\w*|уборк\w*|риэлтор\w*|адвокат\w*)\b|"
    r"\b(?:looking\s+for|need)\b.{0,90}\b(?:plumber|electrician|handyman|repairman|cleaner|cleaning\s+service)\b|"
    r"\b(?:arıyorum|ariyorum|lazım|lazim)\b.{0,90}\b(?:tesisatçı|tesisatci|elektrikçi|elektrikci|usta|tamirci|temizlikçi|temizlikci)\b"
    r")",
    re.I | re.S,
)

# Terse demand can be valuable even when the writer did not say "buy" or "rent".
# We only surface it for qualification when it is specific enough to contact:
# a North-Cyprus locality plus a concrete unit/property type/configuration.
TG_LOCALITY_RE = re.compile(
    r"\b(?:girne|kyrenia|iskele|İskele|long\s+beach|esentepe|lapta|alsancak|karaoğlanoğlu|karaoglanoglu|"
    r"arabk[oö]y|arabkoy|арабк[её]й|искеле|гирне|эсентепе|лапта|алсанджак|"
    r"famagusta|gazimağusa|gazimagusa|yeniboğaziçi|yenibogazici|tatlısu|tatlisu|bafra|gaziveren|lefke)\b",
    re.I,
)
TG_UNIT_SPEC_RE = re.compile(
    r"(?:\b(?:studio|студи\w*|квартир\w*|вилл\w*|дом\w*|apartment|flat|house|villa|daire|ev)\b|"
    r"\b[1-5]\s*\+\s*[01]\b)",
    re.I,
)

# Bare monthly-scale amounts in terse demand are overwhelmingly rental requests
# in the groups we scan. Purchase-scale amounts are already handled by V5.3.
TG_LOW_AMOUNT_RE = re.compile(
    r"\b(?:за|до|up\s+to|max(?:imum)?|budget|бюджет|bütçe|butce|bis)\s*"
    r"(?:[£€$])?\s*(\d{2,4})(?!\s*[kKmM])\b",
    re.I,
)


def _likely_monthly_scale(text: str) -> bool:
    for m in TG_LOW_AMOUNT_RE.finditer(text or ""):
        try:
            value = int(m.group(1))
        except Exception:
            continue
        if 100 <= value <= 5000:
            return True
    return False


def _specific_ambiguous_property_demand(text: str) -> bool:
    if not v53.TG_TERSE_DEMAND_RE.search(text):
        return False
    if TG_SERVICE_REQUEST_RE.search(text):
        return False
    if v53.gate.TG_RENT_RE.search(text) or TG_SHORT_STAY_RE.search(text):
        return False
    if TG_STRONG_SUPPLY_RE.search(text) or v53.gate.TG_SUPPLY_RE.search(text):
        return False
    if _likely_monthly_scale(text):
        return False
    return bool(TG_LOCALITY_RE.search(text) and TG_UNIT_SPEC_RE.search(text))


v53.gate.TG_SUPPLY_RE = re.compile(
    v53.gate.TG_SUPPLY_RE.pattern
    + r"|\b(?:срочная\s+)?продаж\w*\b|\bпродаю\b|\bпродать\b.{0,80}\b(?:вилл\w*|квартир\w*|апартамент\w*|дом\w*)\b",
    re.I | re.S,
)

_original_refine = v53.refine_with_budgeted_demand


def refine_telegram_v55(lead: dict[str, Any]):
    text = str(lead.get("message") or "")
    author = str(lead.get("author") or "").strip()

    if TG_BOT_AUTHOR_RE.search(author):
        return None
    if TG_STRONG_SUPPLY_RE.search(text):
        return None
    if v53.gate.TG_SUPPLY_RE.search(text):
        return None
    if TG_SHORT_STAY_RE.search(text):
        return None
    if TG_SERVICE_REQUEST_RE.search(text):
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

    # Explicit ownership/title/payment language is a genuine purchase qualifier.
    if TG_PURCHASE_QUALIFIER_RE.search(text):
        out = dict(lead)
        has_budget = v53._purchase_scale_budget(text)
        out["classification"] = "HOT" if has_budget else "WARM"
        out["buyer_signal"] = "purchase_qualified_demand"
        out["telegram_score"] = max(int(out.get("telegram_score") or 0), 76 if has_budget else 64)
        out["budget_detected"] = has_budget
        out["radar_version"] = VERSION
        return out

    # Do not silently throw away a specific property seeker just because they did
    # not state buy/rent. It is NOT a buyer lead yet; route it as a qualification
    # opportunity so Semih can ask one question and potentially turn it into work.
    if _specific_ambiguous_property_demand(text):
        out = dict(lead)
        out["classification"] = "WARM"  # compatibility with the existing pipeline
        out["buyer_signal"] = "needs_purchase_confirmation"
        out["telegram_score"] = max(int(out.get("telegram_score") or 0), 52)
        out["budget_detected"] = False
        out["qualification_question"] = "Satın alma mı kiralama mı düşünüyorsunuz?"
        out["radar_version"] = VERSION
        return out

    return None


v53.gate.refine_telegram_property_buyer = refine_telegram_v55

# The legacy notifier calls every HOT/WARM row a BUYER. Qualification rows must
# be visibly different so they never contaminate the buyer count semantically.
_base_notify = v5.notify_telegram_lead


def notify_telegram_v58(lead: dict[str, Any], prefix: str = "NEW") -> bool:
    if lead.get("buyer_signal") == "needs_purchase_confirmation":
        if str(lead.get("market") or "") != "north_cyprus":
            return False
        message = v5._clip(lead.get("message") or "", 900)
        msg = (
            f"🟠 BAY-S | TALEP VAR — SATIN ALMA/KİRALAMA NET DEĞİL [{prefix}]\n\n"
            f"Grup: {lead.get('group','')}\n"
            f"Kişi: {lead.get('author','-') or '-'}\n"
            f"Skor: {lead.get('telegram_score',0)}\n\n"
            f"{message}\n\n"
            f"✅ Sorulacak tek soru: Satın alma mı kiralama mı düşünüyorsunuz?\n\n"
            f"🔗 {lead.get('url','') or 'Doğrudan link yok'}"
        )
        core.telegram(msg[:3900])
        return True
    return _base_notify(lead, prefix)


v5.notify_telegram_lead = notify_telegram_v58


def main() -> None:
    v5.main()


if __name__ == "__main__":
    main()
