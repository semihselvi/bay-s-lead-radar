from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

VERSION = "1.0.0-russian-public-buyer"
COLLECTION = os.getenv("FIRESTORE_COLLECTION", "bay_s_leads")
SCAN_COLLECTION = os.getenv("FIRESTORE_RU_PUBLIC_SCAN_COLLECTION", "bay_s_ru_public_scans")
DRY_RUN = os.getenv("RADAR_DRY_RUN", "1").strip().lower() not in {"0", "false", "no"}
TIMEOUT = int(os.getenv("RADAR_HTTP_TIMEOUT", "20"))
MAX_PER_QUERY = int(os.getenv("RADAR_RU_PUBLIC_MAX_PER_QUERY", "10"))
CMTT_COMMENT_ENTRY_LIMIT = int(os.getenv("RADAR_CMTT_COMMENT_ENTRY_LIMIT", "20"))

SOURCES = {
    "VK": "vk.com",
    "OK": "ok.ru",
    "Pikabu": "pikabu.ru",
    "MailRu Answers": "otvet.mail.ru",
    "VC.ru": "vc.ru",
    "DTF": "dtf.ru",
}

# Public/search-indexed content only. We do not authenticate to or bypass controls
# on any social platform. Search engines are used as discovery adapters.
QUERIES = [
    '"Северный Кипр" "хочу купить" квартиру',
    '"Северный Кипр" "планирую купить" недвижимость',
    '"Северный Кипр" "ищу квартиру" купить',
    '"Северный Кипр" "где купить" квартиру',
    '"Северный Кипр" "стоит ли покупать" квартиру',
    '"Северный Кипр" "рассматриваю покупку" недвижимость',
    '"Северный Кипр" "бюджет" "купить" квартиру',
    '"Северный Кипр" "для инвестиций" "купить" квартиру',
    '"Искеле" "хочу купить" квартиру',
    '"Лонг Бич" "хочу купить" квартиру',
    '"Фамагуста" "хочу купить" квартиру',
    '"Гирне" "хочу купить" квартиру',
]

QUERY_LIMIT = max(1, min(int(os.getenv("RADAR_RU_PUBLIC_QUERY_LIMIT", str(len(QUERIES))) or str(len(QUERIES))), len(QUERIES)))

CMTT_TERMS = [
    "Северный Кипр",
    "Искеле",
    "Лонг Бич",
    "Гирне",
    "Фамагуста",
]

CMTT_SITES = {
    "VC.ru": ("https://vc.ru", "https://api.vc.ru"),
    "DTF": ("https://dtf.ru", "https://api.dtf.ru"),
}

CMTT_API_VERSIONS = ("v2.6", "v2.31")
CMTT_DEBUG = Counter()
CMTT_SAMPLES: dict[str, Any] = {}

NC_RE = re.compile(
    r"(?:северн\w*\s+кипр\w*|искел\w*|лонг\s+бич|фамагуст\w*|гирн\w*|"
    r"кирен\w*|алсанджак|лапт\w*|эсентеп\w*|татлысу|бафр\w*|боаз\w*|"
    r"гюзельюрт|north(?:ern)?\s+cyprus|iskele|long\s+beach|famagust\w*|kyrenia|girne)",
    re.I,
)

BUY_RE = re.compile(
    r"(?:"
    r"\bхочу\s+купить\b|\bхотим\s+купить\b|\bпланир\w*\s+купить\b|"
    r"\bрассматрива\w*\s+(?:покупк\w*|вариант\w*.{0,80}(?:покупк\w*|приобрет\w*))\b|\bсобира\w*\s+купить\b|"
    r"\bкуплю\b|\bищу\b.{0,100}\b(?:для\s+покупк\w*|купить)\b|"
    r"\bгде\s+(?:лучше\s+)?купить\b|\bстоит\s+ли\s+покупать\b|"
    r"\bкакую\s+(?:квартир\w*|недвижимост\w*|вилл\w*|дом\w*)\s+купить\b|"
    r"\bчто\s+можно\s+купить\b|\bподбира\w*\b.{0,80}\b(?:квартир\w*|вилл\w*|дом\w*|недвижимост\w*)\b|"
    r"\blooking\s+to\s+buy\b|\bwant(?:ing)?\s+to\s+buy\b|\bplanning\s+to\s+buy\b"
    r")",
    re.I | re.S,
)

