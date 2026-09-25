from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import nc_v5_batch_quality_guard as batch_guard
from telethon import functions as tg_functions

radar = batch_guard.radar
core = radar.core
v5 = radar.v5

VERSION = "6.12-owner-direct-buyer-fix"
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
    r"\bищу\s+в\s+аренд\w*\b|\bнужн(?:а|ы)\b.{0,100}\b(?:в\s+аренд\w*|на\s+аренд\w*)\b|"
    r"\bищу\s+(?:квартир\w*|дом\w*|вилл\w*|студи\w*)\b.{0,180}\b(?:на\s+месяц|на\s+год|на\s+долгий\s+срок|долгосроч\w*|долгосрок\w*|аренд\w*|сдавать\w*)\b|"
    r"\bищу\b.{0,120}\b(?:квартир\w*|дом\w*|вилл\w*|студи\w*)\b.{0,120}\b(?:с\s+\d|по\s+\d|на\s+\d+\s+(?:дн|день|дней|недел|месяц))\b"
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

FINANCIAL_OR_GOODS_RE = re.compile(
    r"(?:"
    r"\busdt\b|\bcrypto\b|\bкрипт\w*\b|\bобмен\s+валют\b|"
    r"\bучебник\w*\b|\bресниц\w*\b|\bпротеин\w*\b|\bракетк\w*\b|"
    r"\btextbook\b|\bprotein\b|\bracket\b|\bpaddle\b"
    r")",
    re.I,
)

POST_PURCHASE_OR_INFO_RE = re.compile(
    r"(?:"
    r"\b(?:получил[аи]?|у\s+меня\s+есть|своя)\b.{0,80}\b(?:титул\w*|квартир\w*|дом\w*|вилл\w*)\b|"
    r"\b(?:титул\w*|договор\s+покупк\w*)\b.{0,100}\b(?:внж|подаю|документ\w*|полици\w*)\b|"
    r"\bпосле\s+окончания\s+университета\b|\bперечень\s+должен\s+быть\b"
    r")",
    re.I | re.S,
)

AGENT_CLIENT_RE = re.compile(
    r"(?:\bдля\s+клиента\b|\bдля\s+моего\s+клиента\b|\bfor\s+(?:my|a|the|a\s+ready)\s+client\b|\bready\s+client\b|\bm[üu][şs]terim\s+i[çc]in\b)",
    re.I,
)

OWNER_DIRECT_ONLY_RE = re.compile(
    r"(?:"
    r"\bsahibinden\b|\bmal\s+sahibinden\b|\barac[ıi]s[ıi]z\b|\bemlak[çc][ıi]\s+istemiyorum\b|"
    r"\bdirect\s+from\s+(?:the\s+)?owner\b|\bowner\s+direct\b|\bno\s+(?:agents?|brokers?)\b|"
    r"\bот\s+собственник\w*\b|\bтолько\s+собственник\w*\b|\bбез\s+посредник\w*\b|"
    r"\bагент\w*\s+не\s+писать\b|\bриелтор\w*\s+не\s+писать\b|\bриэлтор\w*\s+не\s+писать\b"
    r")",
    re.I,
)

JOB_POST_RE = re.compile(
    r"(?:\bваканси\w*\b|\bобязанност\w*\b|\bзарплат\w*\b|\bработодатель\b|"
    r"\bvacancy\b|\bjob\s+opening\b|\bsalary\b|\bduties\b|"
    r"\bi[şs]\s+ilan[ıi]\b|\bmaa[şs]\b)",
    re.I,
)

VEHICLE_RE = re.compile(
    r"(?:\b(?:suzuki|honda|toyota|nissan|mazda|bmw|mercedes|audi|ford|kia|hyundai|renault|peugeot|fiat|volkswagen)\b|"
    r"\b(?:марка/модель|топливо|километров|автоматическ\w*|обмен)\b|"
    r"\b(?:car|vehicle|auto|автомобил\w*|машин\w*)\b.{0,120}\b(?:year|model|price|fuel|km|рассрочк)\b|"
    r"\b(?:ищу\s+в\s+аренду\s+авто|аренд\w*\s+авто|rent\s+(?:a\s+)?car|car\s+rental)\b)",
    re.I | re.S,
)

TUTOR_OR_PERSONAL_SERVICE_RE = re.compile(
    r"(?:\bрепетитор\w*\b|\bнян[яи]\b|\bдомработниц\w*\b|\bпомощниц\w*\s+по\s+дому\b|"
    r"\btutor\b|\bbabysitter\b|\bhousekeeper\b|\bprivate\s+teacher\b|"
    r"\b[öo]zel\s+ders\b|\b[öo][ğg]retmen\s+ar[ıi]yorum\b)",
    re.I,
)

DISCUSSION_OR_HYPOTHETICAL_RE = re.compile(
    r"(?:"
    r"\bмы\s+квартир\w*\s+продавали\b|\bя\s+таких\s+продаж\w*\s+сделал\b|"
    r"\bвы\s+купили\s+квартир\w*\b|\bне\s+нужно\s+покупать\s+недвижимост\w*\b|"
    r"\bкогда-нибудь\b.{0,80}\bкуплю\b|\bбудем\s+сидеть\s+и\s+плакать\b|"
    r"\bквартир\w*\s+мне\s+и\s+даром\s+не\s+нужн\w*\b|"
    r"\bпереуступк\w*\b.{0,160}\b(?:закон|налог|продаж)\w*\b|"
    r"\bзакон\w*\b.{0,160}\b(?:титул|оформлен|квартир|недвижимост)\w*\b.{0,160}\b(?:виноват|измен|обязал|ужесточ)\w*"
    r")",
    re.I | re.S,
)

