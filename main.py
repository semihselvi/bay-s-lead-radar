import os, re, json, time, hashlib, warnings
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from google.cloud import firestore
from google.oauth2 import service_account
from config import COLLECTION, SCAN_LOG_COLLECTION, MAX_RESULTS_PER_SOURCE, MARKETS, INTENT_PHRASES, EXCLUDE_PHRASES, ROUTES

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

UA = 'BAY-S-Lead-Radar/4.0 (+https://github.com/semihselvi)'
REDDIT_URL = 'https://www.reddit.com/search.rss'
NEWS_URL = 'https://news.google.com/rss/search'
TIMEOUT = 15
REDDIT_DELAY = 7
NEWS_DELAY = 0.5
MAX_RESULTS = max(10, min(int(MAX_RESULTS_PER_SOURCE), 25))
REDDIT_PER_RUN = 18
NEWS_PER_RUN = 8
MAX_TELEGRAM_LEADS = 10

S = requests.Session()
S.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})

# Extra coverage without changing config.py
EXTRA = {
 'spain':(['Spain','Madrid','Barcelona','Valencia','Malaga','Alicante','Marbella'],'Golden Visa Partner'),
 'portugal':(['Portugal','Lisbon','Porto','Algarve','Cascais'],'Golden Visa Partner'),
 'italy':(['Italy','Rome','Milan','Florence','Naples','Sicily'],'Partner Network'),
 'poland':(['Poland','Warsaw','Krakow','Wroclaw','Gdansk'],'Partner Network'),
 'czechia':(['Czech Republic','Czechia','Prague','Brno'],'Partner Network'),
 'austria':(['Austria','Vienna','Salzburg','Graz'],'Partner Network'),
 'ireland':(['Ireland','Dublin','Cork','Galway'],'Partner Network'),
 'estonia':(['Estonia','Tallinn','Tartu'],'Partner Network'),
 'latvia':(['Latvia','Riga','Jurmala'],'Partner Network'),
 'finland':(['Finland','Helsinki','Espoo','Tampere'],'Partner Network'),
 'sweden':(['Sweden','Stockholm','Gothenburg','Malmo'],'Partner Network'),
 'norway':(['Norway','Oslo','Bergen','Stavanger'],'Partner Network'),
 'denmark':(['Denmark','Copenhagen','Aarhus'],'Partner Network'),
 'hungary':(['Hungary','Budapest'],'Partner Network'),
 'romania':(['Romania','Bucharest','Cluj'],'Partner Network'),
 'bulgaria':(['Bulgaria','Sofia','Varna','Burgas'],'Partner Network'),
 'luxembourg':(['Luxembourg'],'Partner Network'),
 'malta':(['Malta','Valletta','Sliema'],'Partner Network'),
 'uae':(['UAE','United Arab Emirates','Dubai','Abu Dhabi'],'Partner Network'),
 'qatar':(['Qatar','Doha'],'Partner Network'),
 'saudi_arabia':(['Saudi Arabia','Riyadh','Jeddah'],'Partner Network'),
 'slovakia':(['Slovakia','Bratislava','Kosice'],'Partner Network'),
 'slovenia':(['Slovenia','Ljubljana','Koper'],'Partner Network'),
 'serbia':(['Serbia','Belgrade','Novi Sad'],'Partner Network'),
}
SAFE = {
 'north_cyprus':['North Cyprus','Northern Cyprus','Kuzey Kıbrıs','Iskele','Long Beach','Kyrenia','Girne','Esentepe','Famagusta','Gazimağusa'],
 'turkey':['Turkey','Türkiye','Antalya','Alanya','Mersin','Istanbul','İstanbul','Izmir','İzmir','Bodrum','Fethiye'],
 'greece':['Greece','Athens','Thessaloniki','Crete','Rhodes','Corfu','Mykonos'],
 'germany':['Germany','Berlin','Munich','Frankfurt','Hamburg','Cologne','Deutschland'],
 'netherlands':['Netherlands','Amsterdam','Rotterdam','The Hague','Utrecht','Nederland'],
 'belgium':['Belgium','Brussels','Antwerp','Ghent'],
 'france':['France','Paris','Nice','Cannes','Marseille','Lyon'],
 'lithuania':['Lithuania','Vilnius','Kaunas','Klaipeda'],
 'switzerland':['Switzerland','Zurich','Geneva','Lausanne','Basel','Zug','Lugano'],
 'russia':['Russia','Россия','Moscow','Москва','St Petersburg','Санкт-Петербург'],
 'kazakhstan':['Kazakhstan','Казахстан','Almaty','Алматы','Astana','Астана'],
 'montenegro':['Montenegro','Budva','Kotor','Tivat','Podgorica','Bar'],
 'uk':['United Kingdom','UK','London','Manchester','Birmingham','Leeds','Brighton'],
}
MARKET_INFO={k:(v,ROUTES.get(k,'Partner Network')) for k,v in SAFE.items()}
MARKET_INFO.update(EXTRA)

