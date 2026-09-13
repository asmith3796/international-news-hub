"""Market-implied odds for the Elections page (v2.8, 9/13, his ruling). Polymarket's public feed, no key: for each curated event
(the 2026 US control and marquee races, the foreign votes on the hub) the top outcomes by 'yes' price. A price is what bettors
pay for a yes, shown as a percentage and labeled as such on the page. Writes site/data/odds.json; missing events are skipped;
a failed fetch keeps the last file. Run by hourly.sh before build.py."""
import json, os, time, urllib.request, urllib.parse, datetime
ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, "site", "data", "odds.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/2.0; +https://internationalnewshub.com)"}
EVENTS = [  # (slug, label shown, group)
    ("which-party-will-win-the-senate-in-2026", "US Senate control, 2026", "US"),
    ("which-party-will-win-the-house-in-2026", "US House control, 2026", "US"),
    ("texas-senate-election-winner", "Texas Senate", "US"), ("north-carolina-senate-election-winner", "North Carolina Senate", "US"),
    ("georgia-senate-election-winner", "Georgia Senate", "US"), ("ohio-senate-election-winner", "Ohio Senate", "US"), ("maine-senate-election-winner", "Maine Senate", "US"),
    ("michigan-senate-election-winner", "Michigan Senate", "US"), ("texas-governor-winner-2026", "Texas Governor", "US"), ("california-governor-election-2026", "California Governor", "US"),
    ("florida-governor-winner-2026", "Florida Governor", "US"), ("pennsylvania-governor-winner-2026", "Pennsylvania Governor", "US"),
    ("new-york-governor-winner-2026", "New York Governor", "US"), ("presidential-election-winner-2028", "US President, 2028", "US"),
    ("brazil-presidential-election", "Brazil: President, October 2026", "World"),
    ("which-party-will-gain-most-seats-in-russian-parliamentary-election", "Russia: Duma, September 2026", "World"),
]
def get(url): return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
def main():
    out = {"updated": int(time.time()), "source": "Polymarket", "events": []}
    for slug, label, group in EVENTS:
        try:
            ev = get(f"https://gamma-api.polymarket.com/events?slug={urllib.parse.quote(slug)}")
            ev = ev[0] if isinstance(ev, list) and ev else None
            if not ev or ev.get("closed"): continue
            rows = []
            for m in ev.get("markets", []):
                if m.get("closed"): continue
                try: yes = float(json.loads(m.get("outcomePrices") or "[]")[0])
                except Exception: continue
                name = (m.get("groupItemTitle") or m.get("question") or "").strip()
                rows.append({"name": name[:60], "p": round(yes * 100, 1)})
            rows.sort(key=lambda r: -r["p"])
            if rows: out["events"].append({"slug": slug, "label": label, "group": group, "title": ev.get("title"), "volume": round(float(ev.get("volume") or 0)), "url": f"https://polymarket.com/event/{slug}", "top": rows[:5]})
            time.sleep(0.3)
        except Exception as e: print("odds failed", slug, str(e)[:80])
    if out["events"]: json.dump(out, open(OUT, "w")); print("odds:", [(e["label"], e["top"][0]["name"], e["top"][0]["p"]) for e in out["events"]])
    else: print("odds: nothing fetched; last file kept")
if __name__ == "__main__": main()
