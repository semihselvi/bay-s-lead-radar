import os

COLLECTION = os.getenv("FIRESTORE_COLLECTION", "bay_s_leads")
SCAN_LOG_COLLECTION = os.getenv("FIRESTORE_SCAN_COLLECTION", "bay_s_radar_scans")
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
MAX_RESULTS_PER_SOURCE = int(os.getenv("MAX_RESULTS_PER_SOURCE", "15"))

MARKETS = {
    "north_cyprus": ["North Cyprus","Northern Cyprus","Kuzey Kıbrıs","Северный Кипр","Iskele","İskele","Long Beach","Kyrenia","Girne","Esentepe","Famagusta","Gazimağusa"],
    "turkey": ["Turkey","Türkiye","Antalya","Alanya","Mersin","Istanbul","İstanbul","Izmir","İzmir","Bodrum","Fethiye"],
    "greece": ["Greece","Athens","Thessaloniki","Crete","Rhodes","Corfu","Golden Visa"],
    "germany": ["Germany","Berlin","Munich","Frankfurt","Hamburg","Cologne"],
    "netherlands": ["Netherlands","Amsterdam","Rotterdam","The Hague","Utrecht"],
    "belgium": ["Belgium","Brussels","Antwerp","Ghent"],
    "france": ["France","Paris","Nice","Cannes","Marseille","Lyon"],
    "lithuania": ["Lithuania","Vilnius","Kaunas","Klaipeda"],
    "switzerland": ["Switzerland","Zurich","Geneva","Lausanne","Basel","Zug","Lugano"],
    "russia": ["Russia","Россия","Северный Кипр","Греция","Германия","Нидерланды","Бельгия","Франция","Литва","Черногория","Турция"],
    "kazakhstan": ["Kazakhstan","Казахстан","Almaty","Алматы","Astana","Астана"],
    "montenegro": ["Montenegro","Budva","Kotor","Tivat","Podgorica","Bar"],
    "uk": ["United Kingdom","UK","London","Manchester","Birmingham","Leeds","Brighton"],
}

INTENT_PHRASES = [
    "looking to buy","want to buy","looking for","buying property","buy property",
    "buy a house","buy an apartment","buy apartment","buy villa","property budget",
    "cash buyer","investment property","property investment","moving to","relocating to",
    "looking to purchase","ready to buy","planning to buy",
    "ev almak","ev arıyorum","satın almak","gayrimenkul almak","yatırım yapmak",
    "хочу купить","ищу квартиру","купить квартиру","купить дом","купить недвижимость",
    "недвижимость за рубежом","инвестиции в недвижимость","переезд","планирую купить",
    "Golden Visa","residency by investment","property for residency",
]

EXCLUDE_PHRASES = [
    "contact us","call us","whatsapp us","our properties","property developer",
    "real estate agency","estate agent","realtor","broker","listing page",
    "for sale","we sell","available units","new project","developer",
    "продам","продается","агентство","застройщик","риэлтор",
]

ROUTES = {
    "north_cyprus":"Prime Kıbrıs",
    "turkey":"Turkey Partner",
    "germany":"Germany Partner",
    "netherlands":"Netherlands Partner",
    "france":"France Partner",
    "greece":"Golden Visa Partner",
    "switzerland":"Partner Network",
    "belgium":"Partner Network",
    "lithuania":"Partner Network",
    "russia":"Partner Network",
    "kazakhstan":"Partner Network",
    "montenegro":"Partner Network",
    "uk":"Partner Network",
}