COMMERCIAL_PROVIDER_RE = re.compile(
    r"(?:"
    r"\bуправляющ\w*\s+компани\w*\b|\bбер[её]м\s+в\s+управлени\w*\b|"
    r"\bполное\s+обслуживани\w*\b.{0,80}\bнедвижимост\w*\b|"
    r"\bproperty\s+management\s+company\b|\bwe\s+manage\s+propert\w*\b|"
    r"\bуправление\s+недвижимост\w*\b"
    r")",
    re.I | re.S,
)

SERVICE_PROVIDER_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:looking\s+for|need|recommend)\b.{0,80}\b(?:realtor|real\s+estate\s+agent|property\s+agent|agency|lawyer|solicitor|plumber|electrician|handyman|cleaner)\b|"
    r"\b(?:emlak[çc][ıi]|gayrimenkul\s+dan[ıi][şs]man[ıi]|avukat|tesisat[çc][ıi]|elektrik[çc]i|usta|tamirci|temizlik[çc]i)\s+ar[ıi]yorum\b|"
    r"\b(?:dairem|evim|villam|konutum)\w*.{0,80}\b(?:elektrik[çc]i|tesisat[çc][ıi]|usta|tamirci|temizlik[çc]i|avukat|emlak[çc][ıi])\b.{0,80}\bar[ıi]yorum\b|"
    r"\b(?:ищу|нужен|посоветуйте)\b.{0,80}\b(?:риелтор|риэлтор|агент\w*\s+по\s+недвижимости|юрист|адвокат|электрик|сантехник|мастер)\b"
    r")",
    re.I | re.S,
)

SELLER_DIRECTION_RE = re.compile(
    r"\b(?:продаю|продам|прода[её]тся|сдаю|сдам|сда[её]тся)\b",
    re.I,
)

IMPERATIVE_SALE_AD_RE = re.compile(
    r"(?:"
    r"^\W*buy\b.{0,140}\b(?:property|apartment|flat|house|villa|studio|land)\b.{0,180}"
    r"\b(?:for\s+sale|from\s*[£€$]|[£€$]\s?\d|dm\s+(?:me\s+)?for\s+details|contact\s+(?:me|us)|whatsapp)\b|"
    r"^\W*(?:sat[ıi]n\s+al[ıi]n|hemen\s+al[ıi]n)\b.{0,180}\b(?:daire|ev|villa|arsa|gayrimenkul|konut)\b|"
    r"^\W*купите\b.{0,180}\b(?:квартир\w*|апартамент\w*|вилл\w*|дом\w*|недвижимост\w*)\b"
    r")",
    re.I | re.S,
)

SUPPLY_STRONG_RE = re.compile(
    r"(?:"
    r"\bfor\s+sale\b.{0,150}\b(?:price|bedroom|sqm|m2|contact|whatsapp)\b|"
    r"\b(?:available\s+units?|price\s+from|book\s+a\s+viewing|property\s+(?:id|ref)|listing\s+(?:id|ref))\b|"
    r"\b(?:sat[ıi]l[ıi]k|kiral[ıi]k)\b.{0,140}\b(?:fiyat|m2|metrekare|ileti[şs]im|whatsapp|portf[öo]y)\b|"
    r"\b(?:прода[её]тся|продаю|продам|сдам|сдаю|сда[её]тся|#?продаж\w*)\b.{0,220}\b(?:цена|цены|м2|м²|пишите|whatsapp|контакт|менеджер|£|€|\$)\b|"
    r"^\s*аренда\s*[,.:\-].{0,180}\b(?:£|€|\$|айдат|рассматриваем|комплекс)\b|"
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
    ('site:facebook.com/groups "North Cyprus" ("looking for" OR "moving" OR "investment" OR "rent")', None),
    ('site:facebook.com/groups "Kuzey Kıbrıs" ("arıyorum" OR "taşın" OR "yatırım" OR "kiralık")', None),
    ('site:facebook.com/groups "Северный Кипр" ("ищу" OR "переезд" OR "инвест" OR "аренда")', None),
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
        ("Lefkoşa", r"lefko[şs]a|nicosia\s+north|лефкош\w*|никоси\w*"),
        ("Lefke", r"\blefke\b|\bлефке\b"),
        ("Güzelyurt", r"g[üu]zelyurt|morphou|гюзельюрт"),
        ("Ercan", r"ercan"),
    ]
    for label, pattern in mapping:
        if re.search(pattern, text or "", re.I):
            return label
    return ""


