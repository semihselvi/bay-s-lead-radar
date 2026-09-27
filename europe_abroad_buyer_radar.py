from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from google.cloud import firestore
from google.oauth2 import service_account

VERSION = "1.1-global-ocean-discovery"
PROFILE = os.getenv("ABROAD_RADAR_PROFILE", "germany_abroad").strip().lower()
LOOKBACK_DAYS = int(os.getenv("ABROAD_RADAR_LOOKBACK_DAYS", "7"))
QUERY_LIMIT = int(os.getenv("ABROAD_RADAR_QUERY_LIMIT", "10"))
NOTIFIED_COLLECTION = "bay_s_abroad_buyer_notified"
SCAN_COLLECTION = "bay_s_abroad_buyer_scans"

USER_DOMAINS = {
    "reddit.com", "old.reddit.com", "expat.com", "expatforum.com", "nomadgate.com",
    "auswandererforum.de", "wertpapier-forum.de", "wiwi-treff.de", "finanztip.de",
    "tweakers.net", "forum.fok.nl", "pim.be", "bouwinfo.be", "englishforum.ch",
    "internations.org", "bogleheads.org", "moneysavingexpert.com",
}

PROFILES = {
    "germany_abroad": {
        "icon": "🇩🇪", "title": "GERMANY RESIDENTS BUYING ABROAD", "hl": "de", "gl": "de",
        "audience_re": re.compile(r"(?:\bi live in germany\b|\bwe live in germany\b|\bfrom germany\b|\bals deutscher\b|\bals deutsche\b|\bich wohne in deutschland\b|\bwir wohnen in deutschland\b|\bich lebe in deutschland\b|\bwir leben in deutschland\b|\bdeutscher staatsb[üu]rger\b)", re.I),
        "query_anchor": re.compile(r"(?:deutschland|germany|german|deutsch)", re.I),
        "bridge_domains": {"auswandererforum.de", "wertpapier-forum.de", "wiwi-treff.de", "finanztip.de", "reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com Germany "buy property abroad" "I"',
            'site:reddit.com/r/germany "buy a house abroad"',
            'site:auswandererforum.de "Immobilie im Ausland kaufen"',
            'site:wertpapier-forum.de Auslandsimmobilie kaufen',
            'site:wiwi-treff.de Auslandsimmobilie kaufen',
            'site:expat.com Germany "buy property abroad" forum',
            'Deutschland "ich möchte" "Immobilie im Ausland kaufen"',
            'Deutschland "wir wollen" "Ferienwohnung im Ausland kaufen"',
            'Deutschland "Nordzypern" "ich möchte kaufen"',
            'Deutschland "North Cyprus" "looking to buy" property',
        ],
    },
    "netherlands_abroad": {
        "icon": "🇳🇱", "title": "NETHERLANDS RESIDENTS BUYING ABROAD", "hl": "nl", "gl": "nl",
        "audience_re": re.compile(r"(?:\bi live in the netherlands\b|\bwe live in the netherlands\b|\bfrom the netherlands\b|\bik woon in nederland\b|\bwij wonen in nederland\b|\bwe wonen in nederland\b|\bik leef in nederland\b|\bnederlander\b)", re.I),
        "query_anchor": re.compile(r"(?:nederland|netherlands|dutch)", re.I),
        "bridge_domains": {"tweakers.net", "forum.fok.nl", "reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com Netherlands "buy property abroad"',
            'site:reddit.com/r/Netherlands "second home abroad" buy',
            'site:tweakers.net "huis in het buitenland kopen"',
            'site:forum.fok.nl "huis in het buitenland kopen"',
            'site:expat.com Netherlands "buy property abroad" forum',
            'Nederland "ik wil een huis in het buitenland kopen"',
            'Nederland "wij willen vastgoed in het buitenland kopen"',
            'Nederland "tweede huis in het buitenland" kopen forum',
            'Nederland "Noord Cyprus" woning kopen',
            'Nederland "North Cyprus" property buy forum',
        ],
    },
    "belgium_abroad": {
        "icon": "🇧🇪", "title": "BELGIUM RESIDENTS BUYING ABROAD", "hl": "nl", "gl": "be",
        "audience_re": re.compile(r"(?:\bi live in belgium\b|\bwe live in belgium\b|\bfrom belgium\b|\bik woon in belgi[ëe]\b|\bwij wonen in belgi[ëe]\b|\bje vis en belgique\b|\bnous vivons en belgique\b|\bbelgian resident\b)", re.I),
        "query_anchor": re.compile(r"(?:belgi[ëe]|belgique|belgium|belgian)", re.I),
        "bridge_domains": {"pim.be", "bouwinfo.be", "reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com Belgium "buy property abroad"',
            'site:reddit.com/r/belgium "second home abroad"',
            'site:pim.be vastgoed buitenland kopen',
            'site:pim.be immobilier étranger acheter',
            'site:expat.com Belgium "buy property abroad" forum',
            'België "ik wil een huis in het buitenland kopen"',
            'Belgique "je veux acheter un bien à l’étranger"',
            'Belgique "résidence secondaire à l’étranger" acheter',
            'België "Noord Cyprus" woning kopen',
            'Belgique "Chypre du Nord" acheter immobilier',
        ],
    },
    "switzerland_abroad": {
        "icon": "🇨🇭", "title": "SWITZERLAND RESIDENTS BUYING ABROAD", "hl": "de", "gl": "ch",
        "audience_re": re.compile(r"(?:\bi live in switzerland\b|\bwe live in switzerland\b|\bfrom switzerland\b|\bich wohne in der schweiz\b|\bwir wohnen in der schweiz\b|\bje vis en suisse\b|\bnous vivons en suisse\b|\bswiss resident\b)", re.I),
        "query_anchor": re.compile(r"(?:schweiz|suisse|switzerland|swiss)", re.I),
        "bridge_domains": {"englishforum.ch", "reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com Switzerland "buy property abroad"',
            'site:reddit.com/r/Switzerland "second home abroad"',
            'site:englishforum.ch property abroad buy',
            'site:englishforum.ch second home abroad',
            'site:expat.com Switzerland "buy property abroad" forum',
            'Schweiz "ich möchte eine Immobilie im Ausland kaufen"',
            'Suisse "je veux acheter immobilier à l’étranger"',
            'Schweiz "Ferienwohnung im Ausland kaufen" Forum',
            'Schweiz "Nordzypern" Immobilie kaufen',
            'Suisse "Chypre du Nord" acheter immobilier',
        ],
    },
,
    "uk_abroad": {
        "icon": "🇬🇧", "title": "UK RESIDENTS BUYING ABROAD", "hl": "en", "gl": "uk",
        "audience_re": re.compile(r"(?:\bi live in (?:the )?uk\b|\bwe live in (?:the )?uk\b|\bfrom (?:the )?uk\b|\bi live in britain\b|\bwe live in britain\b|\bbritish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:\buk\b|united kingdom|britain|british)", re.I),
        "bridge_domains": {"moneysavingexpert.com", "reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/AskUK "buy property abroad"',
            'site:reddit.com/r/UKPersonalFinance "property abroad" buy',
            'site:moneysavingexpert.com "property abroad" buy forum',
            'UK "looking to buy property abroad"',
            'UK "second home abroad" buying',
            'British "want to buy" "property abroad"',
            '"retire abroad" "buy property" UK',
            '"Mediterranean property" "looking to buy" UK',
            '"property abroad" "budget" UK forum',
            '"North Cyprus" "looking to buy" UK',
        ],
    },
    "ireland_abroad": {
        "icon": "🇮🇪", "title": "IRELAND RESIDENTS BUYING ABROAD", "hl": "en", "gl": "ie",
        "audience_re": re.compile(r"(?:\bi live in ireland\b|\bwe live in ireland\b|\bfrom ireland\b|\birish resident\b|\bi am irish\b)", re.I),
        "query_anchor": re.compile(r"(?:ireland|irish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/ireland "buy property abroad"',
            'site:reddit.com/r/irishpersonalfinance "property abroad"',
            'Ireland "looking to buy property abroad"',
            'Ireland "second home abroad" buy',
            'Irish "want to buy" property abroad',
            '"retire abroad" property Ireland',
            '"Mediterranean property" Ireland buy',
            '"property abroad" budget Ireland forum',
            '"holiday home abroad" Ireland buy',
            '"North Cyprus" Irish buyer property',
        ],
    },
    "poland_abroad": {
        "icon": "🇵🇱", "title": "POLAND RESIDENTS BUYING ABROAD", "hl": "pl", "gl": "pl",
        "audience_re": re.compile(r"(?:\bmieszkam w polsce\b|\bmieszkamy w polsce\b|\bjestem z polski\b|\bfrom poland\b|\bi live in poland\b|\bpolish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:polska|poland|polish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/poland "buy property abroad"',
            'site:reddit.com/r/Polska "nieruchomość za granicą" kupić',
            'Polska "chcę kupić nieruchomość za granicą"',
            'Polska "mieszkanie za granicą" kupić',
            'Polska "dom za granicą" kupić',
            '"nieruchomość za granicą" budżet Polska',
            '"drugi dom za granicą" Polska',
            '"nieruchomość nad morzem" za granicą Polska',
            '"Cypr Północny" kupić mieszkanie',
            '"North Cyprus" Polish buyer property',
        ],
    },
    "sweden_abroad": {
        "icon": "🇸🇪", "title": "SWEDEN RESIDENTS BUYING ABROAD", "hl": "sv", "gl": "se",
        "audience_re": re.compile(r"(?:\bjag bor i sverige\b|\bvi bor i sverige\b|\bfrån sverige\b|\bfrom sweden\b|\bi live in sweden\b|\bswedish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:sverige|sweden|swedish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/sweden "buy property abroad"',
            'site:reddit.com/r/TillSverige "property abroad" buy',
            'Sverige "köpa bostad utomlands"',
            'Sverige "köpa hus utomlands"',
            'Sverige "lägenhet utomlands" köpa',
            '"bostad utomlands" budget Sverige',
            '"andra hem utomlands" Sverige',
            '"Mediterranean property" Sweden buy',
            '"Norra Cypern" köpa lägenhet',
            '"North Cyprus" Swedish buyer property',
        ],
    },
    "italy_abroad": {
        "icon": "🇮🇹", "title": "ITALY RESIDENTS BUYING ABROAD", "hl": "it", "gl": "it",
        "audience_re": re.compile(r"(?:\bvivo in italia\b|\bviviamo in italia\b|\bsono italiano\b|\bsono italiana\b|\bfrom italy\b|\bi live in italy\b|\bitalian resident\b)", re.I),
        "query_anchor": re.compile(r"(?:italia|italy|italian)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/italy "buy property abroad"',
            'Italia "voglio comprare casa all estero"',
            'Italia "comprare immobile all estero"',
            'Italia "seconda casa all estero"',
            '"casa all estero" budget Italia',
            '"investire in immobili all estero" Italia',
            '"casa al mare all estero" comprare Italia',
            '"Mediterranean property" Italy buy',
            '"Cipro del Nord" comprare casa',
            '"North Cyprus" Italian buyer property',
        ],
    },
    "spain_abroad": {
        "icon": "🇪🇸", "title": "SPAIN RESIDENTS BUYING ABROAD", "hl": "es", "gl": "es",
        "audience_re": re.compile(r"(?:\bvivo en españa\b|\bvivimos en españa\b|\bsoy español\b|\bsoy española\b|\bfrom spain\b|\bi live in spain\b|\bspanish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:españa|spain|spanish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/spain "buy property abroad"',
            'España "quiero comprar casa en el extranjero"',
            'España "comprar vivienda en el extranjero"',
            'España "segunda residencia en el extranjero"',
            '"casa en el extranjero" presupuesto España',
            '"invertir en vivienda en el extranjero" España',
            '"propiedad mediterránea" comprar España',
            '"casa barata en el extranjero" España',
            '"Chipre del Norte" comprar vivienda',
            '"North Cyprus" Spanish buyer property',
        ],
    },
    "portugal_abroad": {
        "icon": "🇵🇹", "title": "PORTUGAL RESIDENTS BUYING ABROAD", "hl": "pt", "gl": "pt",
        "audience_re": re.compile(r"(?:\bvivo em portugal\b|\bvivemos em portugal\b|\bsou português\b|\bsou portuguesa\b|\bfrom portugal\b|\bi live in portugal\b|\bportuguese resident\b)", re.I),
        "query_anchor": re.compile(r"(?:portugal|portuguese|português|portuguesa)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/portugal "buy property abroad"',
            'Portugal "quero comprar casa no estrangeiro"',
            'Portugal "comprar imóvel no estrangeiro"',
            'Portugal "segunda casa no estrangeiro"',
            '"casa no estrangeiro" orçamento Portugal',
            '"investir em imóveis no estrangeiro" Portugal',
            '"casa no mediterrâneo" comprar Portugal',
            '"property abroad" Portugal budget',
            '"Chipre do Norte" comprar apartamento',
            '"North Cyprus" Portuguese buyer property',
        ],
    },
    "uae_abroad": {
        "icon": "🇦🇪", "title": "UAE RESIDENTS BUYING ABROAD", "hl": "en", "gl": "ae",
        "audience_re": re.compile(r"(?:\bi live in (?:the )?uae\b|\bwe live in (?:the )?uae\b|\bi live in dubai\b|\bwe live in dubai\b|\buae resident\b|\bdubai resident\b)", re.I),
        "query_anchor": re.compile(r"(?:\buae\b|dubai|united arab emirates)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/dubai "buy property abroad"',
            'site:reddit.com/r/UAE "property abroad" buy',
            'Dubai resident "looking to buy property abroad"',
            'UAE resident "second home abroad"',
            'Dubai "want to buy" Mediterranean property',
            'UAE "holiday home abroad" buy',
            'Dubai "property abroad" budget',
            'UAE "investment property abroad"',
            'Dubai "North Cyprus" property buy',
            'UAE resident "payment plan" property abroad',
        ],
    }    "global_abroad": {
        "icon": "🌍", "title": "GLOBAL BUYERS LOOKING ABROAD", "hl": "en", "gl": "us",
        "audience_re": None,
        "query_anchor": re.compile(r"(?:property abroad|buy abroad|second home abroad|retire abroad|mediterranean property|overseas property)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com", "internations.org", "nomadgate.com", "bogleheads.org", "moneysavingexpert.com"},
        "queries": [
            'site:reddit.com "looking to buy property abroad"',
            'site:reddit.com "want to buy property abroad"',
            'site:reddit.com "second home abroad" "I"',
            'site:reddit.com "retire abroad" "buy property"',
            'site:reddit.com "Mediterranean property" "looking to buy"',
            'site:expat.com "buy property abroad" forum',
            'site:expatforum.com "second home abroad" buy',
            '"property abroad" "budget" forum',
            '"overseas property" "payment plan"',
            '"property abroad" "under €150,000"',
            '"Mediterranean apartment" "want to buy"',
            '"holiday home abroad" "looking to buy"',
        ],
    },
    "norway_abroad": {
        "icon": "🇳🇴", "title": "NORWAY RESIDENTS BUYING ABROAD", "hl": "no", "gl": "no",
        "audience_re": re.compile(r"(?:\bjeg bor i norge\b|\bvi bor i norge\b|\bfra norge\b|\bfrom norway\b|\bi live in norway\b|\bnorwegian resident\b)", re.I),
        "query_anchor": re.compile(r"(?:norge|norway|norwegian)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/norge "buy property abroad"',
            'Norge "kjøpe bolig i utlandet"',
            'Norge "kjøpe hus i utlandet"',
            'Norge "feriebolig i utlandet" kjøpe',
            '"bolig i utlandet" budsjett Norge',
            '"investere i eiendom i utlandet" Norge',
            '"andre bolig i utlandet" Norge',
            '"Mediterranean property" Norway buy',
            '"Nord-Kypros" kjøpe leilighet',
            '"North Cyprus" Norwegian buyer property',
        ],
    },
    "denmark_abroad": {
        "icon": "🇩🇰", "title": "DENMARK RESIDENTS BUYING ABROAD", "hl": "da", "gl": "dk",
        "audience_re": re.compile(r"(?:\bjeg bor i danmark\b|\bvi bor i danmark\b|\bfra danmark\b|\bfrom denmark\b|\bi live in denmark\b|\bdanish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:danmark|denmark|danish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/Denmark "buy property abroad"',
            'Danmark "købe bolig i udlandet"',
            'Danmark "købe hus i udlandet"',
            'Danmark "feriebolig i udlandet" købe',
            '"bolig i udlandet" budget Danmark',
            '"investere i ejendom i udlandet" Danmark',
            '"anden bolig i udlandet" Danmark',
            '"Mediterranean property" Denmark buy',
            '"Nordcypern" købe lejlighed',
            '"North Cyprus" Danish buyer property',
        ],
    },
    "finland_abroad": {
        "icon": "🇫🇮", "title": "FINLAND RESIDENTS BUYING ABROAD", "hl": "fi", "gl": "fi",
        "audience_re": re.compile(r"(?:\basun suomessa\b|\basumme suomessa\b|\bsuomesta\b|\bfrom finland\b|\bi live in finland\b|\bfinnish resident\b)", re.I),
        "query_anchor": re.compile(r"(?:suomi|suomessa|finland|finnish)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/Finland "buy property abroad"',
            'Suomi "ostaa asunto ulkomailta"',
            'Suomi "ostaa talo ulkomailta"',
            'Suomi "loma-asunto ulkomailla" ostaa',
            '"asunto ulkomailla" budjetti Suomi',
            '"sijoittaa kiinteistöön ulkomailla" Suomi',
            '"toinen koti ulkomailla" Suomi',
            '"Mediterranean property" Finland buy',
            '"Pohjois-Kypros" ostaa asunto',
            '"North Cyprus" Finnish buyer property',
        ],
    },
    "czechia_abroad": {
        "icon": "🇨🇿", "title": "CZECHIA RESIDENTS BUYING ABROAD", "hl": "cs", "gl": "cz",
        "audience_re": re.compile(r"(?:\bžiji v česku\b|\bžijeme v česku\b|\bz česka\b|\bfrom czechia\b|\bi live in czechia\b|\bczech resident\b)", re.I),
        "query_anchor": re.compile(r"(?:česko|česká|czechia|czech)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/czech "buy property abroad"',
            'Česko "koupit nemovitost v zahraničí"',
            'Česko "koupit byt v zahraničí"',
            'Česko "druhý domov v zahraničí"',
            '"nemovitost v zahraničí" rozpočet Česko',
            '"investovat do nemovitosti v zahraničí" Česko',
            '"apartmán u moře" zahraničí koupit',
            '"Mediterranean property" Czechia buy',
            '"Severní Kypr" koupit byt',
            '"North Cyprus" Czech buyer property',
        ],
    },
    "estonia_abroad": {
        "icon": "🇪🇪", "title": "ESTONIA RESIDENTS BUYING ABROAD", "hl": "et", "gl": "ee",
        "audience_re": re.compile(r"(?:\belan eestis\b|\belame eestis\b|\beestist\b|\bfrom estonia\b|\bi live in estonia\b|\bestonian resident\b)", re.I),
        "query_anchor": re.compile(r"(?:eesti|estonia|estonian)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'site:reddit.com/r/Eesti "buy property abroad"',
            'Eesti "osta kinnisvara välismaal"',
            'Eesti "osta korter välismaal"',
            'Eesti "teine kodu välismaal"',
            '"kinnisvara välismaal" eelarve Eesti',
            '"investeerida kinnisvarasse välismaal" Eesti',
            '"korter mere ääres" välismaal Eesti',
            '"Mediterranean property" Estonia buy',
            '"Põhja-Küpros" osta korter',
            '"North Cyprus" Estonian buyer property',
        ],
    },
    "uae_arabic_abroad": {
        "icon": "🇦🇪", "title": "ARABIC-SPEAKING UAE RESIDENTS BUYING ABROAD", "hl": "ar", "gl": "ae",
        "audience_re": re.compile(r"(?:أعيش في الإمارات|نعيش في الإمارات|أعيش في دبي|نعيش في دبي|مقيم في الإمارات|مقيم في دبي)", re.I),
        "query_anchor": re.compile(r"(?:الإمارات|دبي|uae|dubai)", re.I),
        "bridge_domains": {"reddit.com", "expat.com", "expatforum.com"},
        "queries": [
            'الإمارات "أريد شراء عقار في الخارج"',
            'دبي "أبحث عن عقار في الخارج"',
            'الإمارات "شراء منزل في الخارج"',
            'دبي "شراء شقة في الخارج"',
            '"عقار في الخارج" ميزانية الإمارات',
            '"استثمار عقاري في الخارج" دبي',
            '"منزل ثان في الخارج" الإمارات',
            '"عقار على البحر المتوسط" دبي شراء',
            '"شمال قبرص" شراء شقة',
            '"قبرص الشمالية" شراء عقار',
        ],
    },
    "golden_visa": {
        "icon": "🛂", "title": "GOLDEN VISA BUYER INTENT", "hl": "en", "gl": "us",
        "audience_re": None,
        "query_anchor": re.compile(r"golden visa|residency by investment|residence by investment|investor visa", re.I),
        "bridge_domains": {"nomadgate.com", "reddit.com", "expat.com", "expatforum.com", "bogleheads.org"},
        "queries": [
            'site:reddit.com "golden visa" "I want" investment',
            'site:reddit.com "golden visa" "looking for" property',
            'site:reddit.com "residency by investment" property budget',
            'site:nomadgate.com "golden visa" investment forum',
            'site:expatforum.com "golden visa" property investment',
            'site:expat.com "golden visa" "minimum investment" forum',
            '"golden visa" "which country" investor forum',
            '"golden visa" "budget" property forum',
            '"residency by investment" "I am considering" forum',
            '"investor visa" property "looking for" forum',
        ],
    },
}

