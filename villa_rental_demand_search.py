"""Read-only search for 3+1 / 4+1 villa rental demand in joined Telegram sources."""
import asyncio, json, os, re
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.types import PeerChannel

VILLA=re.compile(r"\b(?:villa|villas|villa\s+house|vila|вилл\w*|вилла|виллу|виллы|m[üu]stakil\s+ev|villa)\b",re.I)
LAYOUT=re.compile(r"(?<!\d)(3|4)\s*[+＋]\s*1(?!\d)",re.I)
DEMAND=re.compile(r"(?:ar[ıi]yorum|kiralamak\s*istiyorum|ihtiyac\w*|looking\s+for|want\s+to\s+rent|need\s+(?:a|an)?\s*|seeking|ищу|сниму|хочу\s+снять|нужн\w*|подбира\w*)",re.I)
RENT=re.compile(r"(?:kiral\w*|rent|rental|lease|аренд\w*|снять|сниму|долгосроч\w*|посуточ\w*)",re.I)
SUPPLY=re.compile(r"(?:kiral[ıi]k\s+(?:villa|m[üu]stakil)|for\s+rent|available\s+for\s+rent|сда(?:м|ю|ется|ётся)|аренда\s+вилл\w*)",re.I)
SALE=re.compile(r"(?:sat[ıi]l[ıi]k|for\s+sale|продаю|продам|прода[её]тся)",re.I)
PRICE=re.compile(r"(?:[£€$]\s*\d[\d\s,.]*|\d[\d\s,.]*\s*(?:gbp|eur|usd|sterlin|pounds?|фунт\w*))",re.I)

def classify(text):
    t=str(text or "")
    m=LAYOUT.search(t)
    if not m or not VILLA.search(t):
        return None
    if SALE.search(t):
        return None
    if not DEMAND.search(t):
        return None
    if SUPPLY.search(t) and not re.search(r"(?:ar[ıi]yorum|looking\s+for|ищу|сниму|хочу\s+снять)",t,re.I):
        return None
    if not RENT.search(t):
        # In rental-focused wanted language, Russian "сниму" and Turkish
        # "kiralamak istiyorum" already imply rent; DEMAND handles those.
        if not re.search(r"(?:kiralamak\s*istiyorum|сниму|хочу\s+снять|want\s+to\s+rent)",t,re.I):
            return None
    return f"{m.group(1)}+1"

def link_for(entity,msg):
    u=str(getattr(entity,"username","") or "").strip()
    if u:return f"https://t.me/{u}/{msg.id}"
    if isinstance(getattr(msg,"peer_id",None),PeerChannel):
        cid=int(getattr(entity,"id",0) or 0)
        if cid:return f"https://t.me/c/{cid}/{msg.id}"
    return ""

async def scan():
    client=TelegramClient(os.getenv("TELEGRAM_SESSION_PATH","telegram_radar_session/radar_session.session"),int(os.environ["TELEGRAM_API_ID"]),os.environ["TELEGRAM_API_HASH"])
    cutoff=datetime.now(timezone.utc)-timedelta(days=30)
    stats={"groups":0,"messages":0,"matches":0,"errors":0,"demands":[]}
    seen=set()
    try:
        await client.connect()
        if not await client.is_user_authorized():raise RuntimeError("Telegram session not authorized")
        async for dialog in client.iter_dialogs():
            if not (dialog.is_group or dialog.is_channel):continue
            stats["groups"]+=1
            try:
                async for msg in client.iter_messages(dialog.entity,limit=500):
                    if not msg.date:continue
                    dt=msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                    if dt<cutoff:break
                    stats["messages"]+=1
                    text=str(msg.message or "").strip()
                    kind=classify(text)
                    if not kind:continue
                    url=link_for(dialog.entity,msg)
                    if not url or url in seen:continue
                    seen.add(url)
                    sender=""
                    try:
                        s=await msg.get_sender()
                        sender="@"+s.username if getattr(s,"username",None) else str(getattr(s,"first_name","") or "")
                    except Exception:pass
                    stats["demands"].append({"kind":kind,"date":dt.isoformat(),"group":dialog.name,"author":sender,"url":url,"price_mentions":PRICE.findall(text)[:3],"text":text[:1400]})
            except Exception as exc:
                stats["errors"]+=1
                print("VILLA_RENTAL_GROUP_ERROR",type(exc).__name__,str(exc)[:120])
    finally:
        await client.disconnect()
    stats["demands"].sort(key=lambda x:x["date"],reverse=True)
    stats["matches"]=len(stats["demands"])
    public=[x for x in stats["demands"] if re.fullmatch(r"https://t\.me/[A-Za-z0-9_]+/\d+",x["url"])]
    print("VILLA_RENTAL_DEMAND_RESULTS",json.dumps({"status":"completed","groups":stats["groups"],"messages":stats["messages"],"matches":stats["matches"],"three_bed":sum(x["kind"]=="3+1" for x in stats["demands"]),"four_bed":sum(x["kind"]=="4+1" for x in stats["demands"]),"errors":stats["errors"],"public_demands":public[:40]},ensure_ascii=False))
    return stats

if __name__=="__main__":asyncio.run(scan())
