"""International News Hub, version 2 (2026-09-11).
Countries and their metadata come from countries.json; outlets from feeds.json (general outlets plus one business outlet per country).
For each country: pull the feeds, keep the 12 most-covered recent stories, and write ONE- OR TWO-SENTENCE SUMMARIES IN OUR OWN WORDS
with Claude (cached in summaries.json). Financial figures come from finance.json (finance.py). Output is static HTML:
site/index.html (home: markets ribbon, regions, country tiles) and site/c/<CC>/index.html (country page: hero with the map silhouette,
five instruments, stories, markets column). Languages: English for now (LANGS). Stories per country: PER_COUNTRY.
Run: python3 build.py [--countries US,FR] [--no-summaries]. Nothing of an outlet's text is published beyond its headline."""
import feedparser, json, os, re, sys, time, calendar, hashlib, html, datetime, concurrent.futures, random
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__)); SITE = os.path.join(ROOT, "site"); DATA = os.path.join(SITE, "data")
CACHE = os.path.join(ROOT, "summaries.json"); MAPS = os.path.join(SITE, "maps")
LANGS = {"en": "English"}
PER_COUNTRY = 12; EXCERPT_CHARS = 600; MODEL = "claude-haiku-4-5-20251001"
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/2.0; +https://internationalnewshub.com)"}
REGIONS = ["Americas", "Europe", "Middle East", "Asia-Pacific"]
SITE_URL = "https://internationalnewshub.com"

class _Strip(HTMLParser):
    def __init__(self): super().__init__(); self.out = []
    def handle_data(self, d): self.out.append(d)
def strip_html(s):
    p = _Strip(); p.feed(s or ""); t = html.unescape(" ".join(p.out)); return re.sub(r"\s+", " ", t).strip()
def esc(s): return html.escape(str(s if s is not None else ""), quote=True)
def key(title, excerpt): return hashlib.sha1((title + "|" + excerpt).encode()).hexdigest()[:16]
def log(*a): print(datetime.datetime.utcnow().strftime("%H:%M:%S"), *a, flush=True)

def fetch_feed(outlet, url, lang, country, kind):
    try:
        d = feedparser.parse(url, request_headers=UA); out = []
        for e in d.entries[:40]:
            title = strip_html(e.get("title", ""))
            if not title or len(title) < 8: continue
            excerpt = strip_html(e.get("summary") or e.get("description") or "")
            if excerpt.lower().startswith(title.lower()): excerpt = excerpt[len(title):].lstrip(" .:-–")
            ts = e.get("published_parsed") or e.get("updated_parsed"); link = e.get("link") or ""
            if not link: continue
            out.append({"id": key(title, excerpt[:EXCERPT_CHARS]), "title": title, "excerpt": excerpt[:EXCERPT_CHARS], "link": link, "outlet": outlet,
                        "lang": lang, "country": country, "kind": kind, "time": int(calendar.timegm(ts)) if ts else None})
        if not out: log(f"empty feed {country} {outlet} {url} {d.get('bozo_exception', '')}")
        return out
    except Exception as ex: log(f"feed failed {country} {outlet}: {str(ex)[:100]}"); return []

WORDS = re.compile(r"[a-zà-ÿа-яα-ω؀-ۿ぀-ヿ一-鿿가-힯0-9]+", re.I)
def pick(stories, n):
    """Newest-first dedupe, then rank by how many outlets share the story's key words (coverage) with recency as the tiebreak; keep n."""
    seen, out = set(), []
    for s in sorted(stories, key=lambda s: -(s["time"] or 0)):
        t = re.sub(r"[^\w]+", " ", s["title"].lower()).strip()
        if s["link"] in seen or t in seen: continue
        seen.add(s["link"]); seen.add(t); out.append(s)
    now = time.time(); recent = [s for s in out if s["time"] is None or now - s["time"] < 36 * 3600] or out
    bags = [(s, set(w for w in WORDS.findall(s["title"].lower()) if len(w) > 3)) for s in recent]
    def score(i):
        s, bag = bags[i]; cov = sum(1 for j, (o, ob) in enumerate(bags) if j != i and o["outlet"] != s["outlet"] and len(bag & ob) >= 3)
        age_h = (now - s["time"]) / 3600 if s["time"] else 12
        return cov * 10 - min(age_h, 36) / 6
    ranked = sorted(range(len(bags)), key=lambda i: -score(i))
    chosen = [bags[i][0] for i in ranked[:n]]
    return sorted(chosen, key=lambda s: -(s["time"] or 0))

