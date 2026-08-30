# BAY-S Lead Radar V5 test branch

North Cyprus foreign property-buyer radar with Firestore deduplication and Telegram alerts.

V5.1.1 requires real-estate context plus explicit self-buyer or purchase-consideration language before Telegram alerts. Seller/listing copy, rentals, vehicles and household-item purchases are rejected by regression-tested gates.

Secrets:
- FIREBASE_SERVICE_ACCOUNT_JSON
- FIRESTORE_COLLECTION (optional)
- FIRESTORE_SCAN_COLLECTION (optional)
- TELEGRAM_BOT_TOKEN (optional)
- TELEGRAM_CHAT_ID (optional)