PROP = ['property','real estate','home','house','apartment','condo','flat','villa','townhouse','residence','residential','land','mortgage','down payment','deposit','rental income','rental yield','golden visa','residency by investment','ev','konut','daire','gayrimenkul','mülk','arsa','квартира','дом','недвижимость','ипотека','аренда']
BUY = ['looking to buy','want to buy','wanting to buy','planning to buy','ready to buy','thinking of buying','buying a home','buying a house','buying property','buy an apartment','buy apartment','buy a villa','looking for a house','looking for an apartment','cash buyer','first time buyer','first-time buyer','first home buyer','property buyer','looking to purchase','relocating and buying','moving and buying','purchase','how much can i afford','ev almak','ev arıyorum','ev almak istiyorum','satın almak','gayrimenkul almak','yatırım için ev','хочу купить','ищу квартиру','купить квартиру','купить дом','купить недвижимость','нужна квартира','планирую купить','недвижимость за рубежом']
CONCRETE = ['budget','$','€','£','aed','eur','gbp','usd','chf','try','kzt','rub','mortgage','down payment','deposit','bedroom','1br','2br','3br','1 bhk','2 bhk','3 bhk','rent','rental income','yield','first home','moving','relocating','next month','next year','this year','2026','2027','bütçe','kredi','kapora','oda','kira','taşınmak','я ищу','мой бюджет','ипотека','переезд']
PERSONAL = [' i ',' i\'m',' i am ',' we ',' we\'re',' my ',' our ',' my family',' for myself',' for me','ben ','biz ','ailem','kendim için','я ','мы ','моя семья','для себя']
AGENCY = ['for my client','for a client','my clients','client looking','buyer client','customer','real estate agent','estate agent','realtor','broker','developer','property developer','property listing','listing page','our properties','our project','contact us','whatsapp us','call us','we sell','available units','new project','commission','lead generation','marketing agency','property management service','агентство недвижимости','риэлтор','застройщик','продам','продается','продаю']
NOISE = {'memes','funny','askreddit','offmychest','family','askchicago','whatshouldido','whatdoido','arknights'}
GLOBAL_Q = ['"looking to buy" (property OR house OR apartment)','"want to buy" (property OR house OR apartment)','"first time buyer" (house OR home OR apartment)','"cash buyer" (property OR house)','"property investment" budget','"investment property" budget','"rental income" property','"moving" "buying a home"','"relocating" "buying property"','"holiday home" property','"Golden Visa" property','"EU Golden Visa" property','"residency by investment" property','"хочу купить" недвижимость','"ищу квартиру" недвижимость','"недвижимость за рубежом"','"ev almak istiyorum" gayrimenkul','"Kıbrıs" ev almak']
GOLDEN = ['"Golden Visa" Greece property','"Golden Visa" Portugal property','"Golden Visa" Spain property','"Golden Visa" Europe buyer','"residency by investment" Greece','"residency by investment" Europe']
FIXED = ['"North Cyprus" property buyer','"Turkey" property buyer','"Greece" property buyer','"Germany" property buyer','"Netherlands" property buyer','"Belgium" property buyer','"France" property buyer','"Lithuania" property buyer','"Switzerland" property buyer','"Russia" "buy property abroad"','"Kazakhstan" "buy property abroad"','"Montenegro" property buyer','"UK" property buyer','"Spain" property buyer','"Portugal" property buyer','"Italy" property buyer','"Poland" property buyer','"Czech Republic" property buyer','"Austria" property buyer','"Ireland" property buyer','"Estonia" property buyer','"Latvia" property buyer','"Finland" property buyer','"Sweden" property buyer','"Norway" property buyer','"Denmark" property buyer','"UAE" property buyer','"Dubai" property buyer','"Qatar" property buyer','"Saudi Arabia" property buyer']

def client():
 raw=os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
 if not raw: raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON missing')
 try: info=json.loads(raw)
 except json.JSONDecodeError as e: raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON') from e
 cred=service_account.Credentials.from_service_account_info(info)
 return firestore.Client(credentials=cred)

