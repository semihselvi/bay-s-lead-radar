from __future__ import annotations

import re
from datetime import datetime, timezone

VERSION = "1.0-ocean-intent-core"

PROPERTY_RE = re.compile(
    r"(?:property|real estate|apartment|flat|house|home|villa|condo|land|second home|holiday home|"
    r"immobilie|wohnung|haus|nieruchomość|mieszkanie|bostad|lägenhet|casa|immobile|vivienda|inmueble|"
    r"imóvel|apartamento|bolig|lejlighed|asunto|talo|nemovitost|byt|kinnisvara|korter|عقار|شقة|منزل|"
    r"недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|gayrimenkul|daire|ev)",
    re.I,
)

STRONG_PROPERTY_RE = re.compile(
    r"(?:property|real estate|apartment|flat|house|villa|condo|land|second home|holiday home|"
    r"immobilie|wohnung|haus|nieruchomość|mieszkanie|bostad|lägenhet|casa|immobile|vivienda|inmueble|"
    r"imóvel|apartamento|bolig|lejlighed|asunto|talo|nemovitost|byt|kinnisvara|korter|عقار|شقة|منزل|"
    r"недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|gayrimenkul|daire)",
    re.I,
)

PROPERTY_PURCHASE_LINK_RE = re.compile(
    r"(?:"
    r"(?:buy|buying|purchase|purchasing|invest|investing).{0,90}(?:property|real estate|apartment|flat|house|villa|condo|land|second home|holiday home)|"
    r"(?:property|real estate|apartment|flat|house|villa|condo|land|second home|holiday home).{0,90}(?:buy|buying|purchase|purchasing|invest|investing)"
    r")",
    re.I | re.S,
)

BUY_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,100}\b(?:want|looking|planning|considering|ready|need|seeking|interested|researching|thinking)\b.{0,130}\b(?:buy|buying|purchase|purchasing|invest|investing|property|apartment|house|villa|home)\b|"
    r"\b(?:looking|planning|want|ready|trying|hoping)\s+to\s+(?:buy|purchase|invest)\b|"
    r"\b(?:second home|holiday home)\b.{0,100}\b(?:buy|purchase|budget|mortgage|deposit|invest)\b|"
    r"\b(?:retire|retirement)\b.{0,130}\b(?:buy|purchase|property|home|house|apartment)\b|"
    r"\b(?:budget|deposit|payment plan|mortgage|cash buyer|installments?)\b.{0,130}\b(?:property|apartment|house|villa|home)\b|"
    r"\b(?:ich|wir)\b.{0,90}\b(?:möchte|moechte|wollen|will|suche|suchen|plane|planen|überlege|ueberlege)\b.{0,130}\b(?:kaufen|erwerben|immobilie|wohnung|haus)\b|"
    r"\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,130}\b(?:kupić|nieruchomość|mieszkanie|dom)\b|"
    r"\b(?:jag|vi)\b.{0,90}\b(?:vill|planerar|överväger|söker)\b.{0,130}\b(?:köpa|bostad|lägenhet|hus|fastighet)\b|"
    r"\b(?:io|noi)\b.{0,90}\b(?:voglio|vogliamo|cerco|cerchiamo|penso|pensiamo)\b.{0,130}\b(?:comprare|acquistare|casa|immobile|appartamento)\b|"
    r"\b(?:yo|nosotros)\b.{0,90}\b(?:quiero|queremos|busco|buscamos|pienso|pensamos)\b.{0,130}\b(?:comprar|vivienda|casa|apartamento|inmueble)\b|"
    r"\b(?:eu|nós|nos)\b.{0,90}\b(?:quero|queremos|procuro|procuramos|planejo|planejamos)\b.{0,130}\b(?:comprar|casa|apartamento|imóvel)\b|"
    r"\b(?:я|мы)\b.{0,90}\b(?:хочу|хотим|ищу|ищем|планирую|планируем|рассматриваю|думаю)\b.{0,130}\b(?:купить|покупк\w*|приобрест\w*|квартир\w*|недвижимост\w*)\b|"
    r"\b(?:ben|biz)\b.{0,90}\b(?:almak istiyorum|almayı düşünüyorum|almayi dusunuyorum|satın almak|satin almak)\b|"
    r"(?:أريد|نريد|أبحث|نبحث|أخطط|نخطط).{0,130}(?:شراء|عقار|شقة|منزل)"
    r")",
    re.I | re.S,
)

