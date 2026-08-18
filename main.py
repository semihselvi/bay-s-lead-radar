import asyncio, csv, html, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

BASE=Path(__file__).resolve().parent
OUT=BASE/'output'
OUT.mkdir(exist_ok=True)
load_dotenv(BASE/'.env')

API_ID=int(os.getenv('TELEGRAM_API_ID','0') or '0')
API_HASH=os.getenv('TELEGRAM_API_HASH','').strip()
PHONE=os.getenv('TELEGRAM_PHONE','').strip()
HOURS=int(os.getenv('RADAR_HOURS','24'))
LIMIT=int(os.getenv('RADAR_PER_CHAT_LIMIT','700'))
SESSION=str(BASE/'radar_session')

BUY=[
r'\balmak istiyorum\b',r'\bsatın almak istiyorum\b',r'\bev arıyorum\b',r'\bdaire arıyorum\b',
r'\bvilla arıyorum\b',r'\barsa arıyorum\b',r'\byatırım için\b',r'\bbütçem\b',r'\balıcıyım\b',
r'\blooking to buy\b',r'\bwant to buy\b',r'\bplanning to buy\b',r'\bready to buy\b',
r'\bcash buyer\b',r'\bbuyer looking\b',r'\bproperty wanted\b',r'\bhouse wanted\b',
r'\bapartment wanted\b',r'\bvilla wanted\b',r'\bseeking to buy\b',r'\binterested in buying\b',
r'\bwtb\b',r'\blooking for (?:an? )?(?:apartment|flat|house|villa|property|land)\b',
r'\bхочу купить\b',r'\bхотим купить\b',r'\bкуплю\b',r'\bищу купить\b',r'\bищу квартиру\b',
r'\bищу апартамент',r'\bищу виллу\b',r'\bищу дом\b',r'\bищу недвижимость\b',
r'\bготов купить\b',r'\bготовы купить\b',r'\bпланирую купить\b',r'\bдля инвестиц',r'\bбюджет\b',r'\bсрочно нужна квартира\b',r'\bнужна квартира\b',r'\bкуплю квартиру\b',r'\bкуплю дом\b',r'\bкуплю недвижимость\b',r'\bищу жилье\b',r'\bищу жильё\b',r'\bкакую квартиру купить\b',r'\bгде купить квартиру\b',r'\bacil(?:en)? .*?daire\b',r'\bdaire lazım\b',r'\bkonut arıyorum\b'
]
WEAK=[r'\bönerir misiniz\b',r'\bhangi bölge\b',r'\bmortgage\b',r'\bwhere should i buy\b',
r'\bwhich area\b',r'\binvestment property\b',r'\bгде купить\b',r'\bкакой район\b',r'\bипотек']
SELL=[r'\bsatılık\b',r'\bsatışta\b',r'\bportföy\b',r'\bkomisyon\b',r'\bkampanya\b',
r'\bfor sale\b',r'\bavailable now\b',r'\bcontact us\b',r'\bagent\b',r'\bagency\b',
r'\bcommission\b',r'\bdeveloper\b',r'\bпродам\b',r'\bпродается\b',r'\bпродаётся\b',
r'\bагент\b',r'\bагентство\b',r'\bкомисси',r'\bзастройщик\b']
RENT=[r'\bkiralık\b',r'\bkiralık arıyorum\b',r'\bfor rent\b',r'\blooking to rent\b',
r'\brental\b',r'\bсниму\b',r'\bаренд',r'\bснять квартиру\b',r'\bснять виллу\b']
BUDGET_RE=re.compile(r'(?:£|€|\$|₺|₽)\s?\d[\d\s.,]*|\b\d[\d\s.,]*\s?(?:gbp|eur|usd|try|tl|руб|млн|million|k)\b',re.I)