def extract_budget(text: str) -> str:
    patterns = [
        r"\b\d[\d\s,.]*(?:k|m)?\s?(?:£|€|\$)",
        r"(?<!\d)(?:£|€|\$)\s?\d[\d\s,.]*(?:k|m)?",
        r"\b\d[\d\s,.]*(?:k)?\s?(?:gbp|eur|usd|pounds?|euros?|dollars?|фунт\w*)\b",
        r"\b\d[\d\s,.]*\s*bin\s*(?:£|gbp|pound|pounds?|sterlin)?\b",
        r"\b(?:budget|b[üu]t[çc]e|бюджет)\s*[:\-]?\s*((?:£|€|\$)?\s?\d[\d\s,.]*(?:k|m)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "", re.I)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip()
    return ""


def has_purchase_sized_budget(text: str) -> bool:
    value = str(text or "")
    # Property purchase requests in this market are normally quoted in GBP/EUR/USD
    # at five- or six-figure levels. This catches "ищу 1+1, бюджет £100000"
    # even when the writer omits an explicit "buy" verb.
    patterns = [
        r"(?:£|€|\$)\s*([0-9][0-9\s,.]{3,})",
        r"([0-9][0-9\s,.]{3,})\s*(?:£|€|\$|gbp|eur|usd|фунт\w*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, value, re.I)
        if not m:
            continue
        digits = re.sub(r"\D", "", m.group(1))
        if not digits:
            continue
        try:
            amount = int(digits)
        except ValueError:
            continue
        if amount >= 20000:
            return True
    return False


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
    if FINANCIAL_OR_GOODS_RE.search(text):
        return "financial_or_goods"
    if POST_PURCHASE_OR_INFO_RE.search(text):
        return "post_purchase_or_info"
    # "Sahibinden / direct from owner / от собственника" is NOT a negative
    # signal by itself. A real buyer may explicitly prefer buying from an owner.
    # Seller/listing language is rejected below by the supply guards.
    if JOB_POST_RE.search(text):
        return "job_post"
    if VEHICLE_RE.search(text):
        return "vehicle"
    if TUTOR_OR_PERSONAL_SERVICE_RE.search(text):
        return "personal_service"
    if DISCUSSION_OR_HYPOTHETICAL_RE.search(text):
        return "discussion_or_hypothetical"
    if COMMERCIAL_PROVIDER_RE.search(text):
        return "commercial_provider"
    if IMPERATIVE_SALE_AD_RE.search(text):
        return "supply_or_agent"
    if SELLER_DIRECTION_RE.search(text) and PROPERTY_RE.search(text):
        return "supply_or_agent"
    if radar.TG_SERVICE_REQUEST_RE.search(text) or SERVICE_PROVIDER_REQUEST_RE.search(text):
        return "service_request"
    if radar.TG_STRONG_SUPPLY_RE.search(text) or SUPPLY_STRONG_RE.search(text):
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
    agent_client = bool(AGENT_CLIENT_RE.search(own))
    budget = extract_budget(own)
    specificity = _specificity(own)

    # Production sales-only mode: Prime Kibris wants direct purchase demand only.
    # Rentals, generic investment discussion/research, relocation and ambiguous
    # property chatter are intentionally excluded unless there is an explicit
    # property purchase statement in the person's own message.
    sales_only = os.getenv("RADAR_SALES_ONLY", "0").strip() == "1"
    if sales_only:
        if rent:
            return None, "rental_excluded_sales_only"
        purchase_budget_request = bool(has_property and demand and has_purchase_sized_budget(own))
        agent_purchase_request = bool(agent_client and has_property and demand and (purchase_budget_request or qualifier or investor))
        if not buy and not agent_purchase_request and not purchase_budget_request:
            return None, "no_explicit_purchase_intent"
        if not any((has_property, qualifier, investor, residency)):
            return None, "no_property_purchase_context"

    # A generic "buy" verb inside a North-Cyprus group is not enough. It must
    # actually concern housing/property, otherwise books, crypto and household
    # goods become fake BUYER leads.
    if buy and not any((has_property, qualifier, investor, residency, relocation, research)):
        return None, "no_property_purchase_context"

    # Residency by itself is not a property lead; require a housing, relocation
    # or explicit research/demand context.
    if residency and not any((has_property, buy, relocation, demand, research, qualifier)):
        return None, "residency_without_housing_intent"

    # Nothing housing/relocation/investment-shaped reached the semantic stage.
    if not any((has_property, buy, rent, relocation, investor, research, qualifier, residency)):
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
    elif sales_only and agent_client and has_property and demand and (has_purchase_sized_budget(own) or qualifier or investor):
        intent_type = "BUYER"
        lead_class = "HOT BUYER" if specificity >= 2 else "WARM BUYER"
        score = 76 + min(18, specificity * 4)
        reasons.append("agent_client_purchase_request")
    elif sales_only and has_property and demand and has_purchase_sized_budget(own):
        intent_type = "BUYER"
        lead_class = "HOT BUYER" if specificity >= 2 else "WARM BUYER"
        score = 78 + min(18, specificity * 4)
        reasons.append("purchase_budget_demand")
    elif buy and investor:
        intent_type = "INVESTOR"
        lead_class = "INVESTOR"
        score = 82 + min(14, specificity * 3)
        reasons.extend(["explicit_purchase_intent", "investment_or_yield_research"])
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
    if OWNER_DIRECT_ONLY_RE.search(own) and buy and has_property:
        reasons.append("owner_direct_buyer_preference")
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
    "strict_extra_groups_scanned": 0,
    "strict_extra_messages_scanned": 0,
    "strict_extra_geo_pass": 0,
    "strict_extra_signal_pass": 0,
    "strict_extra_accepted": 0,
    "strict_extra_reject_reasons": Counter(),
    "global_search_queries": 0,
    "global_search_raw": 0,
    "global_search_public": 0,
    "global_search_geo_pass": 0,
    "global_search_signal_pass": 0,
    "global_search_accepted": 0,
    "global_search_reject_reasons": Counter(),
    "global_search_age_buckets": Counter(),
    "global_search_candidate_samples": [],
    "peer_discovery_queries": 0,
    "peer_discovery_found": 0,
    "peer_discovery_scanned": 0,
    "peer_discovery_messages": 0,
    "peer_discovery_geo_pass": 0,
    "peer_discovery_signal_pass": 0,
    "peer_discovery_accepted": 0,
    "peer_discovery_reject_reasons": Counter(),
    "peer_discovery_samples": [],
    "geography_pass": 0,
    "signal_pass": 0,
    "accepted": 0,
    "review_candidates": 0,
    "review_qualified": 0,
    "review_saved": 0,
    "review_reject_reasons": Counter(),
    "review_samples": [],
    "already_notified": 0,
    "reject_reasons": Counter(),
    "accepted_classes": Counter(),
    "languages": Counter(),
    "groups": Counter(),
    "web_raw_by_source": Counter(),
    "web_platforms": Counter(),
    "web_accepted": 0,
    "web_reject_reasons": Counter(),
    "web_provider_errors": Counter(),
    "errors": [],
}


def _group_scope(group: str) -> tuple[bool, bool, bool]:
    return (
        bool(DIRECT_NORTH_GROUP_RE.search(group or "")),
        bool(GENERIC_CYPRUS_GROUP_RE.search(group or "")),
        bool(THEMATIC_GROUP_RE.search(group or "")),
    )


def strict_extra_candidate_signal(text: str) -> bool:
    """Very high precision prefilter for groups whose names look unrelated.

    These groups get no market context from their title. A message must carry
    its own North-Cyprus location, property object and buyer-side signal before
    the normal sales-only classifier is even called.
    """
    own = str(text or "")
    return bool(
        has_nc_geo(own)
        and PROPERTY_RE.search(own)
        and (
            BUY_RE.search(own)
            or DEMAND_RE.search(own)
            or PURCHASE_QUALIFIER_RE.search(own)
            or INVESTOR_RE.search(own)
        )
    )


TELEGRAM_GLOBAL_PUBLIC_QUERIES = (
    "Северный Кипр квартира",
    "Северный Кипр недвижимость",
    "Искеле квартира",
    "Гирне квартира",
    "North Cyprus apartment",
    "North Cyprus property",
    "Kuzey Kıbrıs daire",
    "Kuzey Kıbrıs gayrimenkul",
    "İskele daire",
    "Girne daire",
)


TELEGRAM_PUBLIC_PEER_QUERIES = (
    "North Cyprus",
    "Северный Кипр",
    "Kuzey Kıbrıs",
    "Iskele",
    "Girne",
)

RADAR_SELF_FEEDBACK_RE = re.compile(
    r"(?:\bLEAD\s+RADAR\b|\bOK\.RU\s+RADAR\b|\bPRIME\s+RADAR\b|"
    r"\bNC_REDDIT_|\bBUYER\s+ADAYI\b)",
    re.I,
)


def global_public_candidate_signal(text: str, author: str = "") -> bool:
    """No group-title context is trusted for global search results."""
    own = str(text or "")
    if RADAR_SELF_FEEDBACK_RE.search(own):
        return False
    if _hard_reject(own, author):
        return False
    return strict_extra_candidate_signal(own)


def _public_chat_username(chat: Any) -> str:
    username = str(getattr(chat, "username", "") or "").strip()
    if not username:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", username):
        return ""
    return username


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


def evaluate_review_candidate(candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    text = str(candidate.get("message") or "")
    if not text:
        return None, "empty"

    # REVIEW is not a second listing bucket. It should contain only ambiguous
    # people who may genuinely be in a purchase/research journey.
    if RENT_DEMAND_RE.search(text):
        return None, "rent_demand"
    if SELLER_DIRECTION_RE.search(text):
        return None, "seller_direction"
    if radar.TG_STRONG_SUPPLY_RE.search(text) or SUPPLY_STRONG_RE.search(text):
        return None, "supply_listing"
    if POST_PURCHASE_OR_INFO_RE.search(text):
        return None, "post_purchase_or_info"
    if DISCUSSION_OR_HYPOTHETICAL_RE.search(text):
        return None, "discussion_or_hypothetical"
    if COMMERCIAL_PROVIDER_RE.search(text):
        return None, "commercial_provider"

    has_property = bool(PROPERTY_RE.search(text))
    demand = bool(DEMAND_RE.search(text))
    budget = extract_budget(text)
    purchase_budget = has_purchase_sized_budget(text)
    room = bool(ROOM_RE.search(text))
    region = extract_region(text)
    qualifier = bool(PURCHASE_QUALIFIER_RE.search(text))
    investor = bool(INVESTOR_RE.search(text))
    research = bool(RESEARCH_RE.search(text))
    residency = bool(RESIDENCY_RE.search(text))
    agent_client = bool(AGENT_CLIENT_RE.search(text))

    listing_shape = bool(
        has_property
        and not demand
        and (
            re.search(r"\\b(?:цена|price|fiyat)\\b", text, re.I)
            or re.search(r"\\b\\d{2,4}(?:[.,]\\d+)?\\s*(?:m2|m²|м2|м²)\\b", text, re.I)
            or re.search(r"\\b(?:этаж|площадь|налоги|трафо|балкон|терраса|парковка)\\b", text, re.I)
        )
    )
    if listing_shape:
        return None, "listing_shape"

    purchase_context = bool(
        qualifier
        or investor
        or research
        or residency
        or agent_client
        or (
            purchase_budget
            and demand
            and re.search(r"\\b(?:бюджет|budget|bütçe)\\b", text, re.I)
        )
    )

    if not has_property:
        return None, "no_property"
    if not demand:
        return None, "no_demand"
    if not purchase_context:
        return None, "no_purchase_context"

    score = 4
    reasons: list[str] = ["property", "demand", "purchase_context"]
    if purchase_budget:
        score += 3; reasons.append("purchase_sized_budget")
    elif budget:
        score += 1; reasons.append("budget")
    if room:
        score += 1; reasons.append("room")
    if region:
        score += 1; reasons.append("region")
    if qualifier:
        score += 2; reasons.append("purchase_qualifier")
    if investor:
        score += 2; reasons.append("investment")
    if research:
        score += 2; reasons.append("research")
    if residency:
        score += 1; reasons.append("residency")
    if agent_client:
        score += 2; reasons.append("agent_client")

    return {
        **candidate,
        "lead_class": "REVIEW",
        "classification": "REVIEW",
        "review_score": score,
        "review_reasons": reasons,
        "estimated_budget": budget,
        "estimated_region": region,
        "important_criteria": criteria(text),
        "radar_version": VERSION,
    }, "accepted"


def build_review_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    review, _ = evaluate_review_candidate(candidate)
    return review

async def broad_telegram_scan(db_client, started):
    if not core.TELEGRAM_API_ID or not core.TELEGRAM_API_HASH:
        DEBUG["errors"].append("telegram_missing_api_credentials")
        return {"status": "skipped", "groups": 0, "messages": 0, "hot_warm": 0, "errors": 0, "new_leads": []}
    if not core.TELEGRAM_SESSION.exists():
        DEBUG["errors"].append("telegram_missing_session")
        return {"status": "skipped_no_session", "groups": 0, "messages": 0, "hot_warm": 0, "errors": 0, "new_leads": []}

    client = core.TelegramClient(str(core.TELEGRAM_SESSION), core.TELEGRAM_API_ID, core.TELEGRAM_API_HASH)
    accepted: list[dict[str, Any]] = []
    review_pool: list[dict[str, Any]] = []
    seen_text_hashes: set[str] = set()
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
        joined_public_usernames = {
            _public_chat_username(d.entity).casefold()
            for d in dialogs
            if _public_chat_username(d.entity)
        }

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
            strict_extra = not any((direct_north, generic_cyprus, thematic))

            if strict_extra:
                DEBUG["strict_extra_groups_scanned"] += 1
                message_limit = min(60, core.TELEGRAM_PER_GROUP_LIMIT)
            else:
                DEBUG["groups_relevant"] += 1
                message_limit = core.TELEGRAM_PER_GROUP_LIMIT

            try:
                async for msg in client.iter_messages(entity, limit=message_limit):
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

                    if strict_extra:
                        DEBUG["strict_extra_messages_scanned"] += 1
                    else:
                        DEBUG["messages_scanned"] += 1
                        DEBUG["groups"][group] += 1

                    text_key = hashlib.sha256(_norm(text).encode("utf-8", "ignore")).hexdigest()
                    if text_key in seen_text_hashes:
                        if strict_extra:
                            DEBUG["strict_extra_reject_reasons"]["duplicate_text"] += 1
                        else:
                            DEBUG["reject_reasons"]["duplicate_text"] += 1
                        continue
                    seen_text_hashes.add(text_key)

                    explicit_geo = has_nc_geo(text)

                    if strict_extra:
                        if not explicit_geo:
                            DEBUG["strict_extra_reject_reasons"]["no_north_context"] += 1
                            continue
                        DEBUG["strict_extra_geo_pass"] += 1

                        if not strict_extra_candidate_signal(text):
                            if not PROPERTY_RE.search(text):
                                DEBUG["strict_extra_reject_reasons"]["no_property"] += 1
                            else:
                                DEBUG["strict_extra_reject_reasons"]["no_buyer_signal"] += 1
                            continue
                        DEBUG["strict_extra_signal_pass"] += 1
                    else:
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
                    if strict_extra:
                        candidate["source_type"] = "joined_group_strict_extra"
                    signal, reason = classify_text(
                        text,
                        group="" if strict_extra else group,
                        author=candidate.get("author", ""),
                        explicit_geo=explicit_geo,
                    )
                    if signal is None:
                        if strict_extra:
                            DEBUG["strict_extra_reject_reasons"][reason] += 1
                        else:
                            DEBUG["reject_reasons"][reason] += 1
                            if reason == "no_explicit_purchase_intent":
                                DEBUG["review_candidates"] += 1
                                review, review_reason = evaluate_review_candidate(candidate)
                                if review is None:
                                    DEBUG["review_reject_reasons"][review_reason] += 1
                                else:
                                    DEBUG["review_qualified"] += 1
                                    stable_id = f"telegram-review|{dialog.id}|{msg.id}"
                                    review_id = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
                                    review["lead_id"] = review_id
                                    review["review_reason"] = reason
                                    review["buyer_signal"] = "review_purchase_possible"
                                    try:
                                        db_client.collection("bay_s_lead_radar_review").document(review_id).set(review, merge=True)
                                        DEBUG["review_saved"] += 1
                                    except Exception as exc:
                                        DEBUG["errors"].append(f"review_firestore:{type(exc).__name__}:{exc}")
                                    review_pool.append(review)
                                    if len(DEBUG["review_samples"]) < 12:
                                        DEBUG["review_samples"].append({
                                            "score": review.get("review_score", 0),
                                            "author": review.get("author", ""),
                                            "group": review.get("group", ""),
                                            "message": review.get("message", "")[:500],
                                            "url": review.get("url", ""),
                                            "budget": review.get("estimated_budget", ""),
                                            "region": review.get("estimated_region", ""),
                                            "reasons": review.get("review_reasons", []),
                                        })
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
                    if strict_extra:
                        DEBUG["strict_extra_accepted"] += 1
                    DEBUG["accepted_classes"][signal["lead_class"]] += 1
                    DEBUG["languages"][signal["language"]] += 1
            except core.FloodWaitError as exc:
                errors += 1
                scope = "strict_extra" if strict_extra else "primary"
                DEBUG["errors"].append(f"telegram_flood_wait:{scope}:{group}:{exc.seconds}")
            except Exception as exc:
                errors += 1
                scope = "strict_extra" if strict_extra else "primary"
                DEBUG["errors"].append(f"telegram_group:{scope}:{group}:{type(exc).__name__}:{exc}")
            await asyncio.sleep(0.20)

        # Second discovery surface: Telegram global public message search.
        # We only retain messages from public username-addressable chats/channels.
        # No private chats, no private groups and no group-name context are trusted.
        global_days = max(3, min(60, int(os.getenv("RADAR_GLOBAL_TELEGRAM_DAYS", "30") or "30")))
        global_cutoff = datetime.now(timezone.utc) - timedelta(days=global_days)
        global_seen: set[tuple[str, int]] = set()

        for query in TELEGRAM_GLOBAL_PUBLIC_QUERIES:
            DEBUG["global_search_queries"] += 1
            try:
                async for msg in client.iter_messages(None, search=query, limit=80):
                    DEBUG["global_search_raw"] += 1

                    dt = getattr(msg, "date", None)
                    if not dt:
                        DEBUG["global_search_reject_reasons"]["no_date"] += 1
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    age_days = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
                    if age_days <= 3:
                        DEBUG["global_search_age_buckets"]["0_3d"] += 1
                    elif age_days <= 7:
                        DEBUG["global_search_age_buckets"]["4_7d"] += 1
                    elif age_days <= 30:
                        DEBUG["global_search_age_buckets"]["8_30d"] += 1
                    else:
                        DEBUG["global_search_age_buckets"]["gt_30d"] += 1

                    if dt < global_cutoff:
                        DEBUG["global_search_reject_reasons"]["stale"] += 1
                        continue

                    text = str(getattr(msg, "message", "") or "").strip()
                    if not text:
                        DEBUG["global_search_reject_reasons"]["empty"] += 1
                        continue

                    try:
                        chat = await msg.get_chat()
                    except Exception:
                        chat = None
                    username = _public_chat_username(chat)
                    if not username:
                        DEBUG["global_search_reject_reasons"]["not_public_username_chat"] += 1
                        continue
                    DEBUG["global_search_public"] += 1

                    msg_id = int(getattr(msg, "id", 0) or 0)
                    identity = (username.casefold(), msg_id)
                    if identity in global_seen:
                        DEBUG["global_search_reject_reasons"]["duplicate_message"] += 1
                        continue
                    global_seen.add(identity)

                    text_key = hashlib.sha256(_norm(text).encode("utf-8", "ignore")).hexdigest()
                    if text_key in seen_text_hashes:
                        DEBUG["global_search_reject_reasons"]["duplicate_text"] += 1
                        continue
                    seen_text_hashes.add(text_key)

                    if not has_nc_geo(text):
                        DEBUG["global_search_reject_reasons"]["no_north_context"] += 1
                        continue
                    DEBUG["global_search_geo_pass"] += 1

                    try:
                        await msg.get_sender()
                    except Exception:
                        pass
                    author = core.tg_sender(msg)

                    if not global_public_candidate_signal(text, author):
                        if RADAR_SELF_FEEDBACK_RE.search(text):
                            DEBUG["global_search_reject_reasons"]["self_feedback"] += 1
                        elif _hard_reject(text, author):
                            DEBUG["global_search_reject_reasons"][_hard_reject(text, author)] += 1
                        elif not PROPERTY_RE.search(text):
                            DEBUG["global_search_reject_reasons"]["no_property"] += 1
                        else:
                            DEBUG["global_search_reject_reasons"]["no_buyer_signal"] += 1
                        continue
                    DEBUG["global_search_signal_pass"] += 1
                    if len(DEBUG["global_search_candidate_samples"]) < 12:
                        DEBUG["global_search_candidate_samples"].append({
                            "query": query,
                            "message": text[:500],
                            "message_time": dt.isoformat(timespec="seconds"),
                        })

                    group = str(
                        getattr(chat, "title", None)
                        or getattr(chat, "first_name", None)
                        or username
                    )
                    candidate = {
                        "source": "Telegram",
                        "platform": "Telegram",
                        "source_type": "telegram_global_public_search",
                        "group": group,
                        "group_priority": "GLOBAL_PUBLIC",
                        "group_username": username,
                        "message_id": msg_id,
                        "message_time": dt.isoformat(timespec="seconds"),
                        "author": core.tg_sender(msg),
                        "message": text,
                        "url": f"https://t.me/{username}/{msg_id}",
                        "market": "north_cyprus",
                        "found_at": started.isoformat(),
                        "search_query": query,
                    }

                    signal, reason = classify_text(
                        text,
                        group="",
                        author=candidate.get("author", ""),
                        explicit_geo=True,
                    )
                    if signal is None:
                        DEBUG["global_search_reject_reasons"][reason] += 1
                        continue

                    stable_id = f"telegram-global|{username.casefold()}|{msg_id}"
                    lead_id = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
                    ref = db_client.collection(core.COLLECTION).document(lead_id)
                    snap = ref.get()
                    if snap.exists:
                        previous = snap.to_dict() or {}
                        if previous.get("v5_notified_at") or previous.get("v6_notified_at"):
                            DEBUG["already_notified"] += 1
                            DEBUG["global_search_reject_reasons"]["already_notified"] += 1
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
                    DEBUG["global_search_accepted"] += 1
                    DEBUG["accepted_classes"][signal["lead_class"]] += 1
                    DEBUG["languages"][signal["language"]] += 1

            except core.FloodWaitError as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_global_flood_wait:{query}:{exc.seconds}")
                break
            except Exception as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_global_search:{query}:{type(exc).__name__}:{exc}")
            await asyncio.sleep(0.35)

        # Third discovery surface: discover public Telegram groups/channels
        # by name, without joining them, then scan only their recent public history.
        discovered_peers: dict[str, Any] = {}
        for query in TELEGRAM_PUBLIC_PEER_QUERIES:
            DEBUG["peer_discovery_queries"] += 1
            try:
                result = await client(tg_functions.contacts.SearchRequest(q=query, limit=25))
                for chat in getattr(result, "chats", []) or []:
                    username = _public_chat_username(chat)
                    if not username:
                        continue
                    key = username.casefold()
                    if key in joined_public_usernames:
                        DEBUG["peer_discovery_reject_reasons"]["already_joined"] += 1
                        continue
                    discovered_peers.setdefault(key, chat)
            except core.FloodWaitError as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_peer_discovery_flood_wait:{query}:{exc.seconds}")
                break
            except Exception as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_peer_discovery:{query}:{type(exc).__name__}:{exc}")
            await asyncio.sleep(0.25)

        DEBUG["peer_discovery_found"] = len(discovered_peers)
        peer_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        for username_key, chat in list(discovered_peers.items())[:40]:
            username = _public_chat_username(chat)
            if not username:
                continue
            title = str(getattr(chat, "title", None) or username)
            direct_north = bool(DIRECT_NORTH_GROUP_RE.search(title) or DIRECT_NORTH_GROUP_RE.search(username))
            DEBUG["peer_discovery_scanned"] += 1

            try:
                async for msg in client.iter_messages(chat, limit=60):
                    dt = getattr(msg, "date", None)
                    if not dt:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < peer_cutoff:
                        break

                    text = str(getattr(msg, "message", "") or "").strip()
                    if not text:
                        continue
                    DEBUG["peer_discovery_messages"] += 1

                    text_key = hashlib.sha256(_norm(text).encode("utf-8", "ignore")).hexdigest()
                    if text_key in seen_text_hashes:
                        DEBUG["peer_discovery_reject_reasons"]["duplicate_text"] += 1
                        continue
                    seen_text_hashes.add(text_key)

                    if RADAR_SELF_FEEDBACK_RE.search(text):
                        DEBUG["peer_discovery_reject_reasons"]["self_feedback"] += 1
                        continue

                    explicit_geo = has_nc_geo(text)
                    if not direct_north and not explicit_geo:
                        DEBUG["peer_discovery_reject_reasons"]["no_north_context"] += 1
                        continue
                    DEBUG["peer_discovery_geo_pass"] += 1

                    if not candidate_signal(text):
                        DEBUG["peer_discovery_reject_reasons"]["no_candidate_signal"] += 1
                        continue

                    try:
                        await msg.get_sender()
                    except Exception:
                        pass
                    author = core.tg_sender(msg)
                    hard = _hard_reject(text, author)
                    if hard:
                        DEBUG["peer_discovery_reject_reasons"][hard] += 1
                        continue
                    DEBUG["peer_discovery_signal_pass"] += 1

                    signal, reason = classify_text(
                        text,
                        group=title if direct_north else "",
                        author=author,
                        explicit_geo=explicit_geo,
                    )
                    if signal is None:
                        DEBUG["peer_discovery_reject_reasons"][reason] += 1
                        continue

                    msg_id = int(getattr(msg, "id", 0) or 0)
                    candidate = {
                        "source": "Telegram",
                        "platform": "Telegram",
                        "source_type": "telegram_public_peer_discovery",
                        "group": title,
                        "group_priority": "PUBLIC_DISCOVERY",
                        "group_username": username,
                        "message_id": msg_id,
                        "message_time": dt.isoformat(timespec="seconds"),
                        "author": author,
                        "message": text,
                        "url": f"https://t.me/{username}/{msg_id}",
                        "market": "north_cyprus",
                        "found_at": started.isoformat(),
                    }

                    stable_id = f"telegram-peer|{username.casefold()}|{msg_id}"
                    lead_id = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
                    ref = db_client.collection(core.COLLECTION).document(lead_id)
                    snap = ref.get()
                    if snap.exists:
                        previous = snap.to_dict() or {}
                        if previous.get("v5_notified_at") or previous.get("v6_notified_at"):
                            DEBUG["already_notified"] += 1
                            DEBUG["peer_discovery_reject_reasons"]["already_notified"] += 1
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
                    DEBUG["peer_discovery_accepted"] += 1
                    DEBUG["accepted_classes"][signal["lead_class"]] += 1
                    DEBUG["languages"][signal["language"]] += 1
                    if len(DEBUG["peer_discovery_samples"]) < 12:
                        DEBUG["peer_discovery_samples"].append({
                            "group": title,
                            "username": username,
                            "message": text[:500],
                            "message_time": dt.isoformat(timespec="seconds"),
                            "lead_class": signal["lead_class"],
                        })
            except core.FloodWaitError as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_peer_scan_flood_wait:{username}:{exc.seconds}")
                break
            except Exception as exc:
                errors += 1
                DEBUG["errors"].append(f"telegram_peer_scan:{username}:{type(exc).__name__}:{exc}")
            await asyncio.sleep(0.15)

        return {
            "status": "completed",
            "groups": DEBUG["groups_relevant"],
            "messages": DEBUG["messages_scanned"],
            "hot_warm": len(accepted),
            "errors": errors,
            "new_leads": accepted,
            "review_pool": sorted(review_pool, key=lambda x: x.get("review_score", 0), reverse=True)[:30],
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


def _bing_rss_search(query: str, include_domains: list[str] | None = None) -> list[dict[str, Any]]:
    q = query
    low = query.casefold()
    if "north cyprus" in low and '"north cyprus"' not in low:
        q = re.sub(r"north cyprus", '"North Cyprus"', q, flags=re.I)
    if "northern cyprus" in low and '"northern cyprus"' not in low:
        q = re.sub(r"northern cyprus", '"Northern Cyprus"', q, flags=re.I)
    if "северный кипр" in low and '"северный кипр"' not in low:
        q = re.sub(r"северный кипр", '"Северный Кипр"', q, flags=re.I)
    if "kuzey kıbrıs" in low and '"kuzey kıbrıs"' not in low:
        q = re.sub(r"kuzey kıbrıs", '"Kuzey Kıbrıs"', q, flags=re.I)
    if include_domains:
        q = f"{q} (" + " OR ".join(f"site:{d}" for d in include_domains) + ")"
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(q)
    try:
        r = core.requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadRadar/6.1)"},
            timeout=25,
        )
        if r.status_code != 200:
            DEBUG["web_provider_errors"][f"bing_http_{r.status_code}"] += 1
            return []
        root = ET.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:10]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            pub = item.findtext("pubDate") or ""
            if not link:
                continue
            out.append({
                "source": "Bing RSS",
                "url": link,
                "title": title,
                "text": desc,
                "published": pub,
                "author": "",
            })
        if not out:
            DEBUG["web_provider_errors"]["bing_zero_results"] += 1
        return out
    except Exception as exc:
        DEBUG["web_provider_errors"][f"bing_{type(exc).__name__}"] += 1
        return []