def write_batch(client, items, targets):
    src = "\n\n".join(f"[{i['id']}] (source language: {i['lang']}, outlet: {i['outlet']})\nHEADLINE: {i['title']}\nEXCERPT: {i['excerpt'] or '(none)'}" for i in items)
    prompt = (f"You write a neutral news digest. For EACH item below, produce, in EACH of these languages: {', '.join(targets)} (language codes):\n"
              f"- \"title\": the headline faithfully translated into that language (if already in that language, keep it exactly as given). Keep names and numbers exact.\n"
              f"- \"summary\": one or two plain sentences IN YOUR OWN WORDS, in that language, stating what the outlet reports. Use only facts present in the headline and excerpt; "
              f"add nothing, speculate about nothing, quote nothing verbatim, and do not copy the excerpt's sentences. Neutral tone, no opinion, no 'the article says'. "
              f"If the excerpt is (none), summarize the headline alone in one sentence. Keep each summary under 45 words.\n"
              f"Return ONLY valid JSON (escape any double quotes inside strings as \\\"): {{\"<id>\": {{\"<lang>\": {{\"title\": \"...\", \"summary\": \"...\"}}, ...}}, ...}}\n\n{src}")
    r = client.messages.create(model=MODEL, max_tokens=6000, messages=[{"role": "user", "content": prompt}])
    txt = r.content[0].text; m = re.search(r"\{.*\}", txt, re.S)
    try: return (json.loads(m.group(0), strict=False) if m else {}), r.usage.input_tokens, r.usage.output_tokens
    except json.JSONDecodeError:
        if len(items) == 1: raise
        out = {}; a = b = 0
        for it in items:
            try: res, x, y = write_batch(client, [it], targets); out.update(res); a += x; b += y
            except Exception as e_: log(f"summary failed {it['id']}: {str(e_)[:80]}")
        return out, r.usage.input_tokens + a, r.usage.output_tokens + b

# ---------- rendering ----------
def rel(t, now):
    if not t: return ""
    s = now - t
    return f"{max(1, int(s // 60))} min ago" if s < 3600 else f"{int(s // 3600)} h ago" if s < 86400 else f"{int(s // 86400)} d ago"
def fmt_num(x, digits=2):
    if x is None: return "—"
    if abs(x) >= 1000: return f"{x:,.0f}"
    return f"{x:,.{digits}f}"
def pct(x, sign=True):
    if x is None: return "—"
    return f"{x:+.1f}%" if sign else f"{x:.1f}%"
def cls(x): return "up" if (x or 0) > 0 else "down" if (x or 0) < 0 else ""
def map_svg(cc, depth=0):
    """A div masked with the country's silhouette (the SVG is fetched once and cached by the browser, not inlined)."""
    return f'<div class="mask" style="--m:url({"../" * depth}maps/{cc}.svg)"></div>' if os.path.exists(os.path.join(MAPS, f"{cc}.svg")) else ""

def head(title, desc, depth=0):
    base = "../" * depth
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">'
            f'<link rel="stylesheet" href="{base}style.css"></head><body><div class="wrap">'
            f'<header class="top"><a class="brand" href="{base}./">International News Hub<small>one country at a time</small></a>'
            f'<nav class="nav"><a href="{base}./">Countries</a><a href="{base}about.html">About</a></nav></header>')
def foot(depth=0):
    base = "../" * depth
    return (f'<footer>Each item is a short summary written by AI from the outlet\'s own headline and description; the source and a link to the original are on every item. '
            f'Summaries can be wrong; read the source for anything that matters. Financial figures are daily, from public sources named on each page. '
            f'<a href="{base}about.html">How this works</a></footer></div></body></html>')

def ribbon(countries, fin):
    parts = []
    for cc, c in countries.items():
        ix = fin.get(cc, {}).get("index")
        if not ix: continue
        parts.append(f'<span><a href="c/{cc}/">{c["flag"]} {esc(c["index"]["name"])}</a><b>{fmt_num(ix["price"])}</b> <b class="{cls(ix.get("change_pct"))}">{pct(ix.get("change_pct"))}</b></span>')
    return '<div class="ribbon">' + "".join(parts) + '</div>'

