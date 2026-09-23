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

import requests

import main as core

VERSION = "1.1-project-intent-precision"
COLLECTION = "northlab_sales_project_leads"
SCAN_COLLECTION = "northlab_sales_project_scans"
TELEGRAM_HOURS = int(os.getenv("NORTHLAB_TELEGRAM_HOURS", "24"))
PER_GROUP_LIMIT = int(os.getenv("NORTHLAB_PER_GROUP_LIMIT", "100"))
MAX_ALERTS = int(os.getenv("NORTHLAB_MAX_ALERTS", "12"))
WEB_QUERY_LIMIT = int(os.getenv("NORTHLAB_WEB_QUERY_LIMIT", "16"))

PROJECT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("WEBSITE", re.compile(
        r"(?:\bwebsite\b|\bweb\s*site\b|\blanding\s*page\b|\bweb\s*design\b|\bweb\s*developer\b|"
        r"\bweb\s+sitesi\b|\bweb\s+sayfas[ıi]\b|\bsite\s+yapt[ıi]r|\bsite\s+yenile|"
        r"\bсайт\w*\b|\bвеб[-\s]?сайт\w*\b|\bлендинг\w*\b|\bвеб[-\s]?разработ\w*\b)",
        re.I,
    )),
    ("CRM", re.compile(
        r"(?:\bcrm\b|customer\s+relationship|m[üu][şs]teri\s+takip|m[üu][şs]teri\s+y[öo]netim|"
        r"\bсрм\b|\bcrm[-\s]?систем\w*\b|\bуч[её]т\s+клиент\w*\b)",
        re.I,
    )),
    ("BOOKING", re.compile(
        r"(?:booking\s+system|reservation\s+system|online\s+booking|appointment\s+system|"
        r"rezervasyon\s+sistemi|randevu\s+sistemi|online\s+rezervasyon|"
        r"систем\w*\s+бронирован\w*|онлайн[-\s]?бронирован\w*|систем\w*\s+запис\w*)",
        re.I,
    )),
    ("AUTOMATION", re.compile(
        r"(?:automation|automate|workflow\s+automation|whatsapp\s+automation|"
        r"otomasyon|otomatikle[sş]tir|whatsapp\s+otomasyon|"
        r"автоматизац\w*|автоматизир\w*|whatsapp[-\s]?бот\w*)",
        re.I,
    )),
    ("ADMIN_PANEL", re.compile(
        r"(?:admin\s+panel|dashboard|backoffice|back[-\s]?office|y[öo]netim\s+paneli|admin\s+ekran[ıi]|"
        r"админ[-\s]?панел\w*|личн\w*\s+кабинет\w*|панел\w*\s+управлен\w*)",
        re.I,
    )),
    ("PAYMENT", re.compile(
        r"(?:payment\s+integration|online\s+payment|payment\s+gateway|sanal\s+pos|online\s+[öo]deme|"
        r"[öo]deme\s+entegrasyon|интеграц\w*\s+оплат\w*|онлайн[-\s]?оплат\w*)",
        re.I,
    )),
    ("ECOMMERCE", re.compile(
        r"(?:e[-\s]?commerce|online\s+store|web\s+shop|e[-\s]?ticaret|online\s+ma[gğ]aza|"
        r"интернет[-\s]?магазин\w*|онлайн[-\s]?магазин\w*)",
        re.I,
    )),
    ("MULTILINGUAL", re.compile(
        r"(?:multilingual\s+website|multi[-\s]?language\s+site|çok\s+dilli\s+site|"
        r"rusça\s+site|ingilizce\s+site|многоязычн\w*\s+сайт\w*|сайт\w*\s+на\s+(?:английск|русск|турецк))",
        re.I,
    )),
]

DEMAND_RE = re.compile(
    r"(?:"
    r"\blooking\s+for\b|\bneed\b|\bneed\s+someone\b|\bcan\s+anyone\s+recommend\b|"
    r"\bwant\s+to\s+(?:build|create|redo|redesign|develop)\b|\bquote\s+for\b|\bproposal\s+for\b|"
    r"\bar[ıi]yorum\b|\blaz[ıi]m\b|\bihtiyac[ıi]m[ıi]z\b|\byapt[ıi]rmak\s+istiyorum\b|"
    r"\bteklif\s+almak\s+istiyorum\b|\byenilemek\s+istiyorum\b|"
    r"\bищу\b|\bнужен\b|\bнужна\b|\bнужно\b|\bпосоветуйте\b|\bкто\s+может\b|"
    r"\bхотим\s+(?:сделать|создать|обновить|разработать)\b|\bнужен\s+подрядчик\b"
    r")",
    re.I,
)

