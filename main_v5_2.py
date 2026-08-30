from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import main as core
import main_v5_1 as gate


VERSION = "5.2-candidate-first"
gate.VERSION = VERSION
gate.v5.VERSION = VERSION

# V5.1.1 filtered only messages that the legacy Telegram scorer had already
# labelled HOT/WARM. That could hide real buyers before the strict buyer gate
# ever saw them. V5.2 scans every recent message in relevant Cyprus groups and
# applies the strict property/self-buyer gate directly.

NORTH_GROUP_RE = re.compile(
    r"(?:north\s*cyprus|northern\s*cyprus|kuzey\s*k[ıi]br[ıi]s|"
    r"северн(?:ый|ого|ом)?\s+кипр|iskele|İskele|long\s*beach|girne|kyrenia|"
    r"famagusta|gazimağusa|gazimagusa|esentepe|tatl[ıi]su|bafra|yenibo[gğ]azi[cç]i)",
    re.I,
)

CYPRUS_GROUP_RE = re.compile(
    r"(?:cyprus|кипр|k[ıi]br[ıi]s|kibris|zypern|cypr)",
    re.I,
)

SOUTH_ONLY_RE = re.compile(
    r"\b(?:limassol|larnaca|paphos|ayia\s+napa|protaras|лимассол|ларнак[аи]|пафос)\b",
    re.I,
)

# Broaden public-web discovery while keeping the final buyer gate strict.
gate.v5.EXA_QUERIES = list(gate.v5.EXA_QUERIES) + [
    ("North Cyprus forum I want to buy apartment villa budget", None),
    ("North Cyprus expat looking for property to buy budget", None),
    ("Северный Кипр хочу купить квартиру бюджет форум", None),
    ("Nordzypern suche Wohnung kaufen Forum", None),
    ("Cypr Północny chcę kupić mieszkanie forum", None),
]


def _group_scope(group: str) -> tuple[bool, bool]:
    direct_north = bool(NORTH_GROUP_RE.search(group or ""))
    generic_cyprus = bool(CYPRUS_GROUP_RE.search(group or ""))
    return direct_north, generic_cyprus


def _base_candidate(group: str, entity: Any, msg: Any, started: datetime) -> dict[str, Any]:
    text = str(getattr(msg, "message", "") or "").strip()
    return {
        "source": "Telegram",
        "source_type": "joined_group_candidate_first",
        "group": group,
        "group_priority": core.tg_priority(group),
        "group_username": getattr(entity, "username", None) or "",
        "message_id": getattr(msg, "id", 0),
        "message_time": (
            getattr(msg, "date", None).isoformat(timespec="seconds")
            if getattr(msg, "date", None)
            else ""
        ),
        "author": "",
        "message": text,
        "url": core.tg_link(entity, getattr(msg, "id", 0)),
        "market": "north_cyprus",
        "budget_detected": bool(gate.v5.BUDGET_RE.search(text)),
        "buyer_matches": [],
        "context_matches": [],
        "weak_matches": [],
        "seller_matches": [],
        "rent_matches": [],
        "telegram_score": 40,
        "classification": "REVIEW",
        "negative_status": False,
        "found_at": started.isoformat(),
    }