PROPERTY_RE = re.compile(
    r"(?:квартир\w*|апартамент\w*|вилл\w*|дом\w*|недвижимост\w*|студи\w*|"
    r"земл\w*|участ\w*|property|apartment|flat|villa|house|studio|land)",
    re.I,
)

PERSONAL_RE = re.compile(
    r"(?:"
    r"\b(?:я|мы)\s+(?:хочу|хотим|планир\w*|собира\w*|рассматрива\w*)\b|"
    r"\b(?:хочу|хотим|ищу|ищем|планирую|планируем|собираюсь|собираемся|рассматриваю|рассматриваем)\b|"
    r"\b(?:мне|нам)\s+нужн\w*\b|\b(?:я|мы)\s+ищ\w*\b|"
    r"\bподскажите\b|\bпосоветуйте\b|\bкто\s+покупал\b|"
    r"\b(?:i|we)\s+(?:want|plan|are\s+planning|am\s+looking|are\s+looking)\b"
    r")",
    re.I,
)

TENANT_RE = re.compile(
    r"(?:\bхочу\s+снять\b|\bсниму\b|\bищу\b.{0,100}\b(?:в\s+аренд\w*|снять|долгосроч\w*|посуточ\w*)\b|"
    r"\bнужн(?:а|ы|о)\b.{0,100}\b(?:на\s+месяц|на\s+год|в\s+аренд\w*)\b|"
    r"\blooking\s+to\s+rent\b|\bwant\s+to\s+rent\b)",
    re.I | re.S,
)

SELLER_RE = re.compile(
    r"(?:\bпродаю\b|\bпродам\b|\bпрода[её]тся\b|\bсдаю\b|\bсдам\b|\bсда[её]тся\b|"
    r"\bв\s+продаже\b|\bдоступн\w*\s+квартир\w*\b|\bнаши\s+(?:объект\w*|проект\w*)\b|"
    r"\bпредлагаем\b.{0,80}\b(?:квартир\w*|вилл\w*|недвижимост\w*)\b|"
    r"\bfor\s+sale\b|\bavailable\s+units?\b|\bour\s+properties\b)",
    re.I | re.S,
)

PROVIDER_RE = re.compile(
    r"(?:\bагентств\w*\b|\bриелтор\w*\b|\bриэлтор\w*\b|\bзастройщик\w*\b|"
    r"\bкомисси\w*\b|\bпишите\s+(?:в\s+лс|мне)\b|\bwhatsapp\b|"
    r"\btelegram\b.{0,30}\b(?:менеджер|отдел\s+продаж)\b|"
    r"\breal\s+estate\s+agency\b|\brealtor\b|\bdeveloper\b|\bcontact\s+us\b)",
    re.I | re.S,
)

COMMERCIAL_BRAND_RE = re.compile(
    r"(?:"
    r"\bкомпан(?:ия|ии|ию)\b.{0,120}\b(?:недвижимост|аренд|продаж|услуг)\w*\b|"
    r"\bмы\s+специализиру\w*\b|\bмы\s+предлага\w*\b|\bу\s+нас\s+есть\b|"
    r"\bнаши\s+(?:объект\w*|клиент\w*|услуг\w*|предложен\w*)\b|"
    r"\bзвоните\s+нам\b|\bпосетите\s+наш\s+сайт\b|\bоставьте\s+заявк\w*\b|"
    r"\bcompany\b.{0,100}\b(?:property|real\s+estate|rent|sale|services?)\b|"
    r"\bwe\s+(?:speciali[sz]e|offer|provide|manage)\b"
    r")",
    re.I | re.S,
)

COMPLETED_RE = re.compile(
    r"(?:\bуже\s+купил\w*\b|\bмы\s+купили\b|\bя\s+купил\w*\b|\bпокупк\w*\s+завершен\w*\b|"
    r"\bпередумал\w*\b|\bуже\s+не\s+ищу\b|\balready\s+purchased\b|\bfound\s+a\s+property\b)",
    re.I,
)