def home(countries, pages, fin, now):
    h = head("International News Hub", "One country at a time: its own press, summarized, with the day's markets.", 0)
    h += ribbon(countries, fin)
    h += ('<section class="hero"><div><h1>The world, <em>one country</em> at a time.</h1>'
          '<p>Each country’s news as its own press reports it, summarized in plain English every few hours, with the currency, the market, and the rate that matter there today.</p></div>'
          f'<div class="globe">{map_svg("WORLD")}</div></section>')
    h += '<div id="regions">'
    for region in REGIONS:
        ccs = [cc for cc, c in countries.items() if c["region"] == region]
        if not ccs: continue
        h += f'<section class="region" data-region="{esc(region)}"><h2>{esc(region)}<small>{len(ccs)} countries</small></h2><div class="tiles">'
        for cc in ccs:
            c = countries[cc]; ix = fin.get(cc, {}).get("index"); n = pages.get(cc, 0)
            meta = (f'<b>{esc(c["index"]["name"])}</b> <span class="{cls(ix.get("change_pct"))}">{pct(ix.get("change_pct"))}</span> · ' if ix else "") + f'{n} stories'
            h += (f'<a class="tile" href="c/{cc}/" style="--tint:{c["colors"][0]}"><div class="map">{map_svg(cc)}</div>'
                  f'<div class="flag">{c["flag"]}</div><h3>{esc(c["name"])}</h3><div class="meta">{meta}</div></a>')
        h += '</div></section>'
    h += '</div>'
    h += ('<script>(function(){var r=document.getElementById("regions");var s=Array.from(r.children);'  # rotate which region leads, per visit
          'var k=Math.floor(Math.random()*s.length);s.slice(k).concat(s.slice(0,k)).forEach(function(e){r.appendChild(e)})})();</script>')
    return h + foot(0)

def country_page(cc, c, stories, f, now):
    c1, c2 = (c["colors"] + [c["colors"][0]])[:2]
    h = head(f'{c["name"]} · International News Hub', f'{c["name"]}: its own press, summarized, with today\'s {c["currency"]}, {c["index"]["name"]}, rate, inflation and growth.', 2)
    h += (f'<section class="chero" style="--c1:{c1};--c2:{c2}"><div class="map">{map_svg(cc)}</div>'
          f'<div class="eyebrow">{esc(c["region"])} · {esc(c["capital"])}</div><h1><span class="flag">{c["flag"]}</span>{esc(c["name"])}</h1>'
          f'<div class="sub">{len(stories)} stories from {len({s["outlet"] for s in stories})} of the country’s own outlets · updated {rel(now - 60, now)}</div></section>')
    fx, ix, pr, inf, gr = f.get("fx"), f.get("index"), f.get("policy_rate"), f.get("inflation"), f.get("gdp_growth")
    fxv = ("1 USD = " + fmt_num(fx["per_usd"], 3 if fx["per_usd"] < 10 else 1) + " " + c["currency"]) if fx and c["currency"] != "USD" else ("US dollar" if c["currency"] == "USD" else "—")
    fxd = ""
    if fx and fx.get("prev") and c["currency"] != "USD":
        ch = (fx["per_usd"] / fx["prev"] - 1) * 100; fxd = f'<span class="{cls(-ch)}">{pct(-ch)}</span> vs USD, 1 day'
    elif fx: fxd = esc(fx.get("date", ""))
    inst = [("Currency", fxv, fxd),
            (c["index"]["name"], fmt_num(ix["price"]) if ix else "—", (f'<span class="{cls(ix.get("change_pct"))}">{pct(ix.get("change_pct"))}</span> on the day' if ix else "")),
            ("Policy rate", pct(pr["rate"], sign=False) if pr else "—", (f'{esc(pr.get("last_move", "").capitalize())} · {esc(pr["decided"])}' if pr and pr.get("decided") else "no verified figure")),
            ("Inflation", pct(inf["value"], sign=False) if inf else "—", f'{inf["year"]}, World Bank' if inf else ""),
            ("GDP growth", pct(gr["value"], sign=True) if gr else "—", f'{gr["year"]}, World Bank' if gr else "")]
    h += '<div class="strip">' + "".join(f'<div class="inst"><div class="k">{esc(k)}</div><div class="v">{v}</div><div class="d">{d}</div></div>' for k, v, d in inst) + '</div>'
    gen = [s for s in stories if s["kind"] != "business"]; biz = [s for s in stories if s["kind"] == "business"]
    def card(s):
        t = s["tr"].get("en") or {}
        return (f'<article class="story"><h3><a href="{esc(s["link"])}" target="_blank" rel="noopener">{esc(t.get("title") or s["title"])}</a></h3>'
                + (f'<p>{esc(t["summary"])}</p>' if t.get("summary") else "")
                + f'<div class="src">Source: {esc(s["outlet"])} · <a href="{esc(s["link"])}" target="_blank" rel="noopener">read the original</a>' + (f' · {rel(s["time"], now)}' if s.get("dated") else "") + '</div></article>')
    h += '<div class="cols"><section class="stories"><h2>Today<small>from the national press</small></h2>' + "".join(card(s) for s in gen) + '</section>'
    h += '<aside class="side"><section class="stories"><h2>Markets<small>business press</small></h2>' + ("".join(card(s) for s in biz) or '<p class="src">No business-desk stories in this update.</p>') + '</section></aside></div>'
    return h + foot(2)