async def candidate_first_telegram_scan(db_client, started):
    if not core.TELEGRAM_API_ID or not core.TELEGRAM_API_HASH:
        print("V5.2 TELEGRAM: API_ID/API_HASH yok — atlandı.")
        return {
            "status": "skipped",
            "groups": 0,
            "messages": 0,
            "hot_warm": 0,
            "errors": 0,
            "new_leads": [],
        }

    session = core.TELEGRAM_SESSION
    if not session.exists():
        print("V5.2 TELEGRAM: session dosyası yok — atlandı.")
        return {
            "status": "skipped_no_session",
            "groups": 0,
            "messages": 0,
            "hot_warm": 0,
            "errors": 0,
            "new_leads": [],
        }

    client = core.TelegramClient(str(session), core.TELEGRAM_API_ID, core.TELEGRAM_API_HASH)

    relevant_groups = 0
    total_groups = 0
    total_messages = 0
    buyer_signal_messages = 0
    accepted: list[dict[str, Any]] = []
    errors = 0
    already_notified = 0

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("V5.2 TELEGRAM: session yetkili değil — atlandı.")
            return {
                "status": "skipped_unauthorized",
                "groups": 0,
                "messages": 0,
                "hot_warm": 0,
                "errors": 0,
                "new_leads": [],
            }

        me = await client.get_me()
        print(
            "V5.2 TELEGRAM: giriş ok — "
            f"{getattr(me, 'username', None) or getattr(me, 'first_name', '')}"
        )

        dialogs = []
        async for dialog in client.iter_dialogs():
            if getattr(dialog, "is_group", False):
                dialogs.append(dialog)
        total_groups = len(dialogs)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=core.TELEGRAM_HOURS)

        # Prioritize known North Cyprus groups, then generic Cyprus groups.
        dialogs.sort(
            key=lambda d: (
                0 if _group_scope(d.name or "")[0] else 1,
                0 if _group_scope(d.name or "")[1] else 1,
                core.tg_norm(d.name or ""),
            )
        )

        for dialog in dialogs:
            entity = dialog.entity
            group = dialog.name or getattr(entity, "username", None) or str(dialog.id)
            direct_north, generic_cyprus = _group_scope(group)
            if not direct_north and not generic_cyprus:
                continue

            relevant_groups += 1
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

                    total_messages += 1

                    # Generic Cyprus groups must explicitly mention North Cyprus or
                    # a North Cyprus locality in the message itself.
                    explicit_north = bool(gate.v5.NORTH_RE.search(text))
                    if not direct_north and not explicit_north:
                        continue

                    # A North-Cyprus group can contain questions about the Republic
                    # of Cyprus. Reject clearly south-only property requests unless
                    # the same message explicitly says North Cyprus.
                    if SOUTH_ONLY_RE.search(text) and not explicit_north:
                        continue

                    has_property = bool(gate.TG_PROPERTY_RE.search(text))
                    has_buyer_voice = bool(
                        gate.TG_SELF_BUY_RE.search(text)
                        or gate.TG_CONSIDERATION_RE.search(text)
                    )
                    if not has_property or not has_buyer_voice:
                        continue

                    buyer_signal_messages += 1
                    candidate = _base_candidate(group, entity, msg, started)
                    refined = gate.refine_telegram_property_buyer(candidate)
                    if refined is None:
                        continue

                    stable_id = f"telegram|{dialog.id}|{msg.id}"
                    lead_id = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()
                    ref = db_client.collection(core.COLLECTION).document(lead_id)
                    snap = ref.get()

                    if snap.exists:
                        previous = snap.to_dict() or {}
                        if previous.get("v5_notified_at"):
                            already_notified += 1
                            continue

                    try:
                        await msg.get_sender()
                    except Exception:
                        pass

                    refined["lead_id"] = lead_id
                    refined["author"] = core.tg_sender(msg)
                    refined["found_at"] = started.isoformat()
                    refined["radar_version"] = VERSION
                    ref.set(refined, merge=True)
                    accepted.append(refined)

            except core.FloodWaitError as exc:
                errors += 1
                print(f"V5.2 TELEGRAM FLOOD_WAIT {group}: {exc.seconds}s")
            except Exception as exc:
                errors += 1
                print(f"V5.2 TELEGRAM GROUP ERROR {group}: {type(exc).__name__}: {exc}")

            await asyncio.sleep(0.25)

        print(
            "V5.2 TELEGRAM CANDIDATE-FIRST: "
            f"groups={relevant_groups}/{total_groups} | messages={total_messages} | "
            f"buyer_signals={buyer_signal_messages} | accepted={len(accepted)} | "
            f"already_notified={already_notified} | errors={errors}"
        )

        return {
            "status": "completed",
            "groups": relevant_groups,
            "messages": total_messages,
            "hot_warm": len(accepted),
            "errors": errors,
            "new_leads": accepted,
            "candidate_first_buyer_signals": buyer_signal_messages,
            "candidate_first_total_groups": total_groups,
            "candidate_first_already_notified": already_notified,
        }

    except Exception as exc:
        print(f"V5.2 TELEGRAM ERROR {type(exc).__name__}: {exc}")
        return {
            "status": "error",
            "groups": relevant_groups,
            "messages": total_messages,
            "hot_warm": 0,
            "errors": errors + 1,
            "new_leads": [],
        }
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# Replace the legacy score-first traversal with candidate-first traversal.
core.telegram_buyer_scan = candidate_first_telegram_scan


def main() -> None:
    gate.v5.main()


if __name__ == "__main__":
    main()
