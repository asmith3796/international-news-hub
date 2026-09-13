"""Financial strip for each country page (v2, 9/11). Free daily sources, no keys:
- exchange rates: open.er-api.com (USD base, updated daily)
- stock index: Yahoo Finance's public chart endpoint (last price and previous close; unofficial, so failures are tolerated and the last good value is kept)
- GDP size, GDP growth, inflation: World Bank API (yearly; the year is shown)
- central bank policy rate: rates.json, a table maintained by hand with source and date (no free feed exists)
Writes site/data/finance.json. Run by hourly.sh; each source is fetched at most once per run and kept if a fetch fails."""
import json, os, time, urllib.request, urllib.parse, datetime
ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, "site", "data", "finance.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/2.0; +https://internationalnewshub.com)"}
def get(url, timeout=20):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))
def log(*a): print(datetime.datetime.utcnow().strftime("%H:%M:%S"), *a, flush=True)

def main():
    countries = json.load(open(os.path.join(ROOT, "countries.json")))
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {"countries": {}}
    rates_table = json.load(open(os.path.join(ROOT, "rates.json"))) if os.path.exists(os.path.join(ROOT, "rates.json")) else {}
    out = {"updated": int(time.time()), "countries": {}}
    try: fx = get("https://open.er-api.com/v6/latest/USD"); fxr = fx.get("rates", {}); fx_date = fx.get("time_last_update_utc", "")[:16]
    except Exception as e: log("fx failed", str(e)[:80]); fxr = {}; fx_date = ""
    wb = {}
    for ind, key in (("NY.GDP.MKTP.KD.ZG", "gdp_growth"), ("FP.CPI.TOTL.ZG", "inflation"), ("NY.GDP.MKTP.CD", "gdp_usd")):
        try:
            codes = ";".join(c["wb"] for c in countries.values())
            for row in get(f"https://api.worldbank.org/v2/country/{codes}/indicator/{ind}?format=json&mrv=1&per_page=100")[1]:
                if row.get("value") is not None: wb.setdefault(row["countryiso3code"], {})[key] = {"value": row["value"], "year": row["date"]}
        except Exception as e: log("world bank failed", ind, str(e)[:80])
    for cc, c in countries.items():
        p = prev.get("countries", {}).get(cc, {})
        rec = {"currency": c["currency"], "index_name": c["index"]["name"]}
        # currency: units per USD, and the change against yesterday's stored value when we have one
        if c["currency"] in fxr:
            rec["fx"] = {"per_usd": fxr[c["currency"]], "date": fx_date}
            if p.get("fx", {}).get("per_usd") and p["fx"].get("date") != fx_date: rec["fx"]["prev"] = p["fx"]["per_usd"]
            elif p.get("fx", {}).get("prev"): rec["fx"]["prev"] = p["fx"]["prev"]
        elif c["currency"] == "USD": rec["fx"] = {"per_usd": 1.0, "date": fx_date}
        elif p.get("fx"): rec["fx"] = p["fx"]
        # index
        try:
            sym = urllib.parse.quote(c["index"]["symbol"], safe="")
            m = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d", timeout=15)["chart"]["result"][0]["meta"]
            price, prevc = m.get("regularMarketPrice"), m.get("chartPreviousClose")
            if price: rec["index"] = {"price": price, "prev": prevc, "change_pct": (round((price / prevc - 1) * 100, 2) if prevc else None), "time": m.get("regularMarketTime")}
            elif p.get("index"): rec["index"] = p["index"]
            time.sleep(0.5)
        except Exception as e:
            log("index failed", cc, str(e)[:60])
            if p.get("index"): rec["index"] = p["index"]
        w = wb.get(c["wb"], {})
        for k in ("gdp_growth", "inflation", "gdp_usd"):
            if k in w: rec[k] = w[k]
            elif k in p: rec[k] = p[k]
        if cc in rates_table: rec["policy_rate"] = rates_table[cc]
        out["countries"][cc] = rec
    json.dump(out, open(OUT, "w"))
    try:
        import history; history.append()                                # v2.4: today's values into the chart history
    except Exception as e: log("history append failed", str(e)[:80])
    log("finance.json written for", len(out["countries"]), "countries; fx", "ok" if fxr else "kept", "| world bank rows", sum(len(v) for v in wb.values()))

if __name__ == "__main__": main()