PROPERTY_RE = re.compile(r"(?:property|real estate|apartment|flat|house|home|villa|land|second home|holiday home|immobilie|wohnung|haus|ferienwohnung|ferienhaus|auslandsimmobilie|woning|huis|vastgoed|appartement|immobilier|maison|résidence|residence|nieruchomość|mieszkanie|dom|bostad|lägenhet|hus|casa|immobile|abitazione|vivienda|inmueble|imóvel|apartamento|bolig|hus|lejlighed|asunto|talo|nemovitost|byt|kinnisvara|korter|عقار|شقة|منزل)", re.I)
BUYER_RE = re.compile(
    r"(?:\b(?:i|we)\b.{0,70}\b(?:want|looking|planning|considering|ready|need|seeking)\b.{0,90}\b(?:buy|purchase|invest|property|apartment|house|villa|home)\b|"
    r"\blooking\s+to\s+buy\b|\bwant\s+to\s+buy\b|\bplanning\s+to\s+buy\b|"
    r"\b(?:ich|wir)\b.{0,70}\b(?:möchte|moechte|möchten|moechten|will|wollen|plane|planen|überlege|ueberlege|suche|suchen)\b.{0,90}\b(?:kaufen|investieren|immobilie|wohnung|haus|villa)\b|"
    r"\b(?:ik|wij|we)\b.{0,70}\b(?:wil|willen|plan|plannen|overweeg|overwegen|zoek|zoeken)\b.{0,90}\b(?:kopen|investeren|woning|huis|vastgoed|appartement)\b|"
    r"\b(?:je|nous)\b.{0,70}\b(?:veux|voulons|souhaite|souhaitons|prévois|prevoyons|cherche|cherchons)\b.{0,90}\b(?:acheter|investir|immobilier|appartement|maison|villa)\b|"
    r"\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,90}\b(?:kupić|nieruchomość|mieszkanie|dom)\b|"
    r"\b(?:jag|vi)\b.{0,70}\b(?:vill|planerar|överväger|söker)\b.{0,90}\b(?:köpa|bostad|lägenhet|hus|fastighet)\b|"
    r"\b(?:io|noi)\b.{0,70}\b(?:voglio|vogliamo|cerco|cerchiamo|penso|pensiamo)\b.{0,90}\b(?:comprare|acquistare|casa|immobile|appartamento)\b|"
    r"\b(?:yo|nosotros)\b.{0,70}\b(?:quiero|queremos|busco|buscamos|pienso|pensamos)\b.{0,90}\b(?:comprar|vivienda|casa|apartamento|inmueble)\b|"
    r"\b(?:eu|nós|nos)\b.{0,70}\b(?:quero|queremos|procuro|procuramos|planejo|planejamos)\b.{0,90}\b(?:comprar|casa|apartamento|imóvel)\b|"
    r"\b(?:jeg|vi)\b.{0,70}\b(?:vil|ønsker|planlegger|ser etter|søker)\b.{0,90}\b(?:kjøpe|bolig|hus|leilighet|eiendom)\b|"
    r"\b(?:jeg|vi)\b.{0,70}\b(?:vil|ønsker|planlægger|leder efter|søger)\b.{0,90}\b(?:købe|bolig|hus|lejlighed|ejendom)\b|"
    r"\b(?:minä|me)\b.{0,70}\b(?:haluan|haluamme|etsin|etsimme|suunnittelen|suunnittelemme)\b.{0,90}\b(?:ostaa|asunto|talo|kiinteistö)\b|"
    r"\b(?:já|my)\b.{0,70}\b(?:chci|chceme|hledám|hledáme|plánuji|plánujeme)\b.{0,90}\b(?:koupit|nemovitost|byt|dům)\b|"
    r"\b(?:mina|me)\b.{0,70}\b(?:tahan|tahame|otsin|otsime|plaanin|plaanime)\b.{0,90}\b(?:osta|kinnisvara|korter|maja)\b|"
    r"(?:أريد|نريد|أبحث|نبحث|أخطط|نخطط).{0,90}(?:شراء|عقار|شقة|منزل)\b)",
    re.I | re.S,
)
FIRST_PERSON_RE = re.compile(r"(?:\b(?:i|we|my|our|ich|wir|mein\w*|unser\w*|ik|wij|mijn|ons|onze|je|nous|mon|ma|notre|chcę|chcemy|szukam|szukamy|jag|vi|io|noi|yo|nosotros|eu|nós|nos|jeg|minä|me|já|my|mina)\b|(?:أريد|نريد|أبحث|نبحث))", re.I)
CONCRETE_RE = re.compile(r"(?:[£€$₣]\s*\d[\d\s.,]*(?:\s*[kKmM])?|\bbudget\b|\bmortgage\b|\bdeposit\b|\bpayment plan\b|\beigenkapital\b|\bfinanzierung\b|\bhypotheek\b|\bfinanciering\b|\bapport\b|\bfinancement\b|\bminimum investment\b)", re.I)
RENT_RE = re.compile(r"(?:for rent|looking to rent|rental|per month|monthly|mieten|miete|zur miete|huren|huur|per maand|à louer|a louer|location mensuelle)", re.I)
SELLER_RE = re.compile(r"(?:for sale|available now|contact us|whatsapp|estate agent|real estate agent|realtor|broker|developer|listing|our project|our properties|zu verkaufen|makler|immobilienmakler|te koop aangeboden|makelaar|à vendre|a vendre|agent immobilier|promoteur)", re.I)
NEGATIVE_RE = re.compile(r"(?:already bought|already purchased|i bought|we bought|not buying|no longer looking|bereits gekauft|niet meer op zoek|déjà acheté|deja achete)", re.I)
GOLDEN_CONTEXT_RE = re.compile(r"(?:golden visa|golden residence|residency by investment|residence by investment|investor visa|investment migration|goldenes visum|gouden visum|visa doré|visa dore)", re.I)
GOLDEN_INTENT_RE = re.compile(r"(?:\b(?:i|we)\b.{0,80}\b(?:want|looking|considering|planning|need|interested)\b.{0,100}\b(?:golden visa|residency|residence|investor visa|investment)\b|\bwhich\s+(?:golden visa|country|program)\b|\bminimum investment\b|\brequirements?\b)", re.I | re.S)

