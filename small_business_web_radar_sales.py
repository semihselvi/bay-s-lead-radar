from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse, urlunparse

import requests

import small_business_web_radar as base
import small_business_web_radar_reviewed as reviewed


VERSION = "1.4-hosted-path-safe-sales-fit"

# reviewed import has already patched base.inspect_site with the pre-alert sales
# quality gate. Keep that function as the normal path for reachable websites.
_reviewed_inspect = base.inspect_site
_original_root_url = base._root_url

HOSTED_PATH_SITES = (
    "wixsite.com",
    "weebly.com",
    "webnode.page",
    "webnode.com",
)


def root_url(url: str) -> str:
    """Keep the site slug for hosted builders where the hostname alone is 404.

    Example: onayandonay.wixsite.com/home is a valid live website while
    onayandonay.wixsite.com/ is not. Stripping /home creates a false broken-site
    lead, so preserve the first path segment for these builders.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme in {"http", "https"} and any(host.endswith(x) for x in HOSTED_PATH_SITES):
            parts = [p for p in parsed.path.split("/") if p]
            path = f"/{parts[0]}" if parts else "/"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{parsed.hostname}{port}{path}"
    except Exception:
        pass
    return _original_root_url(url)


def _alternate_scheme(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return urlunparse(parsed._replace(scheme="http"))
    if parsed.scheme == "http":
        return urlunparse(parsed._replace(scheme="https"))
    return ""


def _broken_lead(discovery, reason: str, score: int = 95) -> dict | None:
    # A dead website is only actionable when the verified Google/Places business
    # record gives us a direct public contact channel.
    phone = str(getattr(discovery, "phone", "") or "").strip()
    if not phone:
        return None
    return {
        "business_name": str(getattr(discovery, "title", ""))[:120],
        "website": str(getattr(discovery, "url", "")),
        "domain": base._host(str(getattr(discovery, "url", ""))),
        "city": str(getattr(discovery, "city", "")),
        "category": str(getattr(discovery, "category", "")),
        "address": str(getattr(discovery, "address", ""))[:300],
        "place_type": str(getattr(discovery, "place_type", ""))[:120],
        "rating": float(getattr(discovery, "rating", 0.0) or 0.0),
        "rating_count": int(getattr(discovery, "rating_count", 0) or 0),
        "redesign_score": score,
        "classification": "HOT",
        "reasons": [reason],
        "contacts": {
            "email": "",
            "phone": phone[:120],
            "whatsapp": "",
            "instagram": "",
            "facebook": "",
            "contact_page": "",
        },
        "response_seconds": 0,
        "radar_version": VERSION,
    }


def inspect_site(discovery):
    url = str(getattr(discovery, "url", "") or "")
    if not url or reviewed.blocked_url(url):
        return None

    headers = {"User-Agent": base.UA, "Accept-Language": "en,tr;q=0.9"}

    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=base.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code in {404, 410}:
            lead = _broken_lead(discovery, f"web sitesi açılmıyor (HTTP {r.status_code})", 98)
            if lead:
                print(
                    "SMALL_BIZ_BROKEN_SITE "
                    f"business={lead['business_name']!r} url={url} status={r.status_code}"
                )
            return lead
        # 401/403/429/5xx may be anti-bot/CDN behavior. Do not call those a
        # broken customer website from GitHub alone; let the reviewed layer decide.
        return _reviewed_inspect(discovery)

    except requests.exceptions.SSLError:
        alt = _alternate_scheme(url)
        if alt:
            try:
                r2 = requests.get(
                    alt,
                    headers=headers,
                    timeout=base.REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if r2.status_code == 200:
                    return _reviewed_inspect(replace(discovery, url=alt))
            except requests.RequestException:
                pass
        lead = _broken_lead(discovery, "SSL/sertifika hatası nedeniyle site güvenli açılamıyor", 96)
        if lead:
            print(f"SMALL_BIZ_BROKEN_SITE business={lead['business_name']!r} url={url} error=SSLError")
        return lead

    except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
        alt = _alternate_scheme(url)
        if alt:
            try:
                r2 = requests.get(
                    alt,
                    headers=headers,
                    timeout=base.REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if r2.status_code == 200:
                    return _reviewed_inspect(replace(discovery, url=alt))
                if r2.status_code in {404, 410}:
                    return _broken_lead(discovery, f"web sitesi açılmıyor (HTTP {r2.status_code})", 98)
            except requests.RequestException:
                pass
        lead = _broken_lead(discovery, "web sitesi bağlantı hatası veriyor / erişilemiyor", 97)
        if lead:
            print(f"SMALL_BIZ_BROKEN_SITE business={lead['business_name']!r} url={url} error=ConnectionError")
        return lead

    except requests.exceptions.ReadTimeout:
        # A timeout can be transient. It is a useful redesign signal only when it
        # repeatedly occurs, so keep it out of Telegram for now.
        print(f"SMALL_BIZ_REJECT reason=single_timeout business={getattr(discovery, 'title', '')!r} url={url}")
        return None


base.VERSION = VERSION
base._root_url = root_url
base.inspect_site = inspect_site


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