CONCRETE_RE = re.compile(
    r"(?:[£€$]\s*\d[\d\s.,]*(?:k|m)?|\b\d{2,4}\s*k\b|\bbudget\b|\bdeposit\b|"
    r"\bmortgage\b|\bpayment plan\b|\binstallments?\b|\bcash buyer\b|\bthis year\b|\bnext year\b|"
    r"\bwithin \d+ months?\b|\bready to buy\b)",
    re.I,
)

RENT_RE = re.compile(
    r"(?:\blooking to rent\b|\bfor rent\b|\brenting\b|\brental only\b|\bmonthly rent\b|\bper month\b|"
    r"\bаренд\w*\b|\bснять\b|\bсниму\b|\bkiralık\b|\bkiralam\w*\b|\bzu mieten\b|\bmietwohnung\b)",
    re.I,
)

PURCHASE_VERB_RE = re.compile(
    r"(?:\bbuy\b|\bbuying\b|\bpurchase\b|\bpurchasing\b|\binvest\b|\binvesting\b|"
    r"\bkaufen\b|\berwerben\b|\bkupić\b|\bköpa\b|\bcomprare\b|\bacquistare\b|"
    r"\bcomprar\b|\bкупить\b|\bприобрест\w*\b|\bsatın almak\b|\bsatin almak\b|"
    r"شراء)",
    re.I,
)

SELLER_RE = re.compile(
    r"(?:\bfor sale\b|\breal estate agent\b|\bestate agent\b|\brealtor\b|\bbroker\b|"
    r"\bdeveloper\b|\bcontact me\b|\bdm me\b|\bwhatsapp\b|\bour project\b|\bour properties\b|"
    r"\bavailable units?\b|\bprice from\b|\bmy client\b|\bпродаю\b|\bагент\w*\b|\bриэлтор\w*\b|"
    r"\bemlak danışman\w*\b|\bsatılık\b)",
    re.I,
)

PAST_RE = re.compile(
    r"(?:\bi already bought\b|\bwe already bought\b|\bi purchased\b|\bwe purchased\b|"
    r"\bi own (?:a|an)\b|\balready purchased\b|\bno longer looking\b|\bкупил\b|\bкупили\b|"
    r"\bsatın aldım\b|\bgekauft\b)",
    re.I,
)


def clean(value: str) -> str:
    return " ".join(str(value or "").split())


def classify_candidate(item: dict):
    body = clean(item.get("text", ""))
    text = clean(f"{item.get('title','')} {body}")
    if not text:
        return None, "empty"
    if SELLER_RE.search(text):
        return None, "seller_or_agent"

    # For YouTube comments, the video itself can establish property context,
    # but BUY intent must come from the comment author, not the video title.
    intent_text = body if item.get("source") == "YouTube Comment" else text
    explicit_buy = bool(BUY_RE.search(intent_text))

    if RENT_RE.search(intent_text) and not PURCHASE_VERB_RE.search(intent_text):
        return None, "rental"
    if PAST_RE.search(intent_text) and not explicit_buy:
        return None, "past_purchase"

    has_property = bool(
        STRONG_PROPERTY_RE.search(text)
        or PROPERTY_PURCHASE_LINK_RE.search(intent_text)
        or item.get("context_property")
    )
    if not has_property:
        return None, "no_property"
    if not explicit_buy:
        return None, "no_explicit_purchase_intent"

    # Generic finance/investing talk must not become a property buyer merely
    # because it also contains an unrelated phrase such as "back home".
    if not item.get("context_property") and not PROPERTY_PURCHASE_LINK_RE.search(intent_text):
        if re.search(r"\binvest(?:ing|ment)?\b", intent_text, re.I) and not re.search(
            r"\b(?:buy|buying|purchase|purchasing|kaufen|kupić|köpa|comprare|comprar|купить|satın almak|satin almak|شراء)\b",
            intent_text,
            re.I,
        ):
            return None, "generic_investing"

    concrete = bool(CONCRETE_RE.search(text))
    return {
        **item,
        "classification": "HOT" if concrete else "WARM",
        "intent_score": 95 if concrete else 85,
        "credibility_score": int(item.get("credibility_score") or 82),
        "buyer_stage": "DIRECT",
        "buyer_signal": item.get("buyer_signal") or "ocean_purchase_intent",
        "market": item.get("market") or "global_abroad",
        "route_to": "Prime Kıbrıs",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }, "accepted"
