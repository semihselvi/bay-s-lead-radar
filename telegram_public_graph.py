from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,64}$")
_TME_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,64})",
    re.I,
)
_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{4,64})\b")
_RESERVED = {
    "addlist", "addstickers", "apps", "blog", "c", "contact", "faq", "iv",
    "joinchat", "login", "proxy", "setlanguage", "share", "socks", "web",
}


def clean_username(value: str) -> str:
    raw = str(value or "").strip()
    raw = raw.removeprefix("@")
    if not _USERNAME_RE.fullmatch(raw):
        return ""
    if raw.casefold() in _RESERVED:
        return ""
    return raw


def extract_public_usernames(text: str) -> set[str]:
    raw = str(text or "")
    out: set[str] = set()
    for match in _TME_RE.finditer(raw):
        username = clean_username(match.group(1))
        if username:
            out.add(username)
    for match in _MENTION_RE.finditer(raw):
        username = clean_username(match.group(1))
        if username:
            out.add(username)
    return out


def _message_id_from_post(value: str, username: str) -> int:
    raw = str(value or "").strip()
    if "/" not in raw:
        return 0
    channel, msg_id = raw.rsplit("/", 1)
    if clean_username(channel).casefold() != clean_username(username).casefold():
        return 0
    try:
        return int(msg_id)
    except (TypeError, ValueError):
        return 0


def parse_public_preview(html: str, username: str) -> dict[str, Any]:
    username = clean_username(username)
    if not username:
        return {"username": "", "title": "", "messages": [], "references": []}

    soup = BeautifulSoup(str(html or ""), "html.parser")
    title_node = soup.select_one(".tgme_channel_info_header_title")
    title = title_node.get_text(" ", strip=True) if title_node else username

    all_refs: set[str] = set()
    messages: list[dict[str, Any]] = []

    for wrap in soup.select(".tgme_widget_message_wrap"):
        node = wrap.select_one(".tgme_widget_message[data-post]") or wrap.select_one("[data-post]")
        if node is None:
            continue
        msg_id = _message_id_from_post(node.get("data-post", ""), username)
        if not msg_id:
            continue

        text_node = wrap.select_one(".tgme_widget_message_text")
        text = text_node.get_text(" ", strip=True) if text_node else ""

        time_node = wrap.select_one("time[datetime]")
        dt = str(time_node.get("datetime", "") or "") if time_node else ""

        author = ""
        author_node = wrap.select_one(".tgme_widget_message_author")
        if author_node:
            href = str(author_node.get("href", "") or "")
            author_refs = extract_public_usernames(href)
            if author_refs:
                author = "@" + sorted(author_refs)[0]
            else:
                author = author_node.get_text(" ", strip=True)

        refs = set(extract_public_usernames(text))
        for link in wrap.select("a[href]"):
            classes = {str(x) for x in (link.get("class") or [])}
            if "tgme_widget_message_author" in classes:
                continue
            href = str(link.get("href", "") or "")
            refs |= extract_public_usernames(href)

        refs = {x for x in refs if x.casefold() != username.casefold()}
        all_refs |= refs

        messages.append(
            {
                "message_id": msg_id,
                "text": text,
                "datetime": dt,
                "author": author,
                "url": f"https://t.me/{username}/{msg_id}",
                "references": sorted(refs),
            }
        )

    return {
        "username": username,
        "title": title or username,
        "messages": messages,
        "references": sorted(all_refs),
    }


def fetch_public_preview(username: str, timeout: int = 18) -> dict[str, Any]:
    username = clean_username(username)
    if not username:
        raise ValueError("invalid telegram username")

    response = requests.get(
        f"https://t.me/s/{username}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; PrimeKibrisLeadRadar/6.20; "
                "+https://primekibris.com)"
            )
        },
        timeout=timeout,
        allow_redirects=True,
    )
    if response.status_code == 404:
        raise FileNotFoundError(username)
    response.raise_for_status()
    return parse_public_preview(response.text, username)


def parse_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