def search_debug(query: str, include_domains: list[str] | None = None):
    rows = _existing_search(query, include_domains)
    if not rows:
        exa_disabled = bool(getattr(radar.v53, "_EXA_DISABLED_FOR_RUN", False))
        serper_disabled = bool(getattr(radar.v53, "_SERPER_DISABLED_FOR_RUN", False))
        if exa_disabled and serper_disabled:
            DEBUG["web_provider_errors"]["paid_search_disabled_for_run"] = 1
        else:
            DEBUG["web_provider_errors"]["exa_serper_empty_or_quota"] += 1
        rows = _bing_rss_search(query, include_domains)

    filtered = []
    for row in rows:
        blob = f"{row.get('title','')} {row.get('text','')}"
        url = str(row.get("url") or "").casefold()
        if not (has_nc_geo(blob) or "/r/northcyprus/" in url or "northcyprus" in url or "north-cyprus" in url):
            DEBUG["web_reject_reasons"]["search_irrelevant_no_nc_context"] += 1
            continue
        filtered.append(row)

    for row in filtered:
        DEBUG["web_raw_by_source"][str(row.get("source") or "unknown")] += 1
        url = str(row.get("url") or "").casefold()
        platform = (
            "Facebook" if "facebook.com" in url else
            "Reddit" if "reddit.com" in url else
            "Expat" if "expat.com" in url else
            "Forum" if "forum" in url or "gutefrage.net" in url or "britishexpats.com" in url else
            "Other Web"
        )
        DEBUG["web_platforms"][platform] += 1
        row.setdefault("_search_query", query)
    return filtered


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
        "web_platforms": dict(DEBUG["web_platforms"]),
        "web_reject_reasons": dict(DEBUG["web_reject_reasons"]),
        "web_provider_errors": dict(DEBUG["web_provider_errors"]),
        "review_reject_reasons": dict(DEBUG["review_reject_reasons"]),
        "strict_extra_reject_reasons": dict(DEBUG["strict_extra_reject_reasons"]),
        "global_search_reject_reasons": dict(DEBUG["global_search_reject_reasons"]),
        "global_search_age_buckets": dict(DEBUG["global_search_age_buckets"]),
        "global_search_candidate_samples": DEBUG["global_search_candidate_samples"],
        "peer_discovery_reject_reasons": dict(DEBUG["peer_discovery_reject_reasons"]),
        "peer_discovery_samples": DEBUG["peer_discovery_samples"],
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
    platforms = ", ".join(f"{k}:{v}" for k, v in DEBUG["web_platforms"].most_common()) or "-"
    provider_errors = ", ".join(f"{k}:{v}" for k, v in DEBUG["web_provider_errors"].most_common()) or "-"
    web_rejects = ", ".join(f"{k}:{v}" for k, v in DEBUG["web_reject_reasons"].most_common(8)) or "-"
    strict_extra_rejects = ", ".join(f"{k}:{v}" for k, v in DEBUG["strict_extra_reject_reasons"].most_common(6)) or "-"
    global_search_rejects = ", ".join(f"{k}:{v}" for k, v in DEBUG["global_search_reject_reasons"].most_common(6)) or "-"
    peer_discovery_rejects = ", ".join(f"{k}:{v}" for k, v in DEBUG["peer_discovery_reject_reasons"].most_common(6)) or "-"
    total_errors = len(DEBUG["errors"])
    msg = (
        "🧪 LEAD RADAR DEBUG | SON TARAMA\n\n"
        f"Telegram ana grup: {DEBUG['groups_relevant']}/{DEBUG['groups_total']} | Mesaj: {DEBUG['messages_scanned']}\n"
        f"Ek sıkı grup: {DEBUG['strict_extra_groups_scanned']} | Mesaj: {DEBUG['strict_extra_messages_scanned']} | NC: {DEBUG['strict_extra_geo_pass']} | Aday: {DEBUG['strict_extra_signal_pass']} | Kabul: {DEBUG['strict_extra_accepted']}\n"        f"Global public 30g: sorgu {DEBUG['global_search_queries']} | Ham {DEBUG['global_search_raw']} | Public {DEBUG['global_search_public']} | NC {DEBUG['global_search_geo_pass']} | Aday {DEBUG['global_search_signal_pass']} | Kabul {DEBUG['global_search_accepted']}\n"        f"Public keşif: sorgu {DEBUG['peer_discovery_queries']} | Bulunan {DEBUG['peer_discovery_found']} | Taranan {DEBUG['peer_discovery_scanned']} | Mesaj {DEBUG['peer_discovery_messages']} | NC {DEBUG['peer_discovery_geo_pass']} | Aday {DEBUG['peer_discovery_signal_pass']} | Kabul {DEBUG['peer_discovery_accepted']}\n"
        f"Coğrafya geçti: {DEBUG['geography_pass']}\n"
        f"Intent/keyword adayı: {DEBUG['signal_pass']}\n"
        f"Kabul edilen: {DEBUG['accepted']}\n"
        f"REVIEW ön aday: {DEBUG['review_candidates']} | Kaliteli: {DEBUG['review_qualified']} | Kaydedilen: {DEBUG['review_saved']}\n"
        f"REVIEW eleme: {', '.join(f'{k}:{v}' for k, v in DEBUG['review_reject_reasons'].most_common(6)) or '-'}\n"
        f"Ek sıkı eleme: {strict_extra_rejects}\n"        f"Global public eleme: {global_search_rejects}\n"        f"Public keşif eleme: {peer_discovery_rejects}\n"
        f"Sınıflar: {classes}\n"
        f"Diller: {langs}\n"
        f"Eleme nedenleri: {rejects}\n"
        f"Web sağlayıcı: {sources}\n"
        f"Web platform: {platforms}\n"
        f"Web kabul: {DEBUG['web_accepted']}\n"
        f"Web eleme nedenleri: {web_rejects}\n"
        f"Web provider durumu: {provider_errors}\n"
        f"Gerçek hata: {total_errors}"
    )
    core.telegram(msg[:3900])
    try:
        for row in sorted(DEBUG["review_samples"], key=lambda x: x.get("score", 0), reverse=True):
            print("LEAD_RADAR_REVIEW_CURRENT", json.dumps(row, ensure_ascii=False))
    except Exception as exc:
        DEBUG["errors"].append(f"review_debug:{type(exc).__name__}:{exc}")
    print("LEAD_RADAR_DEBUG", json.dumps(_serializable_debug(), ensure_ascii=False))


def run() -> None:
    radar.main()
    save_and_notify_debug()


if __name__ == "__main__":
    run()