def text(item): return f"{item.get('title','')} {item.get('text','')}".strip()

def has(t,terms):
 x=t.lower(); return any(a.lower() in x for a in terms)

def subreddit(url):
 m=re.search(r'/r/([^/]+)',url or ''); return m.group(1).lower() if m else ''

def market_for(t):
 x=t.lower()
 order=['north_cyprus','greece','germany','netherlands','belgium','france','switzerland','lithuania','kazakhstan','russia','turkey','montenegro','uk']+list(EXTRA.keys())
 for k in order:
  for term in MARKET_INFO[k][0]:
   if term.lower() in x: return k
 return 'unknown'

def budget(t):
 for p in [r'[$€£₺]\s?[\d,.]+(?:\s?[kKmM])?',r'\b(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB)\s?[\d,.]+(?:\s?[kKmM])?\b',r'\b\d{2,3}\s?[kKmM]\b']:
  m=re.search(p,t,re.I)
  if m:return m.group(0)
 return 'Not stated'

def timeframe(t):
 for p in [r'\b(?:within|in|next)\s+\d+\s+(?:days?|weeks?|months?|years?)\b',r'\bthis year\b',r'\bnext year\b',r'\bsoon\b',r'\bimmediately\b',r'\b2026\b',r'\b2027\b']:
  m=re.search(p,t,re.I)
  if m:return m.group(0)
 return 'Not stated'

def city(t,k):
 if k=='unknown':return 'Not stated'
 x=t.lower(); countries={'turkey','türkiye','greece','germany','netherlands','belgium','france','lithuania','switzerland','russia','kazakhstan','montenegro','uk','united kingdom'}
 for term in MARKET_INFO[k][0]:
  if term.lower() in x and term.lower() not in countries:return term
 return 'Not stated'

def lang(t):
 x=t.lower()
 if re.search(r'[а-яё]',x):return 'Russian'
 if has(x,['ev almak','ev arıyorum','gayrimenkul','kıbrıs','satın almak']):return 'Turkish'
 return 'English'

def valid(item):
 t=text(item)
 if len(t)<80:return False,'too_short'
 if not has(t,PROP):return False,'no_property'
 if not has(t,BUY):return False,'no_buyer'
 if has(t,AGENCY):return False,'agency_or_listing'
 if subreddit(item.get('url','')) in NOISE:return False,'noisy_subreddit'
 if not has(t,CONCRETE) and not has(t,PERSONAL):return False,'no_concrete_or_personal'
 return True,'ok'

def score(item,k):
 t=text(item).lower(); hits=sum(1 for p in INTENT_PHRASES if p.lower() in t)
 b=budget(t)!='Not stated'; tf=timeframe(t)!='Not stated'; c=has(t,CONCRETE); p=has(t,PERSONAL); d=len(t)>=450
 intent=min(100,45+hits*7+(12 if b else 0)+(10 if tf else 0)+(10 if p else 0)+(5 if c else 0))
 cred=min(100,55+(15 if b else 0)+(10 if tf else 0)+(10 if p else 0)+(10 if d else 0)+(5 if c else 0))
 fit=45 if k=='unknown' else 70
 if b:fit+=10
 if k in {'north_cyprus','turkey','greece','germany','netherlands','belgium','france','switzerland','lithuania','spain','portugal','italy'}:fit+=8
 fit=max(0,min(100,fit))
 if intent>=88 and cred>=80 and c: cls='HOT'
 elif intent>=72 and cred>=70: cls='WARM'
 else: cls='REVIEW'
 return intent,cred,fit,cls

def fp(item):
 raw='|'.join([item.get('url',''),item.get('title',''),item.get('author','')]).lower(); return hashlib.sha256(raw.encode()).hexdigest()

def reddit(q):
 try:
  r=S.get(REDDIT_URL,params={'q':q,'sort':'new','t':'day','limit':MAX_RESULTS},timeout=TIMEOUT)
  if r.status_code==429: print('REDDIT_429 query='+q); return []
  r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser'); out=[]
  for e in soup.find_all('entry')[:MAX_RESULTS]:
   l=e.find('link'); ti=e.find('title'); c=e.find('content'); p=e.find('published'); a=e.find('name')
   out.append({'source':'Reddit','url':l.get('href','').strip() if l else '','title':ti.get_text(' ',strip=True) if ti else '','text':c.get_text(' ',strip=True) if c else '','published':p.get_text(strip=True) if p else '','author':a.get_text(strip=True) if a else ''})
  return out
 except requests.RequestException as e:
  print('REDDIT_ERROR',e); return []
 finally: time.sleep(REDDIT_DELAY)

