"""Read-only scan for Grand Sapphire 2+1 SALE offers across joined Telegram groups/channels."""
import asyncio, json, os, re
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.types import PeerChannel

PROJECT=re.compile(r"(?:grand\s*sapphire|гранд\s*сапфир|сапфир)",re.I)
LAYOUT=re.compile(r"(?<!\d)2\s*[+＋]\s*1(?!\d)",re.I)
SALE=re.compile(r"(?:sat[ıi]l[ıi]k|sat[ıi]yorum|sat[ıi]l[ıi]yor|for\s+sale|selling|sale|продаю|продам|прода[её]тся|продажа)",re.I)
BUY_DEMAND=re.compile(r"(?:куплю|ищу\b.{0,80}\b(?:2\s*[+＋]\s*1|квартир)|looking\s+to\s+buy|want\s+to\s+buy|buying|sat[ıi]n\s+al(?:mak|acağım)|ar[ıi]yorum)",re.I|re.S)
PRICE=re.compile(r"(?:[£€$]\s*\d[\d\s,.]*|\d[\d\s,.]*\s*(?:gbp|eur|usd|sterlin|pounds?|фунт\w*))",re.I)
FLOOR=re.compile(r"(?:\b(?:kat|floor)\s*[:\-]?\s*(\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+floor\b|\b(?:этаж|этаже)\s*[:\-]?\s*(\d{1,2})\b|\b(\d{1,2})\s*(?:этаж|этаже)\b)",re.I)
SEA=re.compile(r"(?:sea\s*view|deniz\s+manzara|вид\s+на\s+море|море)",re.I)
FAM=re.compile(r"(?:famagust\w*|gazima[ğg]usa|ma[ğg]usa|фамагуст\w*)",re.I)

def link_for(entity,msg):
    u=str(getattr(entity,"username","") or "").strip()
    if u:return f"https://t.me/{u}/{msg.id}"
    if isinstance(getattr(msg,"peer_id",None),PeerChannel):
        cid=int(getattr(entity,"id",0) or 0)
        if cid:return f"https://t.me/c/{cid}/{msg.id}"
    return ""

def classify(text):
    t=str(text or "").strip()
    if not (PROJECT.search(t) and LAYOUT.search(t)):
        return False
    # We want properties being offered for sale, not buyers asking to buy.
    if BUY_DEMAND.search(t) and not SALE.search(t):
        return False
    return bool(SALE.search(t) or PRICE.search(t))

async def scan():
    client=TelegramClient(
        os.getenv("TELEGRAM_SESSION_PATH","telegram_radar_session/radar_session.session"),
        int(os.environ["TELEGRAM_API_ID"]),os.environ["TELEGRAM_API_HASH"])
    cutoff=datetime.now(timezone.utc)-timedelta(days=int(os.getenv("GS_SALE_DAYS","30")))
    stats={"groups":0,"messages":0,"matches":0,"errors":0,"offers":[]}
    seen=set()
    try:
        await client.connect()
        if not await client.is_user_authorized():raise RuntimeError("Telegram session not authorized")
        async for dialog in client.iter_dialogs():
            if not (dialog.is_group or dialog.is_channel):continue
            stats["groups"]+=1
            try:
                async for msg in client.iter_messages(dialog.entity,limit=1000):
                    if not msg.date:continue
                    dt=msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                    if dt<cutoff:break
                    stats["messages"]+=1
                    text=str(msg.message or "").strip()
                    if not classify(text):continue
                    url=link_for(dialog.entity,msg)
                    key=url or f"{dialog.id}:{msg.id}"
                    if key in seen:continue
                    seen.add(key)
                    sender=""
                    try:
                        s=await msg.get_sender()
                        sender="@"+s.username if getattr(s,"username",None) else str(getattr(s,"first_name","") or "")
                    except Exception:pass
                    floor=None
                    fm=FLOOR.search(text)
                    if fm:
                        floor=next((g for g in fm.groups() if g),None)
                    stats["offers"].append({
                        "date":dt.isoformat(),"group":dialog.name,"author":sender,"url":url,
                        "price_mentions":PRICE.findall(text)[:5],"floor":floor,
                        "sea_view":bool(SEA.search(text)),"famagusta":bool(FAM.search(text)),
                        "text":text[:1800]})
            except Exception as exc:
                stats["errors"]+=1
                print("GS_GROUP_ERROR",type(exc).__name__,str(exc)[:160])
    finally:
        await client.disconnect()
    stats["offers"].sort(key=lambda x:x["date"],reverse=True)
    stats["matches"]=len(stats["offers"])
    print("GRAND_SAPPHIRE_2P1_SALE_RESULTS",json.dumps(stats,ensure_ascii=False))
    return stats

if __name__=="__main__":asyncio.run(scan())