PROBLEM_RE = re.compile(
    r"(?:"
    r"website\s+(?:is\s+)?(?:old|outdated|slow|broken|not\s+working)|site\s+(?:is\s+)?down|"
    r"old\s+website|redesign\s+our\s+website|"
    r"site(?:miz|m)\s+(?:eski|yava[sş]|[çc]al[ıi][sş]m[ıi]yor)|web\s+sitemiz\s+eski|"
    r"сайт\s+(?:старый|устарел|медленн|не\s+работает)|обновить\s+сайт|переделать\s+сайт"
    r")",
    re.I,
)

PARTNER_RE = re.compile(
    r"(?:white[-\s]?label|subcontract|outsourc|agency\s+partner|development\s+partner|"
    r"ta[sş]eron|ajans\s+partner|yaz[ıi]l[ıi]m\s+partner|"
    r"субподряд\w*|white[-\s]?label|партн[её]р\w*\s+(?:агентств|разработ))",
    re.I,
)

BUSINESS_RE = re.compile(
    r"(?:\bour\s+(?:company|business|restaurant|hotel|clinic|agency|shop)\b|\bmy\s+(?:company|business|shop)\b|"
    r"\bfirmam[ıi]z\b|\bi[sş]letmemiz\b|\brestoran[ıi]m[ıi]z\b|\bklini[gğ]imiz\b|"
    r"\bнаш\w*\s+(?:компан\w*|фирм\w*|клиник\w*|ресторан\w*|агентств\w*|магазин\w*)\b|\bмой\s+бизнес\b)",
    re.I,
)

SPECIFICITY_RE = re.compile(
    r"(?:\b(?:today|tomorrow|this\s+week|next\s+week|urgent|asap|budget|deadline)\b|"
    r"\b(?:bug[üu]n|yar[ıi]n|bu\s+hafta|acil|b[üu]t[çc]e|teslim\s+tarihi)\b|"
    r"\b(?:срочно|сегодня|завтра|на\s+этой\s+неделе|бюджет|срок)\b|"
    r"(?:£|€|\$)\s?\d+|\b\d+[\s.,]?\d*\s?(?:gbp|eur|usd|tl|try|руб))",
    re.I,
)

JOB_SEEKER_RE = re.compile(
    r"(?:"
    r"\blooking\s+for\s+(?:a\s+)?job\b|\bseeking\s+work\b|\bavailable\s+for\s+work\b|"
    r"\bmy\s+(?:cv|resume)\b|\bfreelancer\s+available\b|"
    r"\bi[sş]\s+ar[ıi]yorum\b|\b[çc]al[ıi][sş]acak\s+i[sş]\s+ar[ıi]yorum\b|\bcv\b.{0,40}\bi[sş]\b|"
    r"\bищу\s+работу\b|\bв\s+поиске\s+работы\b|\bмо[её]\s+резюме\b|\bготов\w*\s+к\s+работе\b"
    r")",
    re.I,
)

EMPLOYMENT_RE = re.compile(
    r"(?:"
    r"\bfull[-\s]?time\b|\bpart[-\s]?time\b|\bsalary\b|\bvacancy\b|\bjob\s+opening\b|\bemployment\b|"
    r"\bmaa[sş]\b|\btam\s+zamanl[ıi]\b|\byar[ıi]\s+zamanl[ıi]\b|\bi[sş]\s+ilan[ıi]\b|"
    r"\bваканси\w*\b|\bзарплат\w*\b|\bполная\s+занятость\b|\bчастичная\s+занятость\b"
    r")",
    re.I,
)

SUPPLY_RE = re.compile(
    r"(?:"
    r"\bwe\s+(?:build|create|design|develop)\s+(?:websites?|crm|software)\b|"
    r"\bi\s+(?:build|create|design|develop)\s+(?:websites?|crm|software)\b|"
    r"\bour\s+services?\b.{0,80}\b(?:web\s+design|software\s+development)\b|"
    r"\bweb\s+tasar[ıi]m\s+hizmeti\b|\byaz[ıi]l[ıi]m\s+hizmeti\b|"
    r"\bсозда[её]м\s+сайт\w*\b|\bразрабатыва[её]м\s+сайт\w*\b|\bнаши\s+услуги\b.{0,80}\bсайт\w*\b"
    r")",
    re.I | re.S,
)

