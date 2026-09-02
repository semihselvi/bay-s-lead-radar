from __future__ import annotations

from urllib.parse import urlparse

import small_business_web_radar as base


VERSION = "1.2-prealert-sales-fit"

# Directory/booking platforms are not an owned business website. They can be
# useful operationally, but they are not the redesign-sale target Semih wants.
PLATFORM_HOST_TOKENS = (
    "salonbir.com",
    "fresha.com",
    "treatwell.",
    "booksy.",
    "vagaro.com",
    "mindbodyonline.com",
    "setmore.com",
)

# A pile of minor SEO warnings alone is not enough reason to pitch a full new
# website. We require at least one visible/operational redesign pain for HOT,
# and at least two for WARM.
MAJOR_PAIN_PREFIXES = (
    "HTTPS yok",
    "mobil viewport yok",
    "eski HTML/JS izleri",
    "site yapımda/coming soon",
    "telif yılı eski",
    "sayfa başlığı zayıf",
    "telefon/WhatsApp/e-posta CTA görünmüyor",
    "ana sayfa çok temel",
    "yavaş yanıt",
)

_original_blocked_url = base.blocked_url
_original_inspect_site = base.inspect_site


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def blocked_url(url: str) -> bool:
    host = _host(url)
    return _original_blocked_url(url) or any(token in host for token in PLATFORM_HOST_TOKENS)


def major_pain_count(reasons: list[str]) -> int:
    return sum(
        1
        for reason in reasons or []
        if any(str(reason).startswith(prefix) for prefix in MAJOR_PAIN_PREFIXES)
    )


def sales_worthy(lead: dict) -> bool:
    host = _host(str(lead.get("website") or ""))
    if any(token in host for token in PLATFORM_HOST_TOKENS):
        return False
    score = int(lead.get("redesign_score") or 0)
    major = major_pain_count(list(lead.get("reasons") or []))
    if score >= 60:
        return major >= 1
    return major >= 2


def inspect_site(discovery):
    lead = _original_inspect_site(discovery)
    if lead is None:
        return None
    if not sales_worthy(lead):
        print(
            "SMALL_BIZ_REJECT reason=weak_sales_case "
            f"business={lead.get('business_name')!r} url={lead.get('website')} "
            f"score={lead.get('redesign_score')} reasons={lead.get('reasons')}"
        )
        return None
    lead["radar_version"] = VERSION
    return lead


# Patch the existing single radar rather than creating a second discovery stack.
base.VERSION = VERSION
base.blocked_url = blocked_url
base.inspect_site = inspect_site


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