MARKETS={
'North Cyprus':['north cyprus','northern cyprus','kuzey kıbrıs','северный кипр','iskele','girne','kyrenia','famagusta','gazimağusa','long beach','esentepe'],
'Turkey':['turkey','türkiye','antalya','alanya','istanbul','izmir','ankara','muratpaşa','lara','konyaaltı','bodrum','fethiye','mersin'],
'Montenegro':['montenegro','черногор','karadağ','budva','kotor','tivat','podgorica'],
'Spain':['spain','испания','ispanya','alicante','valencia','marbella','malaga','barcelona','madrid'],
'Portugal':['portugal','португал','portekiz','lisbon','lisboa','porto','algarve'],
'UAE':['dubai','дубай','uae','abu dhabi','sharjah','emirates'],
'UK':['united kingdom','england','london','manchester','birmingham','британи','лондон'],
'Germany':['germany','deutschland','германи','almanya','berlin','munich','frankfurt','hamburg'],
'Greece':['greece','yunanistan','греци','athens','atina','thessaloniki'],
'Italy':['italy','italia','italya','итал','milan','rome','roma'],
'France':['france','fransa','франц','paris','nice','cannes']
}

def norm(s): return (s or '').casefold()
def matches(text, pats):
    t=norm(text); out=[]
    for p in pats:
        m=re.search(p,t,re.I)
        if m: out.append(m.group(0))
    return out

def market(text, group):
    blob=norm((group or '')+' '+(text or ''))
    scores={k:sum(norm(h) in blob for h in v) for k,v in MARKETS.items()}
    best=max(scores,key=scores.get)
    return best if scores[best] else 'Unknown'

# ---------------- PRIORITY GROUP RADAR ----------------

HIGH_GROUPS = [
    "СЕВЕРНЫЙ КИПР | БАРАХОЛКА",
    "Русские на Северном Кипре",
    "Цезарь резорт",
    "Недвижимость Северный Кипр",
    "Iskele | Long Beach",
    "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
    "Северный Кипр Недвижимость",
    "Гирне | Кирения",
    "Северный Кипр: объявления, работа, недвижимость",
    "Северный Кипр. ЧАТ. БАЗА Недвижимости",
    "Недвижимость Турция и Северный Кипр",
    "Русские в Анталье",
    "Все русские в Турции",
    "Недвижимость Турция",
    "CourtYard Long Beach",
]

MEDIUM_GROUPS = [
    "СЕВЕРНЫЙ КИПР (чат)",
    "Искеле Гирне Фамагуста Лефкоша Северный Кипр чат",
    "АНТАЛИЯ ЧАТ ТУРЦИЯ",
    "АНТАЛИЯ ЧАТ",
    "СТАМБУЛ ЧАТ",
    "Кипр | Чат | Объявления | Барахолка",
    "Кипр Объявления/Барахолка/Недвижимость №1",
    "Северный Кипр | ФОРУМ",
    "Кипр | Чат | Объявления | Барахолка",
]

LOW_GROUPS = [
    "КИПР НОВОСТИ",
    "КИПР FAQ | NEWS",
    "CAESAR PROJECTS NEWS",
    "Гранд Сапфир Резорт",
    "Цезарь резорт",
    "Недвижимость Северный Кипр- Leverage Investments",
    "GP CYPRUS | Северный Кипр | Недвижимость",
]

def group_priority(title):
    t = norm(title)
    if any(norm(x) == t for x in HIGH_GROUPS):
        return "HIGH"
    if any(norm(x) == t for x in MEDIUM_GROUPS):
        return "MEDIUM"
    if any(norm(x) == t for x in LOW_GROUPS):
        return "LOW"
    return "NORMAL"

def buyer_grade(text, group, score, label, buy, budget):
    """Tighten classification: explicit personal purchase intent wins."""
    t = norm(text)
    p = group_priority(group)

    explicit_buy = any(
        x in t
        for x in [
            "куплю квартиру", "куплю дом", "куплю недвижимость",
            "хочу купить", "планирую купить", "готов купить",
            "ищу квартиру для покупки", "купить квартиру",
            "i want to buy", "i'm looking to buy",
            "looking to buy", "planning to buy",
            "ev almak istiyorum", "satın almak istiyorum",
            "ev alacağım", "daire arıyorum", "konut arıyorum",
        ]
    )

    personal_question = any(
        x in t
        for x in [
            "мой бюджет", "бюджет", "подскажите", "где лучше",
            "какой район", "какую квартиру",
            "my budget", "which area", "where should i buy",
            "bütçem", "hangi bölge", "önerir misiniz",
        ]
    )

    rent_only = bool(matches(text, RENT)) and not buy
    seller_only = bool(matches(text, SELL)) and not buy

    if rent_only or seller_only:
        return "REJECT"

    if explicit_buy and budget:
        return "HOT"

    if explicit_buy and p == "HIGH":
        return "HOT"

    if (
        (explicit_buy or personal_question or buy)
        and p in {"HIGH", "MEDIUM"}
        and score >= 45
    ):
        return "WARM"

    if explicit_buy and score >= 55:
        return "WARM"

    return label