EDUCATION_RE = re.compile(
    r"(?:\bhomework\b|\bassignment\b|\bcourse\b|\btutorial\b|\blearn\s+web\s+development\b|"
    r"\b[öo]dev\b|\bkurs\b|\bders\b|\bучебн\w*\b|\bкурс\w*\b|\bдомашн\w*\s+задан\w*\b)",
    re.I,
)


BOT_AUTHOR_RE = re.compile(r"(?:^|[_-])bot$", re.I)

MARKETPLACE_AD_RE = re.compile(
    r"(?:pulsemarket|новое\s+объявление|цена\s*[:：]|больше\s+фотографий|"
    r"смотреть\s+на\s+сайте|подключить\s+алерты|#.*спрос)",
    re.I | re.S,
)

PORTAL_SUPPORT_RE = re.compile(
    r"(?:"
    r"permissions\.gov|staypermit|government\s+portal|"
    r"не\s+могу\s+зайти\s+в\s+личн\w*\s+кабинет|"
    r"пользователь\s+не\s+найден|аккаунт\w*\s+уже\s+существует|"
    r"смена\s+номера\s+телефона|куда\s+обращаться|"
    r"cannot\s+log\s+in|account\s+already\s+exists|user\s+not\s+found|"
    r"hesab(?:ı|i)ma\s+giremiyorum|kullanıcı\s+bulunamadı|hesap\s+zaten\s+mevcut"
    r")",
    re.I | re.S,
)

DOCUMENT_ACCOUNT_CONTEXT_RE = re.compile(
    r"(?:"
    r"список\s+документ\w*|банковск\w*\s+выписк\w*|"
    r"если\s+в\s+списке\s+документов|"
    r"document\s+list|bank\s+statement|belge\s+listesi|banka\s+ekstresi"
    r")",
    re.I,
)

PROJECT_REQUEST_RE = re.compile(
    r"(?:"
    r"\bneed\s+(?:a|an|new|our|someone|somebody|developer|agency|company)\b.{0,90}\b(?:website|web\s*site|crm|booking\s+system|reservation\s+system|admin\s+panel|automation|payment\s+integration|e[-\s]?commerce)\b|"
    r"\blooking\s+for\s+(?:a|an|someone|somebody|developer|agency|company)\b.{0,90}\b(?:website|web\s*site|crm|booking\s+system|reservation\s+system|admin\s+panel|automation|payment\s+integration|e[-\s]?commerce)\b|"
    r"\bwant\s+to\s+(?:build|create|develop|redesign|redo|replace|integrate|implement|automate)\b.{0,100}\b(?:website|web\s*site|crm|booking\s+system|reservation\s+system|admin\s+panel|dashboard|payment|store)\b|"
    r"\b(?:build|create|develop|redesign|redo|replace|integrate|implement|automate)\b.{0,100}\b(?:website|web\s*site|crm|booking\s+system|reservation\s+system|admin\s+panel|dashboard|payment|store)\b|"
    r"\b(?:web\s+sitesi|crm|rezervasyon\s+sistemi|randevu\s+sistemi|yönetim\s+paneli|otomasyon|sanal\s+pos|e[-\s]?ticaret)\b.{0,100}\b(?:lazım|ihtiyac|arıyorum|yaptır|kur|geliştir|yenile|entegr)\w*|"
    r"\b(?:lazım|ihtiyac|arıyorum|yaptırmak|kurmak|geliştirmek|yenilemek)\w*.{0,100}\b(?:web\s+sitesi|crm|rezervasyon\s+sistemi|yönetim\s+paneli|otomasyon|e[-\s]?ticaret)\b|"
    r"\b(?:нужен|нужна|нужно|ищу|хотим)\b.{0,100}\b(?:сайт\w*|веб[-\s]?сайт\w*|crm|срм|систем\w*.{0,40}бронирован\w*|админ[-\s]?панел\w*|автоматизац\w*|интернет[-\s]?магазин\w*)\b|"
    r"\b(?:создать|сделать|разработать|обновить|переделать|интегрировать|автоматизировать)\w*.{0,100}\b(?:сайт\w*|crm|срм|систем\w*|панел\w*|магазин\w*)\b|"
    r"\b(?:сайт\w*|crm|срм|систем\w*.{0,40}бронирован\w*|админ[-\s]?панел\w*)\b.{0,100}\b(?:нужен|нужна|нужно|ищу|разработать|создать|сделать|обновить)\w*"
    r")",
    re.I | re.S,
)

