from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import nc_v5_batch_quality_guard as batch_guard

radar = batch_guard.radar
core = radar.core
v5 = radar.v5

VERSION = "6.0-broad-recall-intent-radar"
for _module in (radar, radar.v53, radar.v53.v52, radar.v53.gate, v5):
    _module.VERSION = VERSION

# ---------------------------------------------------------------------------
# Geography / source scope
# ---------------------------------------------------------------------------

NC_GEO_RE = re.compile(
    r"(?:"
    r"\bnorth(?:ern)?\s+cyprus\b|\btrnc\b|\bkktc\b|\bkuzey\s+k[ıi]br[ıi]s\b|"
    r"\bсеверн\w*\s+кипр\w*\b|"
    r"\biskele\b|\bi̇skele\b|\byeni\s+iskele\b|\btrikomo\b|\blong\s+beach\b|"
    r"\bfamagust\w*\b|\bgazima[ğg]usa\b|\bma[ğg]usa\b|\bkyrenia\b|\bgirne\b|"
    r"\balsancak\b|\blapta\b|\besentepe\b|\btatl[ıi]su\b|\bbafra\b|"
    r"\byenibo[ğg]azi[çc]i\b|\bbo[ğg]az\b|\blefke\b|\bg[üu]zelyurt\b|\bmorphou\b|"
    r"\bercan\b|\bnicosia\s+north\b|\blefko[şs]a\b|"
    r"\bискел\w*\b|\bлонг\s+бич\b|\bфамагуст\w*\b|\bгирн\w*\b|"
    r"\bалсанджак\b|\bлапт\w*\b|\bэсентеп\w*\b|\bтатлысу\b|\bбафр\w*\b|"
    r"\bбоаз\w*\b|\bлефк\w*\b|\bгюзельюрт\b"
    r")",
    re.I,
)

# Python's regex engine treats a copied Cyrillic word boundary literally; add a
# clean secondary expression for the most important Russian localities.
NC_GEO_RU_RE = re.compile(
    r"(?:северн\w*\s+кипр\w*|искел\w*|лонг\s+бич|фамагуст\w*|гирн\w*|"
    r"алсанджак|лапт\w*|эсентеп\w*|татлысу|бафр\w*|боаз\w*|лефк\w*|гюзельюрт)",
    re.I,
)

DIRECT_NORTH_GROUP_RE = re.compile(
    r"(?:north\s*cyprus|northern\s*cyprus|trnc|kktc|kuzey\s*k[ıi]br[ıi]s|"
    r"северн\w*\s+кипр|iskele|i̇skele|trikomo|long\s*beach|girne|kyrenia|"
    r"famagust|gazima[ğg]usa|ma[ğg]usa|alsancak|lapta|esentepe|tatl[ıi]su|"
    r"bafra|yenibo[ğg]azi[çc]i|bo[ğg]az|lefke|g[üu]zelyurt)",
    re.I,
)

