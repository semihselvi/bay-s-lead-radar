import json
from datetime import datetime, timezone
import main as core

START = datetime.fromisoformat("2026-10-07T12:24:00+00:00")

def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:
        return None

def main():
    db = core.db()
    rows=[]
    for snap in db.collection(core.COLLECTION).stream():
        d=snap.to_dict() or {}
        dt=parse_dt(d.get("v6_notified_at") or d.get("core_notified_at"))
        if not dt or dt < START:
            continue
        rows.append({
            "lead_id": d.get("lead_id") or snap.id,
            "author": d.get("author",""),
            "group": d.get("group",""),
            "message": str(d.get("message") or d.get("text") or "")[:1200],
            "url": d.get("url",""),
            "lead_class": d.get("lead_class",""),
            "intent_score": d.get("intent_score",0),
            "language": d.get("language",""),
            "region": d.get("estimated_region",""),
            "budget": d.get("estimated_budget",""),
            "criteria": d.get("important_criteria",[]),
            "reasons": d.get("lead_reasons",[]),
            "notified_at": d.get("v6_notified_at") or d.get("core_notified_at"),
        })
    rows.sort(key=lambda x: x.get("notified_at",""))
    print("RECENT_BUYER_AUDIT", json.dumps({"count":len(rows),"rows":rows}, ensure_ascii=False))

if __name__=="__main__":
    main()