WEB_QUERIES = [
    '"North Cyprus" "looking for" "website developer"',
    '"North Cyprus" "need a website"',
    '"North Cyprus" "website redesign"',
    '"North Cyprus" "booking system" business',
    '"North Cyprus" CRM business',
    '"North Cyprus" "online booking" developer',
    '"Kuzey Kıbrıs" "web sitesi" arıyorum',
    '"Kuzey Kıbrıs" "web sitesi" yaptırmak',
    '"Kuzey Kıbrıs" "rezervasyon sistemi"',
    '"Северный Кипр" "нужен сайт"',
    '"Северный Кипр" "ищу разработчика"',
    '"Северный Кипр" "система бронирования"',
    'site:facebook.com/groups "North Cyprus" "website"',
    'site:facebook.com/groups "Kuzey Kıbrıs" "web sitesi"',
    'site:facebook.com/groups "Северный Кипр" "сайт"',
    'site:reddit.com Cyprus "need a website"',
]


def detect_language(text: str) -> str:
    if re.search(r"[а-яё]", text or "", re.I):
        return "RU"
    if re.search(r"[çğıöşüİı]", text or ""):
        return "TR"
    if re.search(r"[a-z]", text or "", re.I):
        return "EN"
    return "OTHER"


def project_types(text: str) -> list[str]:
    return [name for name, rx in PROJECT_PATTERNS if rx.search(text or "")]


def classify(text: str) -> tuple[dict[str, Any] | None, str]:
    value = " ".join(str(text or "").split())
    if not value:
        return None, "empty"
    if JOB_SEEKER_RE.search(value):
        return None, "job_seeker"
    if EMPLOYMENT_RE.search(value):
        return None, "employment_vacancy"
    if SUPPLY_RE.search(value):
        return None, "service_provider"
    if EDUCATION_RE.search(value):
        return None, "education"
    if MARKETPLACE_AD_RE.search(value):
        return None, "marketplace_ad"
    if PORTAL_SUPPORT_RE.search(value):
        return None, "portal_account_support"
    if DOCUMENT_ACCOUNT_CONTEXT_RE.search(value) and re.search(r"личн\w*\s+кабинет|account|hesap", value, re.I):
        return None, "document_portal_context"

    types = project_types(value)
    demand = bool(DEMAND_RE.search(value))
    project_request = bool(PROJECT_REQUEST_RE.search(value))
    problem = bool(PROBLEM_RE.search(value))
    partner = bool(PARTNER_RE.search(value))
    business = bool(BUSINESS_RE.search(value))
    specific = bool(SPECIFICITY_RE.search(value))

    if not types and not partner:
        return None, "no_project_signal"

    reasons: list[str] = []
    if partner and demand:
        lead_class = "PARTNER"
        score = 82 + (6 if specific else 0)
        reasons.append("explicit_partner_search")
    elif demand and types and project_request:
        lead_class = "HOT PROJECT" if (specific or business) else "WARM PROJECT"
        score = 88 if lead_class == "HOT PROJECT" else 74
        reasons.append("explicit_project_demand")
    elif problem and types:
        lead_class = "WARM PROJECT" if business else "WATCH"
        score = 70 if business else 56
        reasons.append("digital_problem_signal")
    else:
        return None, "weak_project_signal"

    if specific:
        reasons.append("budget_or_timing_present")
    if business:
        reasons.append("business_context")
    if types:
        reasons.append("project:" + ",".join(types))

    return {
        "lead_class": lead_class,
        "intent_score": min(score, 98),
        "project_types": types,
        "language": detect_language(value),
        "reasons": reasons,
    }, "accepted"


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _lead_id(source: str, url: str, author: str, text: str) -> str:
    raw = "|".join([source, url, author, _norm(text)])
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _notify(lead: dict[str, Any], prefix: str) -> None:
    klass = str(lead.get("lead_class") or "WATCH")
    emoji = "🔥" if klass == "HOT PROJECT" else "🤝" if klass == "PARTNER" else "🟡" if klass == "WARM PROJECT" else "👀"
    msg = (
        f"{emoji} NORTHLAB SALES RADAR | {klass} [{prefix}]\n\n"
        f"Kullanıcı: {lead.get('author') or '-'}\n"
        f"Platform: {lead.get('platform') or lead.get('source') or '-'}\n"
        f"Kaynak: {lead.get('group') or lead.get('title') or '-'}\n"
        f"Dil: {lead.get('language') or '-'} | Intent: {lead.get('intent_score', 0)}/100\n"
        f"İş tipi: {', '.join(lead.get('project_types') or []) or '-'}\n"
        f"Neden: {', '.join(lead.get('reasons') or []) or '-'}\n\n"
        f"{str(lead.get('text') or lead.get('message') or '')[:1200]}\n\n"
        f"🔗 {lead.get('url') or 'Doğrudan link yok'}"
    )
    core.telegram(msg[:3900])