GENERIC_CYPRUS_GROUP_RE = re.compile(r"(?:cyprus|кипр|k[ıi]br[ıi]s|kibris|zypern|cypr)", re.I)
THEMATIC_GROUP_RE = re.compile(
    r"(?:expat|relocat|student|university|international|foreign|russian|рус|"
    r"invest|property|real\s+estate|housing|rent|rental|emlak|gayrimenkul|yaşam|living)",
    re.I,
)
SOUTH_ONLY_RE = re.compile(
    r"\b(?:limassol|larnaca|paphos|ayia\s+napa|protaras|лимассол|ларнак[аи]|пафос)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Intent signal net: broad collection, strict hard rejects
# ---------------------------------------------------------------------------

PROPERTY_RE = re.compile(
    r"(?:"
    r"\bproperty\b|\breal\s+estate\b|\bapartment\b|\bflat\b|\bvilla\b|\bhouse\b|\bstudio\b|\bland\b|\bplot\b|"
    r"\bdaire\b|\bev\b|\bkonut\b|\bvilla\b|\bst[üu]dyo\b|\barsa\b|\bgayrimenkul\b|"
    r"\bквартир\w*\b|\bапартамент\w*\b|\bвилл\w*\b|\bдом\w*\b|\bстуди\w*\b|\bнедвижимост\w*\b|\bземл\w*\b|"
    r"\b[0-6]\s*\+\s*[0-3]\b|\b(?:one|two|three|1|2|3)\s+bed(?:room)?s?\b|"
    r"\b(?:bir|iki|üç|uc|1|2|3)\s+yatak\s+odal[ıi]\b"
    r")",
    re.I,
)

BUY_RE = re.compile(
    r"(?:"
    r"\blooking\s+to\s+buy\b|\bwant(?:ing)?\s+to\s+buy\b|\bplanning\s+to\s+buy\b|\bconsidering\s+buying\b|"
    r"\bwhere\s+should\s+(?:i|we)\s+buy\b|\bwhat\s+can\s+(?:i|we)\s+(?:buy|get)\b|\bbuy\s+(?:a|an)?\s*(?:property|apartment|flat|house|villa|studio|land)\b|"
    r"\bsat[ıi]n\s+almak\s+istiyorum\b|\bev\s+almak\s+istiyorum\b|\bdaire\s+almak\s+istiyorum\b|"
    r"\b(?:ev|daire|villa|arsa|konut|gayrimenkul)\s+al(?:mak|may[ıi]|[ıi]p)\b|"
    r"\bne\s+al[ıi]n(?:[ıi]r|abilir|abilirim|abiliriz)\b|\bnereden\s+ev\s+al[ıi]n[ıi]r\b|"
    r"\bхочу\s+купить\b|\bкуплю\b|\bпланир\w*\s+купить\b|\bстоит\s+ли\s+покупать\b|\bгде\s+(?:лучше\s+)?купить\b|"
    r"\bчто\s+можно\s+купить\b|\bищу\s+на\s+покупку\b"
    r")",
    re.I | re.S,
)

DEMAND_RE = re.compile(
    r"(?:"
    r"\blooking\s+for\b|\bseeking\b|\bneed\s+(?:a|an|some)?\b|"
    r"\bar[ıi]yorum\b|\bbak[ıi]yorum\b|\bariyorum\b|\bbakiyorum\b|"
    r"\bищу\b|\bищем\b|\bнужн(?:а|ы|о)\b|\bподбира\w*\b|\bрассматрива\w*\b"
    r")",
    re.I,
)

RENT_DEMAND_RE = re.compile(
    r"(?:"
    r"\blooking\s+to\s+rent\b|\blooking\s+for\b.{0,100}\b(?:rent|rental)\b|\bneed\b.{0,100}\b(?:rent|rental|apartment|flat|house|villa)\b.{0,60}\b(?:month|from|until|move)\b|"
    r"\bkiral[ıi]k\s+(?:ev|daire|villa|st[üu]dyo)?\s*ar[ıi]yorum\b|\b(?:ev|daire|villa|st[üu]dyo)\s+kiralamak\s+istiyorum\b|"
    r"\b(?:ev|daire|villa|st[üu]dyo)\s+ar[ıi]yorum\b.{0,80}\b(?:kiral[ıi]k|ayl[ıi]k|g[üu]nl[üu]k)\b|"
    r"\bсниму\b|\bхочу\s+снять\b|\bищу\b.{0,100}\b(?:аренд|долгосроч|посуточ)\b|"
    r"\bищу\s+(?:квартир\w*|дом\w*|вилл\w*|студи\w*)\b.{0,100}\b(?:на\s+месяц|на\s+год|долгосроч|аренд)\b"
    r")",
    re.I | re.S,
)

RELOCATION_RE = re.compile(
    r"(?:"
    r"\b(?:moving|relocating|planning\s+to\s+move|move)\s+to\b|\bretiring\s+to\b|"
    r"\b(?:k[ıi]br[ıi]s|iskele|girne|ma[ğg]usa|north\s+cyprus).{0,60}\bta[şs][ıi]n(?:may[ıi]|mak|aca[ğg][ıi]z|aca[ğg][ıi]m)\b|"
    r"\bta[şs][ıi]n(?:may[ıi]|mak|aca[ğg][ıi]z|aca[ğg][ıi]m)\b.{0,80}\b(?:k[ıi]br[ıi]s|iskele|girne|ma[ğg]usa)\b|"
    r"\bпереех(?:ать|ать\s+на|ать\s+в)|\bпереезжа\w*\b|\bпланир\w*\s+переезд\w*\b"
    r")",
    re.I | re.S,
)

INVESTOR_RE = re.compile(
    r"(?:"
    r"\binvest(?:ment|ing|or)\b|\brental\s+yield\b|\byield\b|\broi\b|\breturn\s+on\s+investment\b|\bpayment\s+plan\b|"
    r"\bbest\s+area\s+to\s+invest\b|\bproperty\s+prices?\b|\brental\s+income\b|"
    r"\byat[ıi]r[ıi]m\b|\bkira\s+getirisi\b|\bgeri\s+d[öo]n[üu][şs]\b|\btaksit\w*\b|\b[öo]deme\s+plan[ıi]\b|"
    r"\b(?:ev|daire|villa)\s+al[ıi]p\s+kiraya\s+ver\w*\b|\bbuy\b.{0,80}\brent\s+(?:it|the\s+property)\s+out\b|"
    r"\binvestic\w*\b|\bинвест\w*\b|\bдоход\s+от\s+аренд\w*\b|\bдоходност\w*\b|\bрассрочк\w*\b"
    r")",
    re.I,
)

RESEARCH_RE = re.compile(
    r"(?:"
    r"\bhow\s+much\s+(?:is|are|does)\b|\bproperty\s+prices?\b|\bwhere\s+should\s+(?:i|we)\b|\bwhich\s+area\b|"
    r"\bwhat\s+can\s+(?:i|we)\s+(?:buy|get)\b|\bbest\s+area\b|"
    r"\bfiyatlar[ıi]?\s+ne\s+kadar\b|\bka[çc]\s+para\b|\bhangi\s+b[öo]lge\b|"
    r"\bne\s+al[ıi]n(?:[ıi]r|abilir|abilirim|abiliriz)\b|"
    r"\bnereden\s+(?:ev|daire|villa)\s+al[ıi]n[ıi]r\b|"
    r"\bсколько\s+стоит\b|\bкакие\s+цены\b|\bпосоветуйте\s+район\b|\bкакой\s+район\b|\bгде\s+лучше\b|\bстоит\s+ли\b"
    r")",
    re.I,
)

RESIDENCY_RE = re.compile(
    r"(?:\bresiden(?:ce|cy)\s+permit\b|\bproperty\s+for\s+residency\b|\boturma\s+izni\b|\bikamet\b|\bвнж\b|\bвид\s+на\s+жительство\b)",
    re.I,
)

PURCHASE_QUALIFIER_RE = re.compile(
    r"(?:\bko[çc]an\w*\b|\btapu\b|\btitle\s+deed\b|\bdeed\b|\bready\s+to\s+move\b|"
    r"\bhaz[ıi]r\s+teslim\b|\btaksit\w*\b|\bpayment\s+plan\b|\bрассрочк\w*\b|\bготов\w*\s+квартир\w*\b)",
    re.I,
)

SUPPLY_STRONG_RE = re.compile(
    r"(?:"
    r"\bfor\s+sale\b.{0,150}\b(?:price|bedroom|sqm|m2|contact|whatsapp)\b|"
    r"\b(?:available\s+units?|price\s+from|book\s+a\s+viewing|property\s+(?:id|ref)|listing\s+(?:id|ref))\b|"
    r"\b(?:sat[ıi]l[ıi]k|kiral[ıi]k)\b.{0,140}\b(?:fiyat|m2|metrekare|ileti[şs]im|whatsapp|portf[öo]y)\b|"
    r"\b(?:прода[её]тся|продам|сдам|сда[её]тся)\b.{0,140}\b(?:цена|м2|м²|пишите|whatsapp|контакт)\b|"
    r"\b(?:real\s+estate\s+agency|estate\s+agent|realtor|property\s+consultant|broker|agency)\b|"
    r"\b(?:агентство\s+недвижимости|риелтор|риэлтор|застройщик)\b"
    r")",
    re.I | re.S,
)

TIME_RE = re.compile(
    r"(?:\b(?:today|tomorrow|this\s+week|next\s+week|this\s+month|next\s+month|soon|december|january|february|march|april|may|june|july|august|september|october|november)\b|"
    r"\b(?:bug[üu]n|yar[ıi]n|bu\s+ay|gelecek\s+ay|aral[ıi]k|ocak|şubat|mart|nisan|may[ıi]s|haziran|temmuz|a[ğg]ustos|eyl[üu]l|ekim|kas[ıi]m)\b|"
    r"\b(?:сегодня|завтра|в\s+этом\s+месяце|в\s+следующем\s+месяце|декабр\w*|январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*)\b)",
    re.I,
)

ROOM_RE = re.compile(
    r"(?:\b(?:studio|st[üu]dyo|студи\w*|[0-6]\s*\+\s*[0-3]|one|two|three|1|2|3)\s*(?:bed(?:room)?s?)?\b|"
    r"\b(?:bir|iki|üç|uc|1|2|3)\s+yatak\s+odal[ıi]\b)",
    re.I,
)
SEA_RE = re.compile(r"(?:near\s+(?:the\s+)?sea|sea\s+view|denize\s+yak[ıi]n|море|у\s+моря)", re.I)
FURNISHED_RE = re.compile(r"(?:furnished|e[şs]yal[ıi]|меблирован\w*|с\s+мебелью)", re.I)

# Web search expansion: broad intent families instead of purchase-only wording.
v5.EXA_QUERIES = [
    ("North Cyprus moving relocation housing apartment family area", None),
    ("North Cyprus property prices budget 100000 150000 200000 pounds what can I buy", None),
    ("North Cyprus rental yield investment payment plan property", None),
    ("North Cyprus looking for apartment villa near sea", None),
    ("North Cyprus looking to rent apartment villa moving", None),
    ("Iskele Long Beach property prices investment rental yield", None),
    ("Iskele Long Beach apartment budget payment plan ready to move", None),
    ("Kyrenia Girne apartment villa looking for moving rent buy", None),
    ("Famagusta Gazimagusa Magusa apartment rent buy student", None),
    ("Kuzey Kıbrıs taşınmayı düşünüyorum ev daire hangi bölge", None),
    ("Kuzey Kıbrıs ev fiyatları bütçe ne alınır koçan taksit hazır teslim", None),
    ("Kuzey Kıbrıs yatırım kira getirisi oturma izni ev", None),
    ("İskele Long Beach yatırım daire denize yakın bütçe", None),
    ("Mağusa kiralık daire öğrenci arıyorum", None),
    ("Северный Кипр переехать квартира аренда купить район", None),
    ("Северный Кипр квартира бюджет фунтов рассрочка готовая квартира", None),
    ("Северный Кипр инвестиции доход от аренды цены недвижимость", None),
    ("Искеле Long Beach квартира у моря сколько стоит где лучше купить", None),
    ("Северный Кипр ВНЖ через недвижимость квартира", None),
]

# Expand the legacy North-Cyprus regex used by the web path.
v5.NORTH_RE = re.compile(
    rf"(?:{v5.NORTH_RE.pattern}|{NC_GEO_RE.pattern}|{NC_GEO_RU_RE.pattern})",
    re.I,
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def has_nc_geo(text: str) -> bool:
    return bool(NC_GEO_RE.search(text or "") or NC_GEO_RU_RE.search(text or ""))


def detect_language(text: str) -> str:
    value = str(text or "")
    if re.search(r"[а-яё]", value, re.I):
        return "RU"
    low = value.casefold()
    if re.search(r"[çğıöşüİı]", value) or any(x in low for x in (" arıyorum", " bakıyorum", " taşın", " yatırım", " daire", " kiralık", " oturma izni")):
        return "TR"
    if re.search(r"[a-z]", value, re.I):
        return "EN"
    return "OTHER"


def extract_region(text: str) -> str:
    mapping = [
        ("Long Beach", r"long\s+beach|лонг\s+бич"),
        ("İskele", r"iskele|i̇skele|trikomo|искел\w*"),
        ("Gazimağusa", r"famagust\w*|gazima[ğg]usa|ma[ğg]usa|фамагуст\w*"),
        ("Girne", r"kyrenia|girne|гирн\w*"),
        ("Alsancak", r"alsancak|алсанджак"),
        ("Lapta", r"lapta|лапт\w*"),
        ("Esentepe", r"esentepe|эсентеп\w*"),
        ("Tatlısu", r"tatl[ıi]su|татлысу"),
        ("Bafra", r"bafra|бафр\w*"),
        ("Yeniboğaziçi", r"yenibo[ğg]azi[çc]i"),
        ("Boğaz", r"bo[ğg]az|боаз\w*"),
        ("Lefke", r"lefke|лефк\w*"),
        ("Güzelyurt", r"g[üu]zelyurt|morphou|гюзельюрт"),
        ("Ercan", r"ercan"),
        ("Lefkoşa", r"lefko[şs]a|nicosia\s+north"),
    ]
    for label, pattern in mapping:
        if re.search(pattern, text or "", re.I):
            return label
    return ""


def extract_budget(text: str) -> str:
    patterns = [
        r"(?:£|€|\$)\s?\d[\d\s,.]*(?:k|m)?",
        r"\b\d[\d\s,.]*(?:k)?\s?(?:gbp|eur|usd|pounds?|euros?|dollars?|фунт\w*)\b",
        r"\b\d[\d\s,.]*\s*bin\s*(?:£|gbp|pound|pounds?|sterlin)?\b",
        r"\b(?:budget|b[üu]t[çc]e|бюджет)\s*[:\-]?\s*((?:£|€|\$)?\s?\d[\d\s,.]*(?:k|m)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "", re.I)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip()
    return ""


def criteria(text: str) -> list[str]:
    out: list[str] = []
    if ROOM_RE.search(text or ""):
        m = ROOM_RE.search(text or "")
        out.append(f"ROOM:{m.group(0).strip()}" if m else "ROOM")
    if SEA_RE.search(text or ""):
        out.append("NEAR_SEA")
    if FURNISHED_RE.search(text or ""):
        out.append("FURNISHED")
    if PURCHASE_QUALIFIER_RE.search(text or ""):
        if re.search(r"ko[çc]an|tapu|title\s+deed|deed", text or "", re.I):
            out.append("TITLE_DEED")
        if re.search(r"taksit|payment\s+plan|рассроч", text or "", re.I):
            out.append("PAYMENT_PLAN")
        if re.search(r"haz[ıi]r\s+teslim|ready\s+to\s+move|готов", text or "", re.I):
            out.append("READY_TO_MOVE")
    if RESIDENCY_RE.search(text or ""):
        out.append("RESIDENCY")
    return list(dict.fromkeys(out))


def _hard_reject(text: str, author: str = "") -> str:
    if radar.TG_BOT_AUTHOR_RE.search(author or ""):
        return "bot_author"
    if batch_guard.is_nonproperty_goods_request(text):
        return "nonproperty_goods"
    if radar.TG_SERVICE_REQUEST_RE.search(text):
        return "service_request"
    if radar.TG_STRONG_SUPPLY_RE.search(text) or SUPPLY_STRONG_RE.search(text):
        # Explicit first-person demand overrides incidental words such as
        # "agent" or "for sale" inside a question.
        if not (BUY_RE.search(text) or RENT_DEMAND_RE.search(text) or DEMAND_RE.search(text)):
            return "supply_or_agent"
    return ""


def _specificity(text: str) -> int:
    return sum(
        int(bool(x))
        for x in (
            extract_budget(text),
            extract_region(text),
            TIME_RE.search(text or ""),
            ROOM_RE.search(text or ""),
            SEA_RE.search(text or ""),
            FURNISHED_RE.search(text or ""),
            PURCHASE_QUALIFIER_RE.search(text or ""),
        )
    )


def classify_text(text: str, *, group: str = "", author: str = "", explicit_geo: bool | None = None) -> tuple[dict[str, Any] | None, str]:
    own = str(text or "").strip()
    if not own:
        return None, "empty"

    reject = _hard_reject(own, author)
    if reject:
        return None, reject

    north_group = bool(DIRECT_NORTH_GROUP_RE.search(group or ""))
    generic_cyprus = bool(GENERIC_CYPRUS_GROUP_RE.search(group or ""))
    if explicit_geo is None:
        explicit_geo = has_nc_geo(own)

    if not north_group and not explicit_geo:
        return None, "no_north_context"
    if generic_cyprus and not north_group and SOUTH_ONLY_RE.search(own) and not explicit_geo:
        return None, "south_only"

    has_property = bool(PROPERTY_RE.search(own))
    buy = bool(BUY_RE.search(own))
    rent = bool(RENT_DEMAND_RE.search(own))
    relocation = bool(RELOCATION_RE.search(own))
    investor = bool(INVESTOR_RE.search(own))
    research = bool(RESEARCH_RE.search(own))
    residency = bool(RESIDENCY_RE.search(own))
    demand = bool(DEMAND_RE.search(own))
    qualifier = bool(PURCHASE_QUALIFIER_RE.search(own))
    specificity = _specificity(own)

    # Nothing housing/relocation/investment-shaped reached the semantic stage.
    if not any((has_property, buy, rent, relocation, investor, research, residency, qualifier)):
        return None, "no_housing_intent_signal"

    intent_type = "WATCH"
    lead_class = "WATCH"
    score = 46
    reasons: list[str] = []

    if rent:
        intent_type = "TENANT"
        lead_class = "HOT TENANT" if specificity >= 1 else "WATCH"
        score = 78 + min(16, specificity * 4)
        reasons.append("explicit_rental_demand")
    elif buy:
        intent_type = "BUYER"
        lead_class = "HOT BUYER" if specificity >= 1 else "WARM BUYER"
        score = 78 + min(18, specificity * 4)
        reasons.append("explicit_purchase_intent")
    elif investor and (has_property or research or explicit_geo):
        intent_type = "INVESTOR"
        lead_class = "INVESTOR"
        score = 68 + min(20, specificity * 4)
        reasons.append("investment_or_yield_research")
    elif relocation:
        intent_type = "RELOCATION"
        lead_class = "RELOCATION"
        score = 62 + min(18, specificity * 4)
        reasons.append("north_cyprus_relocation")
    elif has_property and (research or residency or qualifier):
        intent_type = "BUYER"
        lead_class = "WARM BUYER"
        score = 64 + min(20, specificity * 4)
        reasons.append("property_research_signal")
    elif has_property and demand:
        intent_type = "WATCH"
        lead_class = "WATCH"
        score = 58 + min(16, specificity * 4)
        reasons.append("ambiguous_property_demand")
    elif research or residency:
        intent_type = "WATCH"
        lead_class = "WATCH"
        score = 52 + min(14, specificity * 3)
        reasons.append("early_research_signal")
    else:
        return None, "weak_unresolved_signal"

    if investor and "investment_or_yield_research" not in reasons:
        reasons.append("investment_secondary")
    if residency:
        reasons.append("residency_signal")
    if extract_budget(own):
        reasons.append("budget_present")
    if extract_region(own):
        reasons.append("region_present")

    return {
        "intent_type": intent_type,
        "lead_class": lead_class,
        "intent_score": min(98, score),
        "language": detect_language(own),
        "estimated_region": extract_region(own),
        "estimated_budget": extract_budget(own),
        "important_criteria": criteria(own),
        "lead_reasons": reasons,
        "specificity": specificity,
    }, "accepted"


def candidate_signal(text: str) -> bool:
    return bool(
        PROPERTY_RE.search(text or "")
        or BUY_RE.search(text or "")
        or RENT_DEMAND_RE.search(text or "")
        or RELOCATION_RE.search(text or "")
        or INVESTOR_RE.search(text or "")
        or RESEARCH_RE.search(text or "")
        or RESIDENCY_RE.search(text or "")
        or PURCHASE_QUALIFIER_RE.search(text or "")
    )


# ---------------------------------------------------------------------------
# Debug counters
# ---------------------------------------------------------------------------

DEBUG: dict[str, Any] = {
    "version": VERSION,
    "messages_scanned": 0,
    "groups_total": 0,
    "groups_relevant": 0,
    "geography_pass": 0,
    "signal_pass": 0,
    "accepted": 0,
    "already_notified": 0,
    "reject_reasons": Counter(),
    "accepted_classes": Counter(),
    "languages": Counter(),
    "groups": Counter(),
    "web_raw_by_source": Counter(),
    "web_accepted": 0,
    "web_reject_reasons": Counter(),
    "errors": [],
}


def _group_scope(group: str) -> tuple[bool, bool, bool]:
    return (
        bool(DIRECT_NORTH_GROUP_RE.search(group or "")),
        bool(GENERIC_CYPRUS_GROUP_RE.search(group or "")),
        bool(THEMATIC_GROUP_RE.search(group or "")),
    )


def _base_candidate(group: str, entity: Any, msg: Any, started: datetime) -> dict[str, Any]:
    text = str(getattr(msg, "message", "") or "").strip()
    return {
        "source": "Telegram",
        "platform": "Telegram",
        "source_type": "joined_group_broad_recall",
        "group": group,
        "group_priority": core.tg_priority(group),
        "group_username": getattr(entity, "username", None) or "",
        "message_id": getattr(msg, "id", 0),
        "message_time": getattr(msg, "date", None).isoformat(timespec="seconds") if getattr(msg, "date", None) else "",
        "author": core.tg_sender(msg),
        "message": text,
        "url": core.tg_link(entity, getattr(msg, "id", 0)),
        "market": "north_cyprus",
        "found_at": started.isoformat(),
    }


async def broad_telegram_scan(db_client, started):
    if not core.TELEGRAM_API_ID or not core.TELEGRAM_API_HASH:
        DEBUG["errors"].append("telegram_missing_api_credentials")
        return {"status": "skipped", "groups": 0, "messages": 0, "hot_warm": 0, "errors": 0, "new_leads": []}
    if not core.TELEGRAM_SESSION.exists():
        DEBUG["errors"].append("telegram_missing_session")
        return {"status": "skipped_no_session", "groups": 0, "messages": 0, "hot_warm": 0, "errors": 0, "new_leads": []}

    client = core.TelegramClient(str(core.TELEGRAM_SESSION), core.TELEGRAM_API_ID, core.TELEGRAM_API_HASH)
    accepted: list[dict[str, Any]] = []
    errors = 0
    try:
        await client.connect()
        if not await client.is_user_authorized():
            DEBUG["errors"].append("telegram_session_unauthorized")
            return {"status": "skipped_unauthorized", "groups": 0, "messages": 0, "hot_warm": 0, "errors": 0, "new_leads": []}

        dialogs = []
        async for dialog in client.iter_dialogs():
            if getattr(dialog, "is_group", False):
                dialogs.append(dialog)
        DEBUG["groups_total"] = len(dialogs)

        dialogs.sort(
            key=lambda d: (
                0 if _group_scope(d.name or "")[0] else 1,
                0 if _group_scope(d.name or "")[1] else 1,
                0 if _group_scope(d.name or "")[2] else 1,
                core.tg_norm(d.name or ""),
            )
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=core.TELEGRAM_HOURS)

        for dialog in dialogs:
            entity = dialog.entity
            group = dialog.name or getattr(entity, "username", None) or str(dialog.id)
            direct_north, generic_cyprus, thematic = _group_scope(group)
            if not any((direct_north, generic_cyprus, thematic)):
                continue
            DEBUG["groups_relevant"] += 1

            try:
                async for msg in client.iter_messages(entity, limit=core.TELEGRAM_PER_GROUP_LIMIT):
                    text = str(getattr(msg, "message", "") or "").strip()
                    if not text:
                        continue
                    dt = getattr(msg, "date", None)
                    if not dt:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        break

                    DEBUG["messages_scanned"] += 1
                    DEBUG["groups"][group] += 1
                    explicit_geo = has_nc_geo(text)

                    # Generic Cyprus or thematic groups need message-level North
                    # Cyprus evidence. Direct North-Cyprus groups provide context.
                    if not direct_north and not explicit_geo:
                        DEBUG["reject_reasons"]["no_north_context"] += 1
                        continue
                    if generic_cyprus and SOUTH_ONLY_RE.search(text) and not explicit_geo:
                        DEBUG["reject_reasons"]["south_only"] += 1
                        continue
                    DEBUG["geography_pass"] += 1

                    if not candidate_signal(text):
                        DEBUG["reject_reasons"]["no_candidate_signal"] += 1
                        continue
                    DEBUG["signal_pass"] += 1

                    try:
                        await msg.get_sender()
                    except Exception:
                        pass
                    candidate = _base_candidate(group, entity, msg, started)
                    signal, reason = classify_text(
                        text,
                        group=group,
                        author=candidate.get("author", ""),
                        explicit_geo=explicit_geo,
                    )
                    if signal is None:
                        DEBUG["reject_reasons"][reason] += 1
                        continue

                    stable_id = f"telegram|{dialog.id}|{msg.id}"
                    lead_id = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
                    ref = db_client.collection(core.COLLECTION).document(lead_id)
                    snap = ref.get()
                    if snap.exists:
                        previous = snap.to_dict() or {}
                        if previous.get("v5_notified_at") or previous.get("v6_notified_at"):
                            DEBUG["already_notified"] += 1
                            continue

                    lead = {**candidate, **signal}
                    lead["lead_id"] = lead_id
                    lead["classification"] = "HOT" if signal["lead_class"] in {"HOT BUYER", "HOT TENANT"} else "WARM"
                    lead["telegram_score"] = signal["intent_score"]
                    lead["buyer_signal"] = signal["intent_type"].lower()
                    lead["radar_version"] = VERSION
                    lead["why_selected"] = ", ".join(signal["lead_reasons"])
                    ref.set(lead, merge=True)
                    accepted.append(lead)

                    DEBUG["accepted"] += 1
                    DEBUG["accepted_classes"][signal["lead_class"]] += 1
                    DEBUG["languages"][signal["language"]] += 1
            except core.FloodWaitError as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_flood_wait:{group}:{exc.seconds}")
            except Exception as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_group:{group}:{type(exc).__name__}:{exc}")
            await asyncio.sleep(0.20)

        return {
            "status": "completed",
            "groups": DEBUG["groups_relevant"],
            "messages": DEBUG["messages_scanned"],
            "hot_warm": len(accepted),
            "errors": errors,
            "new_leads": accepted,
            "candidate_first_buyer_signals": DEBUG["signal_pass"],
            "candidate_first_total_groups": DEBUG["groups_total"],
            "candidate_first_already_notified": DEBUG["already_notified"],
        }
    except Exception as exc:
        DEBUG["errors"].append(f"telegram_scan:{type(exc).__name__}:{exc}")
        return {"status": "error", "groups": DEBUG["groups_relevant"], "messages": DEBUG["messages_scanned"], "hot_warm": 0, "errors": errors + 1, "new_leads": []}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Broad web path
# ---------------------------------------------------------------------------

_existing_web_classifier = v5.classify_web
_existing_search = core.exa_search


def search_debug(query: str, include_domains: list[str] | None = None):
    rows = _existing_search(query, include_domains)
    for row in rows:
        DEBUG["web_raw_by_source"][str(row.get("source") or "unknown")] += 1
        row.setdefault("_search_query", query)
    return rows


core.exa_search = search_debug


def broad_web_classifier(item: dict[str, Any]):
    # Preserve strong existing buyer matches first.
    existing = _existing_web_classifier(item)
    if existing is not None:
        existing["intent_type"] = "BUYER"
        existing["lead_class"] = existing.get("lead_class") or ("HOT BUYER" if existing.get("classification") == "HOT" else "WARM BUYER")
        existing["language"] = detect_language(f"{item.get('title','')} {item.get('text','')}")
        existing["estimated_region"] = extract_region(f"{item.get('title','')} {item.get('text','')}")
        existing["estimated_budget"] = extract_budget(f"{item.get('title','')} {item.get('text','')}")
        existing["important_criteria"] = criteria(f"{item.get('title','')} {item.get('text','')}")
        DEBUG["web_accepted"] += 1
        return existing

    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    text = str(item.get("text") or "")
    blob = f"{title} {text[:3200]}"
    if radar._web_listing_url(url) or radar._WEB_LISTING_RE.search(blob):
        DEBUG["web_reject_reasons"]["listing"] += 1
        return None
    if SUPPLY_STRONG_RE.search(blob) and not (BUY_RE.search(blob) or RENT_DEMAND_RE.search(blob) or DEMAND_RE.search(blob)):
        DEBUG["web_reject_reasons"]["supply_or_agent"] += 1
        return None

    explicit_geo = has_nc_geo(blob) or "/r/northcyprus/" in url.casefold()
    signal, reason = classify_text(blob, group="North Cyprus web" if explicit_geo else "", explicit_geo=explicit_geo)
    if signal is None:
        DEBUG["web_reject_reasons"][reason] += 1
        return None

    out = dict(item)
    out.update(signal)
    out["market"] = "north_cyprus"
    out["route_to"] = "Prime Kıbrıs"
    out["classification"] = "HOT" if signal["lead_class"] in {"HOT BUYER", "HOT TENANT"} else "WARM"
    out["credibility_score"] = max(45, min(92, signal["intent_score"] - (8 if not item.get("published") else 0)))
    out["market_fit_score"] = 100
    out["buyer_signal"] = signal["intent_type"].lower()
    out["radar_version"] = VERSION
    out["why_selected"] = ", ".join(signal["lead_reasons"])
    DEBUG["web_accepted"] += 1
    return out


v5.classify_web = broad_web_classifier
core.telegram_buyer_scan = broad_telegram_scan


# ---------------------------------------------------------------------------
# Notification / debug report
# ---------------------------------------------------------------------------

def _clip(value: Any, n: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def notify_lead(lead: dict[str, Any], prefix: str = "NEW") -> bool:
    if str(lead.get("market") or "") != "north_cyprus":
        return False
    lead_class = str(lead.get("lead_class") or "WATCH")
    emoji = "🔥" if lead_class in {"HOT BUYER", "HOT TENANT"} else "🟡" if lead_class in {"WARM BUYER", "INVESTOR", "RELOCATION"} else "👀"
    criteria_text = ", ".join(lead.get("important_criteria") or []) or "-"
    reasons = ", ".join(lead.get("lead_reasons") or []) or "-"
    msg = (
        f"{emoji} LEAD RADAR | {lead_class} [{prefix}]\n\n"
        f"Kullanıcı: {lead.get('author','-') or '-'}\n"
        f"Platform: {lead.get('platform') or lead.get('source','')}\n"
        f"Kaynak/Grup: {lead.get('group') or lead.get('title') or lead.get('source','')}\n"
        f"Dil: {lead.get('language','')} | Intent: {lead.get('intent_score',0)}/100\n"
        f"Bölge: {lead.get('estimated_region') or '-'} | Bütçe: {lead.get('estimated_budget') or '-'}\n"
        f"Kriterler: {criteria_text}\n"
        f"Neden: {reasons}\n\n"
        f"{_clip(lead.get('message') or lead.get('text') or '', 900)}\n\n"
        f"🔗 {lead.get('url','') or 'Doğrudan link yok'}"
    )
    core.telegram(msg[:3900])
    return True


def notify_web(lead: dict[str, Any]) -> None:
    notify_lead(lead, "WEB")


v5.notify_telegram_lead = notify_lead
v5.notify_web_lead = notify_web

# Old backfill is buyer-only. Do not reclassify historical rows with stale V5
# semantics; fresh V6 scans will repopulate all intent classes safely.
v5.backfill_unnotified_telegram = lambda db_client, started: []


def _serializable_debug() -> dict[str, Any]:
    return {
        **{k: v for k, v in DEBUG.items() if not isinstance(v, Counter)},
        "reject_reasons": dict(DEBUG["reject_reasons"]),
        "accepted_classes": dict(DEBUG["accepted_classes"]),
        "languages": dict(DEBUG["languages"]),
        "top_groups": dict(DEBUG["groups"].most_common(30)),
        "web_raw_by_source": dict(DEBUG["web_raw_by_source"]),
        "web_reject_reasons": dict(DEBUG["web_reject_reasons"]),
    }


def save_and_notify_debug() -> None:
    data = _serializable_debug()
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        db = core.db()
        doc_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        db.collection("bay_s_lead_radar_debug").document(doc_id).set(data)
    except Exception as exc:
        DEBUG["errors"].append(f"debug_firestore:{type(exc).__name__}:{exc}")

    rejects = ", ".join(f"{k}:{v}" for k, v in DEBUG["reject_reasons"].most_common(8)) or "-"
    classes = ", ".join(f"{k}:{v}" for k, v in DEBUG["accepted_classes"].most_common()) or "-"
    langs = ", ".join(f"{k}:{v}" for k, v in DEBUG["languages"].most_common()) or "-"
    sources = ", ".join(f"{k}:{v}" for k, v in DEBUG["web_raw_by_source"].most_common()) or "-"
    msg = (
        "🧪 LEAD RADAR DEBUG | SON TARAMA\n\n"
        f"Telegram grup: {DEBUG['groups_relevant']}/{DEBUG['groups_total']}\n"
        f"Telegram mesaj: {DEBUG['messages_scanned']}\n"
        f"Coğrafya geçti: {DEBUG['geography_pass']}\n"
        f"Intent/keyword adayı: {DEBUG['signal_pass']}\n"
        f"Kabul edilen: {DEBUG['accepted']}\n"
        f"Sınıflar: {classes}\n"
        f"Diller: {langs}\n"
        f"Eleme nedenleri: {rejects}\n"
        f"Web ham: {sources}\n"
        f"Web kabul: {DEBUG['web_accepted']}\n"
        f"Hata: {len(DEBUG['errors'])}"
    )
    core.telegram(msg[:3900])
    print("LEAD_RADAR_DEBUG", json.dumps(_serializable_debug(), ensure_ascii=False))


def run() -> None:
    radar.main()
    save_and_notify_debug()


if __name__ == "__main__":
    run()