TARGETS = [
    ("north_cyprus", re.compile(r"north(?:ern)? cyprus|nordzypern|chypre du nord|noord[- ]cyprus|kuzey k[ıi]br[ıi]s", re.I)),
    ("cyprus", re.compile(r"\bcyprus\b|\bzypern\b|\bchypre\b", re.I)),
    ("spain", re.compile(r"\bspain\b|\bspanien\b|\bspanje\b|\bespagne\b", re.I)),
    ("portugal", re.compile(r"\bportugal\b", re.I)),
    ("greece", re.compile(r"\bgreece\b|\bgriechenland\b|\bgr[èe]ce\b", re.I)),
    ("italy", re.compile(r"\bitaly\b|\bitalien\b|\bitalie\b", re.I)),
    ("turkey", re.compile(r"\bturkey\b|\btürkei\b|\bturquie\b|\bturkije\b", re.I)),
    ("uae", re.compile(r"\bdubai\b|\buae\b|\bunited arab emirates\b", re.I)),
    ("montenegro", re.compile(r"\bmontenegro\b", re.I)),
    ("croatia", re.compile(r"\bcroatia\b|\bkroatien\b", re.I)),
]


def now_utc():
    return datetime.now(timezone.utc)


def clean(value: str) -> str:
    return " ".join(str(value or "").split())


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def user_source(url: str) -> bool:
    d = domain_of(url)
    return any(d == x or d.endswith("." + x) for x in USER_DOMAINS)


