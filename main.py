import os, re, json, time, hashlib
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account

USER_AGENT='BAY-S-Lead-Radar/2.0 (+https://github.com/semihselvi)'
REDDIT_URL='https://www.reddit.com/search.rss'
COLLECTION=os.getenv('FIRESTORE_COLLECTION','buyer_leads')
SCAN_COLLECTION=os.getenv('FIRESTORE_SCAN_COLLECTION','scan_logs')
MAX_RESULTS=25
DELAY=2.5

MARKETS={
'north_cyprus':(['north cyprus','northern cyprus','kuzey kıbrıs'],'Prime Kıbrıs'),
'turkey':(['turkey','türkiye','antalya','istanbul','izmir','bodrum'],'Turkey Partner'),
'greece':(['greece','athens','thessaloniki','crete','rhodes'],'Partner Network'),
'germany':(['germany','berlin','munich','frankfurt','hamburg'],'Partner Network'),
'netherlands':(['netherlands','amsterdam','rotterdam','utrecht'],'Partner Network'),
'belgium':(['belgium','brussels','antwerp','ghent'],'Partner Network'),
'france':(['france','paris','nice','cannes','lyon'],'Partner Network'),
'lithuania':(['lithuania','vilnius','kaunas'],'Partner Network'),
'switzerland':(['switzerland','zurich','geneva','basel'],'Partner Network'),
'russia':(['russia','moscow','st petersburg','москва','санкт-петербург'],'Partner Network'),
'kazakhstan':(['kazakhstan','almaty','astana','казахстан','алматы','астана'],'Partner Network'),
'united_kingdom':(['united kingdom','uk','england','london','manchester','birmingham'],'Partner Network'),
'montenegro':(['montenegro','podgorica','budva','kotor','tivat'],'Partner Network'),
'uae':(['dubai','abu dhabi','uae','united arab emirates'],'Partner Network'),
}

QUERIES=[
'"looking to buy" property','"looking for" apartment house budget','"want to buy" property',
'"buying a home" budget','"property investment" budget','"relocating" "buying property"',
'"moving" "buying a home"','"holiday home" "looking to buy"','"Golden Visa" property',
'"EU Golden Visa" property','"residency by investment" property','"хочу купить" недвижимость',
'"ищу квартиру"','"купить недвижимость за рубежом"','"ev almak istiyorum"','"ev arıyorum" gayrimenkul',
'"North Cyprus" "looking to buy"','"Turkey" "looking to buy property"','"Greece" "looking to buy property"',
'"Germany" "looking to buy property"','"Netherlands" "looking to buy property"','"Belgium" "looking to buy property"',
'"France" "looking to buy property"','"Lithuania" "looking to buy property"','"Switzerland" "looking to buy property"',
'"Russia" "buy property abroad"','"Kazakhstan" "buy property abroad"','"UK" "looking to buy property"',
'"Montenegro" "looking to buy property"','"Golden Visa" Greece buyer','"Golden Visa" Portugal buyer',
'"Golden Visa" Spain buyer','"relocation" "buy a house" Europe'
]
INTENTS=['looking to buy','looking for','want to buy','buying a home','buying property','property investment','holiday home','golden visa','residency by investment','хочу купить','ищу квартиру','купить недвижимость','ev almak','ev arıyorum','yatırım için ev']
EXCLUDES=['for sale','property for sale','listing','listings','agent','agency','realtor','developer','development','commission']

def now(): return datetime.now(timezone.utc)

def fb_client():
    raw=os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if not raw: raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON missing')
    creds=service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)

def search_reddit(q):
    headers={'User-Agent':USER_AGENT,'Accept':'application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8'}
    for attempt in range(2):
        try:
            r=requests.get(REDDIT_URL,params={'q':q,'sort':'new','t':'day','limit':MAX_RESULTS},headers=headers,timeout=15)
            if r.status_code==429:
                wait=min(int(r.headers.get('Retry-After','5')) if r.headers.get('Retry-After','5').isdigit() else 5,20)
                print(f'REDDIT_429 q={q!r} wait={wait}s')
                if attempt==0: time.sleep(wait); continue
                return []
            r.raise_for_status(); return r.text
        except requests.RequestException as e:
            print(f'REDDIT_ERROR q={q!r} attempt={attempt+1}: {e}')
            if attempt==0: time.sleep(3)
            else: return []
    return []

def parse(xml):
    soup=BeautifulSoup(xml,'html.parser'); out=[]
    for e in soup.find_all('entry')[:MAX_RESULTS]:
        link=e.find('link'); title=e.find('title'); content=e.find('content'); pub=e.find('published'); author=e.find('name')
        out.append({'source':'Reddit','url':link.get('href','').strip() if link else '','title':title.get_text(' ',strip=True) if title else '','text':content.get_text(' ',strip=True) if content else '','published':pub.get_text(strip=True) if pub else '','author':author.get_text(strip=True) if author else ''})
    return out

def fp(x): return hashlib.sha256('|'.join([x.get('url',''),x.get('title',''),x.get('author','')]).lower().encode()).hexdigest()

def market(text):
    t=text.lower()
    for m,(terms,route) in MARKETS.items():
        if any(term in t for term in terms): return m
    return 'unknown'