def _save_new(db_client, lead: dict[str, Any], now: datetime) -> bool:
    lead_id = _lead_id(
        str(lead.get("source") or ""),
        str(lead.get("url") or ""),
        str(lead.get("author") or ""),
        str(lead.get("text") or lead.get("message") or ""),
    )
    lead["lead_id"] = lead_id
    ref = db_client.collection(COLLECTION).document(lead_id)
    snap = ref.get()
    payload = dict(lead)
    payload["last_seen_at"] = now.isoformat()
    if snap.exists:
        old = snap.to_dict() or {}
        payload["first_seen_at"] = old.get("first_seen_at") or now.isoformat()
        payload["notified_at"] = old.get("notified_at")
        ref.set(payload, merge=True)
        return not bool(old.get("notified_at"))
    payload["first_seen_at"] = now.isoformat()
    ref.set(payload)
    return True


def _mark_notified(db_client, lead: dict[str, Any], now: datetime) -> None:
    db_client.collection(COLLECTION).document(lead["lead_id"]).set(
        {"notified_at": now.isoformat(), "last_seen_at": now.isoformat()},
        merge=True,
    )


async def scan_telegram(db_client, now: datetime, debug: dict[str, Any]) -> list[dict[str, Any]]:
    if not core.TELEGRAM_API_ID or not core.TELEGRAM_API_HASH or not core.TELEGRAM_SESSION.exists():
        debug["errors"].append("telegram_credentials_or_session_missing")
        return []

    client = core.TelegramClient(str(core.TELEGRAM_SESSION), core.TELEGRAM_API_ID, core.TELEGRAM_API_HASH)
    out: list[dict[str, Any]] = []
    cutoff = now - timedelta(hours=TELEGRAM_HOURS)
    seen_text: set[str] = set()
    try:
        await client.connect()
        if not await client.is_user_authorized():
            debug["errors"].append("telegram_session_unauthorized")
            return []
        dialogs = []
        async for dialog in client.iter_dialogs():
            if getattr(dialog, "is_group", False):
                dialogs.append(dialog)
        debug["telegram_groups"] = len(dialogs)

        for dialog in dialogs:
            group = dialog.name or getattr(dialog.entity, "username", "") or str(dialog.id)
            try:
                async for msg in client.iter_messages(dialog.entity, limit=PER_GROUP_LIMIT):
                    dt = getattr(msg, "date", None)
                    if not dt:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        break
                    text = str(getattr(msg, "message", "") or "").strip()
                    if not text:
                        continue
                    debug["telegram_messages"] += 1
                    key = hashlib.sha256(_norm(text).encode("utf-8", "ignore")).hexdigest()
                    if key in seen_text:
                        debug["rejects"]["duplicate_text"] += 1
                        continue
                    seen_text.add(key)
                    try:
                        await msg.get_sender()
                    except Exception:
                        pass
                    author = core.tg_sender(msg)
                    if BOT_AUTHOR_RE.search(str(author or "")):
                        debug["rejects"]["bot_author"] += 1
                        continue
                    signal, reason = classify(text)
                    if signal is None:
                        debug["rejects"][reason] += 1
                        continue
                    lead = {
                        "source": "Telegram",
                        "platform": "Telegram",
                        "group": group,
                        "author": author,
                        "text": text,
                        "url": core.tg_link(dialog.entity, getattr(msg, "id", 0)),
                        "message_time": dt.isoformat(),
                        "radar_version": VERSION,
                        **signal,
                    }
                    debug["accepted_classes"][signal["lead_class"]] += 1
                    debug["project_types"].update(signal["project_types"])
                    debug["languages"][signal["language"]] += 1
                    if _save_new(db_client, lead, now):
                        out.append(lead)
            except Exception as exc:
                debug["errors"].append(f"telegram_group:{group}:{type(exc).__name__}")
            await asyncio.sleep(0.10)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return out