def detect_target(text: str) -> str:
    for name, rx in TARGETS:
        if rx.search(text):
            return name
    return "unspecified_abroad"


def serper_search(profile: str, query: str) -> list[dict]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SERPER_API_KEY missing: abroad buyer radar requires Serper")
    spec = PROFILES[profile]
    cutoff = (now_utc() - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": f"{query} after:{cutoff}", "num": 10, "hl": spec["hl"], "gl": spec["gl"], "tbs": "qdr:w"},
        timeout=25,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Serper HTTP {response.status_code}: {response.text[:180]}")
    out = []
    for row in response.json().get("organic", []) or []:
        out.append({
            "source": "Serper",
            "url": row.get("link", ""),
            "title": row.get("title", ""),
            "text": row.get("snippet", ""),
            "published": row.get("date", ""),
            "author": "",
            "discovery_query": query,
        })
    print(f"ABROAD_SERPER_OK profile={profile} results={len(out)} query={query!r}")
    return out


def audience_match(profile: str, item: dict, text: str) -> tuple[bool, bool]:
    spec = PROFILES[profile]
    if profile in {"golden_visa", "global_abroad"}:
        return True, True
    explicit = bool(spec["audience_re"].search(text))
    if explicit:
        return True, True
    query = str(item.get("discovery_query") or "")
    domain = domain_of(str(item.get("url") or ""))
    bridge = bool(spec["query_anchor"].search(query) and any(domain == d or domain.endswith("." + d) for d in spec["bridge_domains"]))
    return bridge, False


def classify(profile: str, item: dict) -> tuple[dict | None, str]:
    url = str(item.get("url") or "")
    if not url or not user_source(url):
        return None, "non_user_source"
    text = clean(f"{item.get('title','')} {item.get('text','')}")
    if not text:
        return None, "empty"
    if NEGATIVE_RE.search(text):
        return None, "negative"
    if RENT_RE.search(text):
        return None, "rental"
    if SELLER_RE.search(text) and not FIRST_PERSON_RE.search(text):
        return None, "seller"

    if profile == "golden_visa":
        if not GOLDEN_CONTEXT_RE.search(text):
            return None, "no_golden_context"
        if not GOLDEN_INTENT_RE.search(text):
            return None, "no_golden_intent"
        first = bool(FIRST_PERSON_RE.search(text))
        concrete = bool(CONCRETE_RE.search(text))
        classification = "HOT" if first and concrete else "WARM"
        audience_explicit = True
    else:
        if not PROPERTY_RE.search(text):
            return None, "no_property"
        if not BUYER_RE.search(text):
            return None, "no_buyer_intent"
        matched, audience_explicit = audience_match(profile, item, text)
        if not matched:
            return None, "audience_unverified"
        first = bool(FIRST_PERSON_RE.search(text))
        concrete = bool(CONCRETE_RE.search(text))
        classification = "HOT" if first and concrete and audience_explicit else "WARM"

    return {
        **item,
        "profile": profile,
        "classification": classification,
        "target_market": detect_target(text),
        "audience_explicit": audience_explicit,
        "intent_score": 92 if classification == "HOT" else 76,
        "credibility_score": 86 if audience_explicit else 72,
        "fit_score": 95,
        "scanned_at": now_utc().isoformat(),
    }, "accepted"


def firestore_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    creds = service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)


