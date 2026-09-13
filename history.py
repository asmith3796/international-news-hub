"""Price history for the hub's charts (v2.4, 9/13). One-time fill of a year of daily index closes (Yahoo's public chart endpoint,
unofficial) and daily currency rates per USD (Frankfurter, the ECB's reference rates, free, no key); then finance.py appends each
day's values. Writes site/data/history.json: {cc: {"index": [[YYYY-MM-DD, close], ...], "fx": [[YYYY-MM-DD, per_usd], ...]}}.
Run: python3 history.py (fill missing years); python3 history.py --append (called by finance.py with today's values)."""
import json, os, sys, time, datetime, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, "site", "data", "history.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/2.0; +https://internationalnewshub.com)"}
def get(url, timeout=25): return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))
def load(): return json.load(open(OUT)) if os.path.exists(OUT) else {}
def save(h): json.dump(h, open(OUT, "w"), separators=(",", ":"))
def merge(series, points):
    d = dict(series or []); d.update({k: v for k, v in points if v is not None}); return sorted(d.items())[-400:]

def fill():
    countries = json.load(open(os.path.join(ROOT, "countries.json"))); h = load()
    for cc, c in countries.items():
        try:
            sym = urllib.parse.quote(c["index"]["symbol"], safe="")
            r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d")["chart"]["result"][0]
            ts = r["timestamp"]; cl = r["indicators"]["quote"][0]["close"]
            pts = [(datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), round(v, 2)) for t, v in zip(ts, cl) if v]
            h.setdefault(cc, {})["index"] = merge(h.get(cc, {}).get("index"), pts); print(cc, "index", len(pts), "days")
            time.sleep(0.6)
        except Exception as e: print(cc, "index failed", str(e)[:80])
    syms = sorted({c["currency"] for c in countries.values() if c["currency"] != "USD"})
    end = datetime.date.today(); start = end - datetime.timedelta(days=370)
    try:
        r = get(f"https://api.frankfurter.app/{start}..{end}?from=USD&to={','.join(syms)}")
        rates = r.get("rates", {}); got = {s: [(d, v[s]) for d, v in sorted(rates.items()) if s in v] for s in syms}
        for cc, c in countries.items():
            cur = c["currency"]
            if cur == "USD": h.setdefault(cc, {})["fx"] = merge(h.get(cc, {}).get("fx"), [(d, 1.0) for d in sorted(rates)]); continue
            if got.get(cur): h.setdefault(cc, {})["fx"] = merge(h.get(cc, {}).get("fx"), got[cur])
        print("fx:", {s: len(v) for s, v in got.items()})
    except Exception as e: print("fx fill failed", str(e)[:100])
    save(h)

def append():
    """Today's values from finance.json into the history (one point per date)."""
    fin = json.load(open(os.path.join(ROOT, "site", "data", "finance.json"))).get("countries", {}); h = load(); today = datetime.date.today().isoformat()
    for cc, f in fin.items():
        ix, fx = f.get("index"), f.get("fx")
        if ix and ix.get("price"):
            d = datetime.datetime.utcfromtimestamp(ix["time"]).strftime("%Y-%m-%d") if ix.get("time") else today
            h.setdefault(cc, {})["index"] = merge(h.get(cc, {}).get("index"), [(d, round(ix["price"], 2))])
        if fx and fx.get("per_usd"): h.setdefault(cc, {})["fx"] = merge(h.get(cc, {}).get("fx"), [(today, fx["per_usd"])])
    save(h); print("history appended for", len(fin), "countries")

if __name__ == "__main__": append() if "--append" in sys.argv else fill()