def _bing_rss(query: str) -> list[dict[str, Any]]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NorthlabSalesRadar/1.0)"}, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:10]:
            link = item.findtext("link") or ""
            if not link:
                continue
            out.append({
                "source": "Bing RSS",
                "platform": "Web",
                "title": item.findtext("title") or "",
                "text": item.findtext("description") or "",
                "url": link,
                "published": item.findtext("pubDate") or "",
                "author": "",
            })
        return out
    except Exception:
        return []


def scan_web(db_client, now: datetime, debug: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in WEB_QUERIES[:max(1, WEB_QUERY_LIMIT)]:
        rows = _bing_rss(query)
        debug["web_raw"] += len(rows)
        for row in rows:
            key = str(row.get("url") or "")
            if key in seen:
                continue
            seen.add(key)
            blob = f"{row.get('title','')} {row.get('text','')}"
            signal, reason = classify(blob)
            if signal is None:
                debug["web_rejects"][reason] += 1
                continue
            lead = {**row, **signal, "radar_version": VERSION}
            debug["web_accepted"] += 1
            debug["accepted_classes"][signal["lead_class"]] += 1
            debug["project_types"].update(signal["project_types"])
            debug["languages"][signal["language"]] += 1
            if _save_new(db_client, lead, now):
                out.append(lead)
    return out


def _serial(debug: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: v for k, v in debug.items() if not isinstance(v, Counter)},
        "rejects": dict(debug["rejects"]),
        "web_rejects": dict(debug["web_rejects"]),
        "accepted_classes": dict(debug["accepted_classes"]),
        "project_types": dict(debug["project_types"]),
        "languages": dict(debug["languages"]),
    }


def main() -> None:
    now = datetime.now(timezone.utc)
    debug: dict[str, Any] = {
        "version": VERSION,
        "telegram_groups": 0,
        "telegram_messages": 0,
        "web_raw": 0,
        "web_accepted": 0,
        "rejects": Counter(),
        "web_rejects": Counter(),
        "accepted_classes": Counter(),
        "project_types": Counter(),
        "languages": Counter(),
        "errors": [],
    }
    db_client = core.db()

    telegram_new = asyncio.run(scan_telegram(db_client, now, debug))
    web_new = scan_web(db_client, now, debug)
    new_leads = telegram_new + web_new
    new_leads.sort(
        key=lambda x: (
            x.get("lead_class") == "HOT PROJECT",
            x.get("lead_class") == "PARTNER",
            int(x.get("intent_score") or 0),
        ),
        reverse=True,
    )

    alerts = 0
    for lead in new_leads:
        if alerts >= MAX_ALERTS:
            break
        if lead.get("lead_class") == "WATCH":
            continue
        _notify(lead, "NEW")
        _mark_notified(db_client, lead, now)
        alerts += 1

    data = _serial(debug)
    data.update({
        "started_at": now.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "new_leads": len(new_leads),
        "alerts": alerts,
    })
    db_client.collection(SCAN_COLLECTION).document(now.strftime("%Y%m%dT%H%M%SZ")).set(data)

    rejects = ", ".join(f"{k}:{v}" for k, v in debug["rejects"].most_common(8)) or "-"
    web_rejects = ", ".join(f"{k}:{v}" for k, v in debug["web_rejects"].most_common(8)) or "-"
    classes = ", ".join(f"{k}:{v}" for k, v in debug["accepted_classes"].most_common()) or "-"
    types = ", ".join(f"{k}:{v}" for k, v in debug["project_types"].most_common()) or "-"
    langs = ", ".join(f"{k}:{v}" for k, v in debug["languages"].most_common()) or "-"
    core.telegram(
        (
            "🧪 NORTHLAB SALES RADAR DEBUG | SON TARAMA\n\n"
            f"Telegram grup: {debug['telegram_groups']}\n"
            f"Telegram mesaj: {debug['telegram_messages']}\n"
            f"Yeni fırsat: {len(new_leads)} | Bildirim: {alerts}\n"
            f"Sınıflar: {classes}\n"
            f"İş tipleri: {types}\n"
            f"Diller: {langs}\n"
            f"Telegram eleme: {rejects}\n"
            f"Web ham: {debug['web_raw']} | Web kabul: {debug['web_accepted']}\n"
            f"Web eleme: {web_rejects}\n"
            f"Gerçek hata: {len(debug['errors'])}"
        )[:3900]
    )
    print("NORTHLAB_SALES_DEBUG", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