def notify_telegram(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
        timeout=15,
    ).raise_for_status()


def lead_key(profile: str, lead: dict) -> str:
    basis = f"{profile}|{lead.get('url','')}|{clean(lead.get('text',''))[:260]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def seen_recently(db, key: str) -> bool:
    if not db:
        return False
    snap = db.collection(NOTIFIED_COLLECTION).document(key).get()
    if not snap.exists:
        return False
    data = snap.to_dict() or {}
    value = str(data.get("notified_at") or "")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= now_utc() - timedelta(days=14)


def mark_seen(db, key: str, lead: dict):
    if not db:
        return
    db.collection(NOTIFIED_COLLECTION).document(key).set({
        "profile": PROFILE,
        "url": lead.get("url", ""),
        "classification": lead.get("classification", ""),
        "notified_at": now_utc().isoformat(),
    }, merge=True)


def run():
    if PROFILE not in PROFILES:
        raise SystemExit(f"Unknown ABROAD_RADAR_PROFILE={PROFILE}")
    spec = PROFILES[PROFILE]
    raw = []
    for query in spec["queries"][:QUERY_LIMIT]:
        raw.extend(serper_search(PROFILE, query))

    unique = {}
    for item in raw:
        url = str(item.get("url") or "")
        if url:
            unique[url] = item

    reasons = Counter()
    leads = []
    for item in unique.values():
        lead, reason = classify(PROFILE, item)
        reasons[reason] += 1
        if lead:
            leads.append(lead)

    leads.sort(key=lambda x: (x["classification"] == "HOT", x["intent_score"], x["credibility_score"]), reverse=True)
    db = firestore_client()
    new = []
    for lead in leads:
        key = lead_key(PROFILE, lead)
        if seen_recently(db, key):
            continue
        new.append(lead)
        mark_seen(db, key, lead)

    if db:
        scan_id = f"{now_utc().strftime('%Y%m%d%H%M%S')}_{PROFILE}"
        db.collection(SCAN_COLLECTION).document(scan_id).set({
            "profile": PROFILE,
            "version": VERSION,
            "raw": len(raw),
            "unique": len(unique),
            "qualified": len(leads),
            "new": len(new),
            "reject_reasons": dict(reasons),
            "scanned_at": now_utc().isoformat(),
        }, merge=True)

    print("ABROAD_RADAR_COMPLETE", json.dumps({
        "profile": PROFILE,
        "version": VERSION,
        "raw": len(raw),
        "unique": len(unique),
        "qualified": len(leads),
        "new": len(new),
        "reject_reasons": dict(reasons),
    }, ensure_ascii=False))

    if not new:
        return []

    lines = [f"{spec['icon']} BAY-S {spec['title']} | {len(new)} YENİ LEAD"]
    for lead in new[:10]:
        excerpt = clean(lead.get("text", ""))[:280]
        lines.append(
            f"\n{lead['classification']} | hedef={lead['target_market']} | I{lead['intent_score']} C{lead['credibility_score']} F{lead['fit_score']}\n"
            f"{clean(lead.get('title',''))[:120]}\n{excerpt}\n{lead.get('url','')}"
        )
    notify_telegram("\n".join(lines))
    return new


if __name__ == "__main__":
    run()