# ---------- main ----------
def main():
    args = sys.argv[1:]; only = None; do_write = "--no-summaries" not in args
    if "--countries" in args: only = args[args.index("--countries") + 1].split(",")
    countries = json.load(open(os.path.join(ROOT, "countries.json")))
    feeds = json.load(open(os.path.join(ROOT, "feeds.json")))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    fin = json.load(open(os.path.join(DATA, "finance.json"))).get("countries", {}) if os.path.exists(os.path.join(DATA, "finance.json")) else {}
    os.makedirs(DATA, exist_ok=True); client = None
    if do_write:
        import anthropic
        key_ = os.environ.get("ANTHROPIC_API_KEY") or json.load(open(os.path.expanduser("~/Desktop/Nicky Bot/config.json")))["anthropic"]["api_key"]
        client = anthropic.Anthropic(api_key=key_)
    tin = tout = 0; now = int(time.time()); pages = {}
    for cc, c in countries.items():
        if only and cc not in only: continue
        fl = feeds.get(cc, {}).get("feeds", [])
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            lists = list(ex.map(lambda f: fetch_feed(f["outlet"], f["url"], f.get("lang", c["lang"]), cc, f.get("kind", "general")), fl))
        allst = [s for l in lists for s in l]
        gen = pick([s for s in allst if s["kind"] != "business"], PER_COUNTRY); biz = pick([s for s in allst if s["kind"] == "business"], 5)
        stories = gen + biz
        todo = [s for s in stories if any(l not in cache.get(s["id"], {}) for l in LANGS)]
        if do_write and todo:
            batches = [todo[i:i + 4] for i in range(0, len(todo), 4)]
            def run(batch):
                try: return write_batch(client, batch, list(LANGS))
                except Exception as e_: log(f"summary failed {cc}: {str(e_)[:120]}"); return {}, 0, 0
            with concurrent.futures.ThreadPoolExecutor(4) as ex:
                for batch, (res, a, b) in zip(batches, ex.map(run, batches)):
                    tin += a; tout += b
                    for s in batch:
                        got = res.get(s["id"], {})
                        cache.setdefault(s["id"], {}).update({l: v for l, v in got.items() if l in LANGS and isinstance(v, dict) and v.get("title") and v.get("summary")})
            json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
        published = []
        for s in stories:
            tr = cache.get(s["id"], {})
            if not tr: continue
            published.append({"id": s["id"], "title": s["title"], "link": s["link"], "outlet": s["outlet"], "lang": s["lang"], "kind": s["kind"],
                              "time": s["time"] or now, "dated": s["time"] is not None, "tr": tr})
        json.dump({"country": cc, "name": c["name"], "updated": now, "stories": published}, open(os.path.join(DATA, f"{cc}.json"), "w"), ensure_ascii=False)
        os.makedirs(os.path.join(SITE, "c", cc), exist_ok=True)
        open(os.path.join(SITE, "c", cc, "index.html"), "w").write(country_page(cc, c, published, fin.get(cc, {}), now))
        pages[cc] = len(published)
        log(f"{cc} {c['name']}: {len(published)} published ({len(biz)} business) of {len(allst)} fetched from {len(fl)} feeds, {len(todo)} newly summarized")
    if only:
        for cc in countries:
            if cc not in pages and os.path.exists(os.path.join(DATA, f"{cc}.json")): pages[cc] = len(json.load(open(os.path.join(DATA, f"{cc}.json")))["stories"])
    open(os.path.join(SITE, "index.html"), "w").write(home(countries, pages, fin, now))
    json.dump({"updated": now, "languages": LANGS, "countries": {cc: {"name": c["name"], "region": c["region"], "flag": c["flag"], "n": pages.get(cc, 0)} for cc, c in countries.items()}},
              open(os.path.join(DATA, "index.json"), "w"), ensure_ascii=False)
    live = {s["id"] for cc in countries if os.path.exists(os.path.join(DATA, f"{cc}.json")) for s in json.load(open(os.path.join(DATA, f"{cc}.json")))["stories"]}
    if len(cache) > 4000: cache = {k: v for k, v in cache.items() if k in live}; json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    log(f"done; tokens in {tin} out {tout} (about ${tin/1e6*1 + tout/1e6*5:.2f} at Haiku prices)")

if __name__ == "__main__": main()