def lang(text):
    t=text.lower()
    if re.search(r'[а-яё]',t): return 'Russian'
    if any(x in t for x in ['ev arıyorum','ev almak istiyorum','gayrimenkul','kuzey kıbrıs','türkiye']): return 'Turkish'
    return 'English'

def budget(text):
    m=re.search(r'[$€£₺]\s?[\d,.]+(?:\s?[kKmM])?|\b(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB)\s?[\d,.]+(?:\s?[kKmM])?|\b\d{2,3}\s?[kKmM]\b',text,re.I)
    return m.group(0) if m else 'Not stated'

def timeframe(text):
    m=re.search(r'\b(?:within|in|next)\s+\d+\s+(?:days?|weeks?|months?|years?)\b|\b(?:this year|next year|soon|immediately)\b',text,re.I)
    return m.group(0) if m else 'Not stated'

def score(text):
    t=text.lower(); ih=sum(p in t for p in INTENTS); ex=sum(p in t for p in EXCLUDES)
    b=budget(text)!='Not stated'; tf=timeframe(text)!='Not stated'; personal=any(x in t for x in [' i ',' my ',' we ',' our ','ben ','biz ','я ','мы '])
    intent=min(100,40+ih*8+(12 if b else 0)+(10 if tf else 0)+(8 if personal else 0)-ex*18)
    cred=min(100,55+(15 if b else 0)+(10 if tf else 0)+(10 if personal else 0)+(10 if len(t)>=450 else 0)-ex*20)
    return intent,cred,'HOT' if intent>=82 and cred>=75 else ('WARM' if intent>=65 and cred>=65 else 'REVIEW')

def route(m): return MARKETS.get(m,([], 'Direct Review'))[1]

def reply(m):
    if m=='north_cyprus': return 'Before choosing a project, I’d compare total purchase cost, title/ownership structure, location and realistic rental potential.'
    if m=='greece': return 'For Greece, I’d compare the property budget with taxes, total acquisition costs and any Golden Visa requirements before choosing a property.'
    return 'Before choosing a property, I’d compare total acquisition cost, location, legal considerations and the main living or investment goal.'

def telegram(text):
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: print('TELEGRAM_NOT_CONFIGURED'); return
    r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':text,'disable_web_page_preview':False},timeout=10); r.raise_for_status()

def main():
    started=now(); print('BAY-S LEAD RADAR V2 STARTED'); print(f'QUERY_COUNT: {len(QUERIES)}')
    db=fb_client(); seen=set(); leads=[]; total=0; errors=0
    for i,q in enumerate(QUERIES,1):
        print(f'[{i}/{len(QUERIES)}] {q}')
        raw=search_reddit(q)
        if not raw: errors+=1; continue
        try: rows=parse(raw)
        except Exception as e: print('PARSE_ERROR',e); errors+=1; continue
        total+=len(rows)
        for item in rows:
            if not item['url']: continue
            key=fp(item)
            if key in seen: continue
            seen.add(key)
            text=f"{item['title']} {item['text']}"; m=market(text); i_score,c_score,cls=score(text)
            if cls not in ('HOT','WARM'): continue
            ref=db.collection(COLLECTION).document(key)
            if ref.get().exists: continue
            lead={**item,'lead_id':key,'language':lang(text),'market':m,'budget':budget(text),'timeframe':timeframe(text),'intent_score':i_score,'credibility_score':c_score,'market_fit_score':70 if m!='unknown' else 40,'classification':cls,'route_to':route(m),'reply_suggestion':reply(m),'found_at':started.isoformat()}
            ref.set(lead); leads.append(lead)
        time.sleep(DELAY)
    finished=now(); scan={'started_at':started.isoformat(),'completed_at':finished.isoformat(),'status':'completed','queries':len(QUERIES),'total_results':total,'unique_results':len(seen),'new_hot_warm':len(leads),'errors':errors,'source':'Reddit'}
    db.collection(SCAN_COLLECTION).document(started.strftime('%Y%m%dT%H%M%SZ')).set(scan)
    if leads:
        for x in leads[:10]: telegram(f"{'🔥' if x['classification']=='HOT' else '🟡'} BAY-S RADAR — {x['classification']}\n\n{x['source']} | {x['author'] or 'Not stated'}\n{x['market']} | {x['route_to']}\n{x['title']}\nBudget: {x['budget']}\nTimeframe: {x['timeframe']}\nIntent {x['intent_score']} | Credibility {x['credibility_score']} | Market Fit {x['market_fit_score']}\n\nReply suggestion:\n{x['reply_suggestion']}\n\n🔗 {x['url']}")
    else:
        telegram(f"ℹ️ BAY-S RADAR\n\nTarama tamamlandı.\nSon taramadan beri yeni HOT/WARM buyer lead bulunamadı.\n\nReddit sorguları: {len(QUERIES)}\nToplam sonuç: {total}\nYeni lead: 0\nKaynak hatası: {errors}")
    print(json.dumps(scan,ensure_ascii=False,indent=2)); print('BAY-S LEAD RADAR V2 FINISHED')

if __name__=='__main__': main()