def news(q):
 try:
  r=S.get(NEWS_URL,params={'q':q+' when:1d','hl':'en-US','gl':'US','ceid':'US:en'},timeout=TIMEOUT); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser'); out=[]
  for e in soup.find_all('item')[:MAX_RESULTS]:
   l=e.find('link'); ti=e.find('title'); d=e.find('description'); p=e.find('pubDate')
   out.append({'source':'Google News','url':l.get_text(strip=True) if l else '','title':ti.get_text(' ',strip=True) if ti else '','text':d.get_text(' ',strip=True) if d else '','published':p.get_text(strip=True) if p else '','author':''})
  return out
 except requests.RequestException as e:
  print('GOOGLE_NEWS_ERROR',e); return []
 finally: time.sleep(NEWS_DELAY)

def market_queries():
 pool=[]
 for k,(terms,_) in MARKET_INFO.items():
  if k in EXTRA: join=' OR '.join(f'"{x}"' for x in terms[:3])
  else: join=' OR '.join(f'"{x}"' for x in terms[:3])
  q=f'({join}) ("looking to buy" OR "want to buy" OR "property buyer" OR "property investment")'
  pool.append(q)
  if k in {'russia','kazakhstan'}: pool.append(f'({join}) ("хочу купить" OR "ищу квартиру" OR "недвижимость за рубежом")')
 return pool

def select_queries(db):
 pool=[]
 seen=set()
 for q in GLOBAL_Q+GOLDEN+FIXED+market_queries():
  n=q.lower().strip()
  if n and n not in seen: seen.add(n); pool.append(q)
 state_ref=db.collection(SCAN_LOG_COLLECTION).document('_query_state'); snap=state_ref.get(); data=snap.to_dict() if snap.exists else {}
 off=int(data.get('offset',0)); selected=[]
 # Keep 8 broad globals every run and rotate the rest.
 broad=GLOBAL_Q[:8]
 selected.extend(broad)
 rest=[q for q in pool if q not in broad]
 take=max(0,REDDIT_PER_RUN-len(selected))
 for i in range(min(take,len(rest))): selected.append(rest[(off+i)%len(rest)])
 state_ref.set({'offset':(off+len(selected)-len(broad))%max(1,len(rest)),'pool_size':len(pool),'updated_at':datetime.now(timezone.utc).isoformat()})
 return selected,pool

def route(k): return MARKET_INFO.get(k,('',ROUTES.get(k,'Direct Review')))[1]

def reply(k):
 return {'north_cyprus':'Compare location, total acquisition cost, ownership structure and realistic rental potential before selecting a project.','greece':'Compare purchase cost, taxes and Golden Visa requirements before selecting a property.','germany':'Compare purchase price, financing, taxes and ongoing ownership costs before choosing an area.','netherlands':'Separate purchase budget from closing and ownership costs before comparing neighborhoods.','france':'Compare purchase budget, acquisition costs and the living or investment objective first.'}.get(k,'Compare total acquisition cost, location, legal considerations and the investment or living goal before choosing a property.')

def telegram(msg):
 tok=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
 if not tok or not chat: print('TELEGRAM_NOT_CONFIGURED'); return
 try:S.post(f'https://api.telegram.org/bot{tok}/sendMessage',json={'chat_id':chat,'text':msg,'disable_web_page_preview':False},timeout=10).raise_for_status()
 except requests.RequestException as e: print('TELEGRAM_ERROR',e)

def format_lead(x):
 emoji='🔥' if x['classification']=='HOT' else '🟠'
 return (f"{emoji} BAY-S RADAR — {x['classification']}\n\nSource: {x['source']}\nAuthor: {x.get('author') or 'Not stated'}\nLanguage: {x['language']}\nMarket: {x['market']}\nCity/Region: {x['city_region']}\n\nWhat they want:\n{x['title']}\n\nBudget: {x['budget']}\nTimeframe: {x['timeframe']}\nIntent: {x['intent_score']}/100\nCredibility: {x['credibility_score']}/100\nMarket Fit: {x['market_fit_score']}/100\nRoute To: {x['route_to']}\n\nReply suggestion:\n{x['reply_suggestion']}\n\n🔗 {x['url']}")