def alert_file():
    return OUT / "telegram_alerted_ids.txt"

def already_alerted(key):
    f = alert_file()
    if not f.exists():
        return False
    try:
        return key in {
            x.strip()
            for x in f.read_text(encoding="utf-8").splitlines()
            if x.strip()
        }
    except Exception:
        return False

def mark_alerted(key):
    f = alert_file()
    with f.open("a", encoding="utf-8") as fh:
        fh.write(key + "\n")

def send_telegram_alert(row):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("ALERT_NOT_CONFIGURED")
        return False

    try:
        import requests

        emoji = "🔥" if row["label"] == "HOT" else "🟠"

        message = (
            f"{emoji} BAY-S TELEGRAM BUYER RADAR\n\n"
            f"{row['label']} | {row['score']}/100\n"
            f"Grup: {row['group']}\n"
            f"Pazar: {row['market']}\n"
            f"Öncelik: {group_priority(row['group'])}\n\n"
            f"{row['message'][:900]}\n\n"
            f"👤 {row.get('author') or 'Kullanıcı gizli'}\n"
            f"🕒 {row['message_time']}\n"
        )

        if row.get("link"):
            message += f"\n🔗 {row['link']}"

        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        r.raise_for_status()
        return True

    except Exception as e:
        print("TELEGRAM_ALERT_ERROR:", type(e).__name__, e)
        return False

def calc(text, group):
    buy=matches(text,BUY); weak=matches(text,WEAK); sell=matches(text,SELL); rent=matches(text,RENT)
    budget=bool(BUDGET_RE.search(text or ''))
    s=min(70,30*len(buy))+min(20,8*len(weak))+(12 if budget else 0)-min(70,24*len(sell))-min(70,40*len(rent))
    s=max(0,min(100,s))
    if buy and s<35: s=35
    if rent and not buy: label='REJECT_RENT'
    elif sell and not buy: label='REJECT_SELLER'
    elif s>=60: label='HOT'
    elif s>=35: label='WARM'
    elif s>=15: label='REVIEW'
    else: label='LOW'
    return s,label,buy,weak,sell,rent,budget,market(text,group)

def sender_name(msg):
    s=getattr(msg,'sender',None)
    if not s: return ''
    u=getattr(s,'username',None)
    if u: return '@'+u
    return ((getattr(s,'first_name','') or '')+' '+(getattr(s,'last_name','') or '')).strip()

def msg_link(entity,mid):
    u=getattr(entity,'username',None)
    return f'https://t.me/{u}/{mid}' if u else ''

def write_csv(path, rows):
    fields=['message_time','score','label','market','priority','group','group_username','author','message','link','budget_detected','buyer_matches','weak_matches','seller_matches','rent_matches']
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