BUDGET_RE = re.compile(
    r"(?:[£€$₽]\s?\d[\d\s.,]*|\b\d[\d\s.,]*\s?(?:gbp|eur|usd|евро|доллар(?:ов|а)?|"
    r"руб(?:лей)?|тыс\.?\s*(?:евро|долларов)|млн)\b)",
    re.I,
)

TIME_RE = re.compile(
    r"(?:\bв\s+(?:этом|следующем)\s+месяц\w*\b|\bв\s+течени[еи]\s+\d+\s+месяц\w*\b|"
    r"\bв\s+(?:этом|следующем)\s+году\b|\bскоро\b|\bв\s+ближайшее\s+время\b|"
    r"\bthis\s+month\b|\bnext\s+month\b|\bthis\s+year\b|\bsoon\b)",
    re.I,
)

REGION_RE = re.compile(
    r"(Северн\w*\s+Кипр\w*|Искел\w*|Лонг\s+Бич|Фамагуст\w*|Гирн\w*|Кирен\w*|"
    r"Алсанджак|Лапт\w*|Эсентеп\w*|Татлысу|Бафр\w*)",
    re.I,
)


def normalize(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def platform_from_url(url: str) -> str:
    low = (url or "").lower()
    for platform, domain in SOURCES.items():
        if domain in low:
            return platform
    return "Russian Public Web"


def extract_budget(text: str) -> str:
    m = BUDGET_RE.search(text or "")
    return normalize(m.group(0)) if m else ""


def extract_region(text: str) -> str:
    m = REGION_RE.search(text or "")
    return normalize(m.group(0)) if m else ""


def classify_candidate(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    blob = normalize(f"{item.get('title', '')} {item.get('text', '')}")
    if not blob:
        return None, "empty"
    if not (NC_RE.search(blob) or bool(item.get("north_cyprus_context"))):
        return None, "no_north_cyprus_context"
    if TENANT_RE.search(blob):
        return None, "tenant"
    if COMPLETED_RE.search(blob):
        return None, "completed_or_cancelled"
    if SELLER_RE.search(blob):
        return None, "seller_or_listing"
    if PROVIDER_RE.search(blob) or COMMERCIAL_BRAND_RE.search(blob):
        return None, "provider_or_agent"
    if not PROPERTY_RE.search(blob):
        return None, "no_property"
    if not BUY_RE.search(blob):
        return None, "no_explicit_purchase_intent"
    if not PERSONAL_RE.search(blob):
        return None, "not_personal_enough"

    budget = extract_budget(blob)
    region = extract_region(blob)
    timeframe = bool(TIME_RE.search(blob))
    score = 72
    reasons = ["explicit_purchase_intent", "north_cyprus_context", "personal_request"]

    if budget:
        score += 12
        reasons.append("budget_present")
    if region:
        score += 6
        reasons.append("region_present")
    if timeframe:
        score += 6
        reasons.append("timeframe_present")
    if any(x in blob.lower() for x in ["инвест", "доходност", "для инвестиц", "rental yield"]):
        score += 4
        reasons.append("investment_signal")

    score = min(score, 98)
    classification = "HOT" if score >= 86 else "WARM"

    return {
        **item,
        "market": "north_cyprus",
        "route_to": "Prime Kıbrıs",
        "lead_class": "HOT BUYER" if classification == "HOT" else "WARM BUYER",
        "classification": classification,
        "intent_type": "BUYER",
        "intent_score": score,
        "estimated_budget": budget,
        "estimated_region": region,
        "lead_reasons": reasons,
        "radar_version": VERSION,
    }, "accepted"


def bing_rss_search(query: str, domain: str) -> list[dict[str, Any]]:
    scoped = f"{query} site:{domain}"
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(scoped)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        out: list[dict[str, Any]] = []
        for item in root.findall(".//item")[:MAX_PER_QUERY]:
            link = item.findtext("link") or ""
            if domain not in link.lower():
                continue
            out.append({
                "source": "Bing RSS",
                "platform": platform_from_url(link),
                "source_type": "public_search_index",
                "url": link,
                "title": normalize(item.findtext("title") or ""),
                "text": normalize(item.findtext("description") or ""),
                "published": normalize(item.findtext("pubDate") or ""),
                "author": "",
                "search_query": query,
            })
        return out
    except Exception:
        return []


def _collect_text_values(value: Any, depth: int = 0) -> list[str]:
    if depth > 5:
        return []

    out: list[str] = []
    if isinstance(value, str):
        text = normalize(value)
        if text and not text.startswith(("http://", "https://")):
            out.append(text)
        return out

    if isinstance(value, list):
        for child in value[:80]:
            out.extend(_collect_text_values(child, depth + 1))
        return out

    if isinstance(value, dict):
        preferred = (
            "title", "intro", "introInFeed", "text", "content", "value",
            "caption", "description", "blocks", "data"
        )
        for key in preferred:
            if key in value:
                out.extend(_collect_text_values(value.get(key), depth + 1))
        return out

    return out


def _cmtt_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            if isinstance(data, dict) and item.get("type") in {"entry", "content", "post"}:
                out.append(data)
            else:
                out.append(item)
        return out

    if not isinstance(payload, dict):
        return []

    # Current VC.ru / DTF search shape:
    # {"result": {"contents": [{"type": "entry", "data": {...}}, ...]}}
    contents = payload.get("contents")
    if isinstance(contents, list):
        out: list[dict[str, Any]] = []
        for wrapper in contents:
            if not isinstance(wrapper, dict):
                continue
            data = wrapper.get("data")
            if isinstance(data, dict):
                out.append(data)
            else:
                out.append(wrapper)
        if out:
            return out

    for key in ("result", "items", "data", "entries", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            rows = _cmtt_entries(value)
            if rows:
                return rows
        if isinstance(value, dict):
            nested = _cmtt_entries(value)
            if nested:
                return nested

    return []

def cmtt_public_search() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for platform, (site_base, api_base) in CMTT_SITES.items():
        session = requests.Session()
        session.headers.update({
            "User-Agent": f"{platform.lower().replace('.', '')}-app/2.2.0; release "
            "(GitHubActions; Linux/1; ru_RU; 1080x1920)",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        })

        try:
            session.get(site_base + "/", timeout=min(TIMEOUT, 10))
        except Exception:
            pass

        working_version = ""
        for term in CMTT_TERMS:
            payload = None

            versions = (working_version,) if working_version else CMTT_API_VERSIONS
            for version in versions:
                if not version:
                    continue
                try:
                    response = session.get(
                        f"{api_base}/{version}/search",
                        params={"query": term, "orderBy": "date", "page": 1},
                        timeout=min(TIMEOUT, 8),
                    )
                    CMTT_DEBUG[f"{platform}:{version}:http_{response.status_code}"] += 1
                    if response.status_code != 200:
                        continue

                    candidate = response.json()
                    entries = _cmtt_entries(candidate)
                    if entries:
                        payload = candidate
                        working_version = version
                        CMTT_DEBUG[f"{platform}:{version}:usable"] += 1
                        break

                    sample_key = f"{platform}:{version}"
                    if sample_key not in CMTT_SAMPLES:
                        raw = normalize(response.text)
                        CMTT_SAMPLES[sample_key] = {
                            "top_keys": list(candidate.keys())[:30] if isinstance(candidate, dict) else [],
                            "result_type": type(candidate.get("result")).__name__ if isinstance(candidate, dict) else type(candidate).__name__,
                            "raw_prefix": raw[:1400],
                        }
                    CMTT_DEBUG[f"{platform}:{version}:empty_or_unparsed"] += 1
                except Exception:
                    continue

            if payload is None:
                continue

            for entry in _cmtt_entries(payload)[:25]:
                entry_id = entry.get("id") or entry.get("entryId") or entry.get("contentId") or ""
                title = normalize(str(entry.get("title") or ""))
                pieces = _collect_text_values(entry)
                text = normalize(" ".join(pieces))

                if not title and not text:
                    continue

                author_obj = entry.get("author") or {}
                author = ""
                if isinstance(author_obj, dict):
                    author = normalize(str(
                        author_obj.get("name")
                        or author_obj.get("title")
                        or author_obj.get("username")
                        or ""
                    ))

                url = str(entry.get("webviewUrl") or entry.get("url") or "")
                if not url and entry_id:
                    url = f"{site_base}/{entry_id}"

                rows.append({
                    "source": f"{platform} API",
                    "platform": platform,
                    "source_type": "public_platform_api",
                    "url": url,
                    "title": title,
                    "text": text[:9000],
                    "published": str(entry.get("dateRFC") or entry.get("date") or ""),
                    "author": author,
                    "search_query": term,
                    "api_version": working_version,
                    "entry_id": str(entry_id),
                })

    return rows


def _cmtt_comment_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("items", "comments"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    for key in ("result", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _cmtt_comment_items(value)
            if nested:
                return nested

    return []


def cmtt_public_comments(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch public comments only for North-Cyprus-context search entries."""
    out: list[dict[str, Any]] = []
    eligible = []

    for row in entries:
        blob = normalize(f"{row.get('title', '')} {row.get('text', '')}")
        if not NC_RE.search(blob):
            continue
        if not row.get("entry_id"):
            continue
        eligible.append(row)

    # De-duplicate entries returned by multiple search terms before requesting comments.
    unique_entries: list[dict[str, Any]] = []
    seen_entries: set[tuple[str, str]] = set()
    for row in eligible:
        key = (str(row.get("platform") or ""), str(row.get("entry_id") or ""))
        if key in seen_entries:
            continue
        seen_entries.add(key)
        unique_entries.append(row)

    for row in unique_entries[:max(0, CMTT_COMMENT_ENTRY_LIMIT)]:
        platform = str(row.get("platform") or "")
        site = CMTT_SITES.get(platform)
        if not site:
            continue
        site_base, api_base = site
        entry_id = str(row.get("entry_id") or "")
        if not entry_id:
            continue

        session = requests.Session()
        session.headers.update({
            "User-Agent": f"{platform.lower().replace('.', '')}-app/2.2.0; release "
            "(GitHubActions; Linux/1; ru_RU; 1080x1920)",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        })

        try:
            response = session.get(
                f"{api_base}/v2.6/comments",
                params={"contentId": entry_id, "sorting": "date"},
                timeout=min(TIMEOUT, 8),
            )
            CMTT_DEBUG[f"{platform}:comments:http_{response.status_code}"] += 1
            if response.status_code != 200:
                continue

            payload = response.json()
            comments = _cmtt_comment_items(payload)
            CMTT_DEBUG[f"{platform}:comments:items"] += len(comments)

            for comment in comments[:100]:
                cid = comment.get("id") or comment.get("commentId") or ""
                text_parts = _collect_text_values(comment)
                comment_text = normalize(" ".join(text_parts))
                if not comment_text:
                    continue

                author_obj = comment.get("author") or comment.get("user") or {}
                author = ""
                if isinstance(author_obj, dict):
                    author = normalize(str(
                        author_obj.get("name")
                        or author_obj.get("title")
                        or author_obj.get("username")
                        or ""
                    ))

                url = str(row.get("url") or "")
                if not url and entry_id:
                    url = f"{site_base}/{entry_id}"
                if cid and url:
                    separator = "&" if "?" in url else "?"
                    url = f"{url}{separator}comment={cid}"

                out.append({
                    "source": f"{platform} Comments API",
                    "platform": platform,
                    "source_type": "public_comment",
                    "url": url,
                    "title": normalize(str(row.get("title") or "")),
                    "text": comment_text[:6000],
                    "published": str(comment.get("dateRFC") or comment.get("date") or ""),
                    "author": author,
                    "search_query": str(row.get("search_query") or ""),
                    "entry_id": entry_id,
                    "comment_id": str(cid),
                    "north_cyprus_context": True,
                    "parent_entry_title": normalize(str(row.get("title") or "")),
                })
        except Exception as exc:
            CMTT_DEBUG[f"{platform}:comments:error_{type(exc).__name__}"] += 1

        # Public API documentation asks clients to stay below 3 requests/sec.
        time.sleep(0.36)

    return out


def serper_search(query: str, domain: str) -> list[dict[str, Any]]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    scoped = f"{query} site:{domain} after:{cutoff}"

    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": scoped,
                "num": MAX_PER_QUERY,
                "hl": "ru",
                "gl": "ru",
                "tbs": "qdr:m3",
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []

        out = []
        for x in r.json().get("organic", []) or []:
            link = x.get("link", "")
            if not link or domain not in link.lower():
                continue

            out.append({
                "source": "Serper",
                "platform": platform_from_url(link),
                "source_type": "public_search_index",
                "url": link,
                "title": normalize(x.get("title", "")),
                "text": normalize(x.get("snippet", "")),
                "published": x.get("date", "") or "",
                "author": "",
                "search_query": query,
            })

        return out[:MAX_PER_QUERY]
    except Exception:
        return []


def exa_search(query: str, domain: str) -> list[dict[str, Any]]:
    api_key = os.getenv("EXA_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        r = requests.post(
            "https://api.exa.ai/search",
            json={
                "query": query,
                "type": "auto",
                "numResults": MAX_PER_QUERY,
                "includeDomains": [domain],
                "contents": {"text": True},
            },
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []

        out = []
        for x in r.json().get("results", [])[:MAX_PER_QUERY]:
            link = x.get("url", "")
            if not link or domain not in link.lower():
                continue
            out.append({
                "source": "Exa",
                "platform": platform_from_url(link),
                "source_type": "public_search_index",
                "url": link,
                "title": normalize(x.get("title", "")),
                "text": normalize(x.get("text", ""))[:5000],
                "published": x.get("publishedDate", "") or "",
                "author": x.get("author", "") or "",
                "search_query": query,
            })
        return out
    except Exception:
        return []


def enrich_public_page(item: dict[str, Any]) -> dict[str, Any]:
    """Best-effort public HTML enrichment. Never logs in or bypasses controls."""
    url = item.get("url", "")
    if not url:
        return item

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
            },
            timeout=min(TIMEOUT, 12),
            allow_redirects=True,
        )
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            return item

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        page_text = normalize(soup.get_text(" ", strip=True))
        if 80 <= len(page_text) <= 200000:
            item = dict(item)
            item["text"] = normalize(f"{item.get('text', '')} {page_text[:7000]}")
        return item
    except Exception:
        return item


def fingerprint(item: dict[str, Any]) -> str:
    raw = "|".join([
        item.get("platform", ""),
        item.get("url", ""),
        item.get("title", ""),
    ]).lower()
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def firestore_client():
    from google.cloud import firestore
    from google.oauth2 import service_account

    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON missing")

    creds = service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)


def telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": text[:3900],
                "disable_web_page_preview": False,
            },
            timeout=10,
        ).raise_for_status()
    except Exception:
        pass


def scan() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    seen: set[str] = set()
    leads: list[dict[str, Any]] = []

    stats = {
        "version": VERSION,
        "dry_run": DRY_RUN,
        "raw_by_platform": Counter(),
        "accepted_by_platform": Counter(),
        "reject_reasons": Counter(),
        "provider_counts": Counter(),
        "reject_samples": {},
        "queries": 0,
    }

    def remember_reject(reason: str, row: dict[str, Any]) -> None:
        bucket = stats["reject_samples"].setdefault(reason, [])
        if len(bucket) >= 3:
            return
        bucket.append({
            "platform": row.get("platform", ""),
            "title": normalize(str(row.get("title") or ""))[:240],
            "text": normalize(str(row.get("text") or ""))[:420],
            "url": row.get("url", ""),
        })

    cmtt_rows = cmtt_public_search()

    for row in cmtt_rows:
        key = fingerprint(row)
        if key in seen:
            continue

        seen.add(key)
        platform = str(row.get("platform") or "CMTT")
        stats["raw_by_platform"][platform] += 1
        stats["provider_counts"][str(row.get("source") or "CMTT API")] += 1

        lead, reason = classify_candidate(row)
        if not lead:
            stats["reject_reasons"][reason] += 1
            remember_reject(reason, row)
            continue

        lead["lead_id"] = key
        lead["found_at"] = started.isoformat()
        stats["accepted_by_platform"][platform] += 1
        leads.append(lead)

    for row in cmtt_public_comments(cmtt_rows):
        key = fingerprint(row)
        if key in seen:
            continue

        seen.add(key)
        platform = str(row.get("platform") or "CMTT")
        stats["raw_by_platform"][f"{platform} comments"] += 1
        stats["provider_counts"][str(row.get("source") or "CMTT Comments API")] += 1

        lead, reason = classify_candidate(row)
        if not lead:
            comment_reason = f"comment:{reason}"
            stats["reject_reasons"][comment_reason] += 1
            remember_reject(comment_reason, row)
            continue

        lead["lead_id"] = key
        lead["found_at"] = started.isoformat()
        stats["accepted_by_platform"][f"{platform} comments"] += 1
        leads.append(lead)

    for platform, domain in SOURCES.items():
        if platform in {"VC.ru", "DTF"}:
            continue
        for query in QUERIES[:QUERY_LIMIT]:
            stats["queries"] += 1

            rows = serper_search(query, domain)
            if not rows:
                rows = exa_search(query, domain)
            if not rows:
                rows = bing_rss_search(query, domain)

            for row in rows:
                stats["provider_counts"][str(row.get("source") or "unknown")] += 1
                key = fingerprint(row)
                if key in seen:
                    continue

                seen.add(key)
                stats["raw_by_platform"][platform] += 1

                snippet = normalize(f"{row.get('title', '')} {row.get('text', '')}")
                if NC_RE.search(snippet) and (BUY_RE.search(snippet) or PROPERTY_RE.search(snippet)):
                    row = enrich_public_page(row)

                lead, reason = classify_candidate(row)
                if not lead:
                    stats["reject_reasons"][reason] += 1
                    continue

                lead["lead_id"] = key
                lead["found_at"] = started.isoformat()
                stats["accepted_by_platform"][platform] += 1
                leads.append(lead)

    leads.sort(
        key=lambda x: (
            -int(x.get("intent_score", 0)),
            x.get("platform", ""),
            x.get("url", ""),
        )
    )

    if not DRY_RUN:
        client = firestore_client()
        saved = []

        for lead in leads:
            ref = client.collection(COLLECTION).document(lead["lead_id"])
            if ref.get().exists:
                continue

            ref.set(lead)
            saved.append(lead)

            telegram(
                f"{'🔥' if lead['classification'] == 'HOT' else '🟡'} "
                f"PRIME RADAR | {lead['lead_class']}\n\n"
                f"Platform: {lead['platform']}\n"
                f"Bölge: {lead.get('estimated_region') or '-'}\n"
                f"Bütçe: {lead.get('estimated_budget') or '-'}\n"
                f"Intent: {lead['intent_score']}/100\n\n"
                f"{lead.get('title', '')[:500]}\n\n"
                f"🔗 {lead.get('url', '')}"
            )

        client.collection(SCAN_COLLECTION).document(
            started.strftime("%Y%m%dT%H%M%SZ")
        ).set({
            "version": VERSION,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": False,
            "raw_by_platform": dict(stats["raw_by_platform"]),
            "accepted_by_platform": dict(stats["accepted_by_platform"]),
            "reject_reasons": dict(stats["reject_reasons"]),
            "provider_counts": dict(stats["provider_counts"]),
            "accepted": len(leads),
            "saved_new": len(saved),
            "queries": stats["queries"],
        })

    return {
        "version": VERSION,
        "dry_run": DRY_RUN,
        "unique_results": len(seen),
        "accepted": len(leads),
        "raw_by_platform": dict(stats["raw_by_platform"]),
        "accepted_by_platform": dict(stats["accepted_by_platform"]),
        "reject_reasons": dict(stats["reject_reasons"]),
        "provider_counts": dict(stats["provider_counts"]),
        "cmtt_debug": dict(CMTT_DEBUG),
        "reject_samples": stats["reject_samples"],
        "comment_candidates": sum(v for k, v in stats["raw_by_platform"].items() if k.endswith(" comments")),
        "leads": leads[:50],
    }


def main() -> None:
    print(json.dumps(scan(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