def main():
 started=datetime.now(timezone.utc); print('BAY-S LEAD RADAR V4 STARTED'); db=client(); queries,pool=select_queries(db); print(f'TOTAL_QUERY_POOL: {len(pool)}'); print(f'QUERY_COUNT_THIS_SCAN: {len(queries)}')
 seen=set(); leads=[]; source={'Reddit':0,'Google News':0}; errors={'Reddit':0,'Google News':0,'Firestore':0}; rejected={}
 for i,q in enumerate(queries,1):
  print(f'[REDDIT {i}/{len(queries)}] {q}')
  try: rows=reddit(q); source['Reddit']+=len(rows)
  except Exception as e: errors['Reddit']+=1; print('REDDIT_QUERY_ERROR',e); rows=[]
  for item in rows:
   if not item.get('url'): continue
   key=fp(item)
   if key in seen: continue
   seen.add(key)
   ok,reason=valid(item)
   if not ok: rejected[reason]=rejected.get(reason,0)+1; continue
   t=text(item); k=market_for(t); intent,cred,fit,cls=score(item,k)
   if cls not in {'HOT','WARM'}: rejected['low_score']=rejected.get('low_score',0)+1; continue
   ref=db.collection(COLLECTION).document(key)
   try:
    if ref.get().exists: print('EXISTING_LEAD:',key); continue
   except Exception as e: errors['Firestore']+=1; print('FIRESTORE_READ_ERROR',e); continue
   lead={**item,'lead_id':key,'language':lang(t),'market':k,'city_region':city(t,k),'budget':budget(t),'timeframe':timeframe(t),'intent_score':intent,'credibility_score':cred,'market_fit_score':fit,'classification':cls,'route_to':route(k),'reply_suggestion':reply(k),'found_at':started.isoformat()}
   try: ref.set(lead)
   except Exception as e: errors['Firestore']+=1; print('FIRESTORE_WRITE_ERROR',e); continue
   leads.append(lead); print(f'NEW_LEAD: {cls} | {k} | {item["url"]}')
 # Google News supplement, not the main source.
 news_q=(GLOBAL_Q[:4]+GOLDEN[:2]+FIXED[:2])[:NEWS_PER_RUN]
 for i,q in enumerate(news_q,1):
  print(f'[NEWS {i}/{len(news_q)}] {q}')
  rows=news(q); source['Google News']+=len(rows)
  for item in rows:
   if not item.get('url'): continue
   key=fp(item)
   if key in seen: continue
   seen.add(key)
   ok,reason=valid(item)
   if not ok: rejected[reason]=rejected.get(reason,0)+1; continue
   t=text(item); k=market_for(t); intent,cred,fit,cls=score(item,k)
   if cls not in {'HOT','WARM'}: rejected['low_score']=rejected.get('low_score',0)+1; continue
   ref=db.collection(COLLECTION).document(key)
   try:
    if ref.get().exists: continue
    lead={**item,'lead_id':key,'language':lang(t),'market':k,'city_region':city(t,k),'budget':budget(t),'timeframe':timeframe(t),'intent_score':intent,'credibility_score':cred,'market_fit_score':fit,'classification':cls,'route_to':route(k),'reply_suggestion':reply(k),'found_at':started.isoformat()}; ref.set(lead); leads.append(lead); print(f'NEW_LEAD: {cls} | {k} | {item["url"]}')
   except Exception as e: errors['Firestore']+=1; print('FIRESTORE_ERROR',e)
 finished=datetime.now(timezone.utc); scan={'started_at':started.isoformat(),'completed_at':finished.isoformat(),'status':'completed','source_results':source,'unique_results':len(seen),'new_hot_warm':len(leads),'source_errors':errors,'rejected':rejected,'total_query_pool':len(pool),'queries_this_scan':len(queries),'news_queries_this_scan':len(news_q)}
 try: db.collection(SCAN_LOG_COLLECTION).document(started.strftime('%Y%m%dT%H%M%SZ')).set(scan)
 except Exception as e: print('SCAN_LOG_ERROR',e)
 print(json.dumps(scan,ensure_ascii=False,indent=2))
 if leads:
  for lead in leads[:MAX_TELEGRAM_LEADS]: telegram(format_lead(lead))
 else:
  telegram('ℹ️ BAY-S RADAR\n\nTarama tamamlandı.\nSon taramadan beri yeni HOT/WARM buyer lead bulunamadı.\n\nReddit sonuçları: '+str(source['Reddit'])+'\nGoogle News sonuçları: '+str(source['Google News'])+'\nYeni lead: 0\nElgenen aday: '+str(sum(rejected.values())))
 print('BAY-S LEAD RADAR V4 FINISHED')

if __name__=='__main__': main()