async def main():
    if not API_ID or not API_HASH or not PHONE: raise SystemExit('Eksik .env')
    client=TelegramClient(SESSION,API_ID,API_HASH)
    await client.start(phone=PHONE)
    me=await client.get_me()
    print('Giriş:',getattr(me,'username',None) or getattr(me,'first_name','Telegram user'))

    dialogs=[]
    async for d in client.iter_dialogs():
        if getattr(d,'is_group',False):
            dialogs.append(d)

    # Scan buyer-heavy groups first, without excluding other groups.
    dialogs.sort(
        key=lambda d: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NORMAL": 3}.get(
                group_priority(
                    d.name or getattr(d.entity, "username", None) or ""
                ),
                3,
            ),
            norm(d.name or ""),
        )
    )

    print('Üye olunan grup sayısı:',len(dialogs))

    with (OUT/'joined_groups.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['title','username','dialog_id']); w.writeheader()
        for d in dialogs:
            w.writerow({'title':d.name or '','username':getattr(d.entity,'username',None) or '','dialog_id':d.id})

    cutoff=datetime.now(timezone.utc)-timedelta(hours=HOURS)
    rows=[]
    for i,d in enumerate(dialogs,1):
        ent=d.entity; title=d.name or getattr(ent,'username',None) or str(d.id); uname=getattr(ent,'username',None) or ''
        print(f'[{i}/{len(dialogs)}] Taranıyor: {title}')
        try:
            async for msg in client.iter_messages(ent,limit=LIMIT):
                text=getattr(msg,'message',None)
                if not text: continue
                dt=msg.date
                if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                if dt<cutoff: break
                s,label,buy,weak,sell,rent,budget,mkt=calc(text,title)

                # Keep buyer-only logic strict.
                final_label = buyer_grade(
                    text,
                    title,
                    s,
                    label,
                    buy,
                    budget,
                )

                if final_label == "REJECT":
                    continue

                label = final_label

                if label not in {'HOT','WARM','REVIEW'}:
                    continue

                alert_key = f"{ent.id}:{msg.id}"

                rows.append({
                    'message_time':dt.isoformat(timespec='seconds'),'score':s,'label':label,'market':mkt,
                    'priority':group_priority(title),
                    'group':'%s' % title,
                    'group_username':uname,'author':sender_name(msg),'message':text.strip(),
                    'link':msg_link(ent,msg.id),'budget_detected':'yes' if budget else 'no',
                    'buyer_matches':' | '.join(buy),'weak_matches':' | '.join(weak),
                    'seller_matches':' | '.join(sell),'rent_matches':' | '.join(rent)
                })
        except FloodWaitError as e:
            print('  FloodWait',e.seconds,'sn')
        except Exception as e:
            print('  Hata:',type(e).__name__,e)
        await asyncio.sleep(0.5)

    await client.disconnect()
    rows.sort(key=lambda r:int(r['score']),reverse=True)
    hotwarm=[r for r in rows if r['label'] in {'HOT','WARM'}]
    write_csv(OUT/'joined_group_leads_v2.csv',hotwarm)

    # Alert only on new HOT/WARM buyer messages.
    alerts_sent = 0
    for r in hotwarm:
        alert_key = f"{r['group_username'] or r['group']}|{r['message_time']}|{r['message'][:120]}"
        if already_alerted(alert_key):
            continue
        if send_telegram_alert(r):
            mark_alerted(alert_key)
            alerts_sent += 1

    print('Yeni Telegram uyarıları:', alerts_sent)
    write_csv(OUT/'joined_group_candidates_v2.csv',rows)

    report=OUT/'joined_group_report_v2.html'
    cards=[]
    for r in rows[:300]:
        l=f'<a href="{html.escape(r["link"])}" target="_blank">Mesajı aç</a>' if r['link'] else 'Özel grup'
        cards.append(f'<article><b>{r["score"]}/100 · {html.escape(r["label"])} · {html.escape(r["market"])}</b><h3>{html.escape(r["group"])}</h3><small>{html.escape(r["message_time"])} · {html.escape(r["author"] or "author hidden")}</small><p>{html.escape(r["message"])}</p>{l}</article>')
    body=''.join(cards) if cards else '<article>Aday bulunmadı.</article>'
    report.write_text(f'<!doctype html><meta charset="utf-8"><style>body{{font-family:Arial;background:#07111f;color:#eef5ff;max-width:1100px;margin:30px auto;padding:0 16px}}article{{background:#0d1a2b;border:1px solid #1d3552;border-radius:14px;padding:18px;margin:12px 0}}small{{color:#9ab0c7}}p{{white-space:pre-wrap;line-height:1.5}}a{{color:#66baff}}</style><h1>BAY-S TELEGRAM BUYER RADAR v3</h1><p>Son {HOURS} saat · HOT/WARM/REVIEW</p>{body}',encoding='utf-8')

    print()
    print('Tarama tamam.')
    print('HOT/WARM:',len(hotwarm))
    print('REVIEW:',sum(r['label']=='REVIEW' for r in rows))
    print('Tüm adaylar:',len(rows))
    print('Lead CSV:',OUT/'joined_group_leads_v2.csv')
    print('Aday CSV:',OUT/'joined_group_candidates_v2.csv')
    print('HTML rapor:',report)

if __name__=='__main__':
    asyncio.run(main())
