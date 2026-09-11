"""International News Hub, version one (2026-09-11).
Pulls each country's outlets by RSS, keeps headline + first paragraph + link, deduplicates, translates new stories
into the site's languages with Claude (cached, so each story is translated once), and writes site/data/*.json
for the static page in site/index.html. Runs hourly (GitHub Actions) or by hand: python3 build.py [--countries US,FR] [--no-translate].
Nothing is republished in full: the summary is capped, and every story links to the original."""
import feedparser, json, os, re, sys, time, hashlib, html, datetime, concurrent.futures
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site"); DATA = os.path.join(SITE, "data"); CACHE = os.path.join(ROOT, "translations.json")
LANGS = {"en": "English", "es": "Español", "fr": "Français", "pt": "Português", "de": "Deutsch", "it": "Italiano", "ru": "Русский",
         "ar": "العربية", "hi": "हिन्दी", "zh": "中文", "ja": "日本語", "ko": "한국어"}
PER_COUNTRY = 24          # stories kept per country per build
SUMMARY_CHARS = 320       # first paragraph only, never the article
MODEL = "claude-haiku-4-5-20251001"
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/1.0; +https://internationalnewshub.com)"}

class _Strip(HTMLParser):
    def __init__(self): super().__init__(); self.out = []
    def handle_data(self, d): self.out.append(d)
def strip_html(s):
    p = _Strip(); p.feed(s or ""); t = html.unescape(" ".join(p.out))
    return re.sub(r"\s+", " ", t).strip()

def key(title, summary): return hashlib.sha1((title + "|" + summary).encode()).hexdigest()[:16]

def fetch_feed(outlet, url, lang, country):
    """One feed -> list of stories. Failures return [] and are logged; a dead feed never stops the build."""
    try:
        d = feedparser.parse(url, request_headers=UA)
        out = []
        for e in d.entries[:40]:
            title = strip_html(e.get("title", ""))
            if not title or len(title) < 8: continue
            summary = strip_html(e.get("summary") or e.get("description") or "")
            if summary.lower().startswith(title.lower()): summary = summary[len(title):].lstrip(" .:-–")
            summary = summary[:SUMMARY_CHARS].rsplit(" ", 1)[0] if len(summary) > SUMMARY_CHARS else summary
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = int(time.mktime(ts)) if ts else int(time.time())
            link = e.get("link") or ""
            if not link: continue
            out.append({"id": key(title, summary), "title": title, "summary": summary, "link": link, "outlet": outlet,
                        "lang": lang, "country": country, "time": when})
        if not out: log(f"empty feed {country} {outlet} {url} {d.get('bozo_exception', '')}")
        return out
    except Exception as ex:
        log(f"feed failed {country} {outlet}: {str(ex)[:100]}"); return []

def log(*a): print(datetime.datetime.utcnow().strftime("%H:%M:%S"), *a, flush=True)

def dedupe(stories):
    seen_links, seen_titles, out = set(), set(), []
    for s in sorted(stories, key=lambda s: -s["time"]):
        t = re.sub(r"[^\w]+", " ", s["title"].lower()).strip()
        if s["link"] in seen_links or t in seen_titles: continue
        seen_links.add(s["link"]); seen_titles.add(t); out.append(s)
    return out

def translate_batch(client, items, targets):
    """items: list of {id,title,summary,lang}; returns {id: {lang: {title, summary}}}. One call per batch of stories."""
    want = [l for l in targets]
    src = "\n\n".join(f"[{i['id']}] ({LANGS.get(i['lang'], i['lang'])})\nTITLE: {i['title']}\nSUMMARY: {i['summary'] or '(none)'}" for i in items)
    prompt = (f"Translate each news item below into these languages: {', '.join(want)} (language codes). Keep proper names, numbers, and meaning exact; "
              f"headline register for titles; plain register for summaries; no additions, no commentary. If SUMMARY is (none), return an empty string for it. "
              f"Return ONLY valid JSON (escape any double quotes inside strings as \\\"): {{\"<id>\": {{\"<lang>\": {{\"title\": \"...\", \"summary\": \"...\"}}, ...}}, ...}}\n\n{src}")
    r = client.messages.create(model=MODEL, max_tokens=12000, messages=[{"role": "user", "content": prompt}])
    txt = r.content[0].text; m = re.search(r"\{.*\}", txt, re.S)
    try: return (json.loads(m.group(0), strict=False) if m else {}), r.usage.input_tokens, r.usage.output_tokens
    except json.JSONDecodeError:
        if len(items) == 1: raise
        out = {}; a = b = 0                                       # a batch that came back malformed: retry story by story
        for it in items:
            try: res, x, y = translate_batch(client, [it], targets); out.update(res); a += x; b += y
            except Exception as e_: log(f"translate failed {it['id']}: {str(e_)[:80]}")
        return out, r.usage.input_tokens + a, r.usage.output_tokens + b

def main():
    args = sys.argv[1:]; only = None; do_translate = "--no-translate" not in args
    if "--countries" in args: only = args[args.index("--countries") + 1].split(",")
    feeds = json.load(open(os.path.join(ROOT, "feeds.json")))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    os.makedirs(DATA, exist_ok=True)
    client = None
    if do_translate:
        import anthropic
        key_ = os.environ.get("ANTHROPIC_API_KEY") or json.load(open(os.path.expanduser("~/Desktop/Nicky Bot/config.json")))["anthropic"]["api_key"]
        client = anthropic.Anthropic(api_key=key_)
    tin = tout = 0; index = {"updated": int(time.time()), "languages": LANGS, "countries": {}}
    for cc, c in feeds.items():
        if only and cc not in only: continue
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            lists = list(ex.map(lambda f: fetch_feed(f["outlet"], f["url"], f.get("lang", c["lang"]), cc), c["feeds"]))
        stories = dedupe([s for l in lists for s in l])[:PER_COUNTRY]
        # translations: every story into every site language it is not already in; cached by story id
        todo = [s for s in stories if any(l not in cache.get(s["id"], {}) and l != s["lang"] for l in LANGS)]
        if do_translate and todo:
            batches = [todo[i:i + 3] for i in range(0, len(todo), 3)]
            def run(batch):
                try: return translate_batch(client, batch, [l for l in LANGS])
                except Exception as e_: log(f"translate failed {cc}: {str(e_)[:120]}"); return {}, 0, 0
            with concurrent.futures.ThreadPoolExecutor(6) as ex:
                for batch, (res, a, b) in zip(batches, ex.map(run, batches)):
                    tin += a; tout += b
                    for s in batch:
                        got = res.get(s["id"], {})
                        cache.setdefault(s["id"], {}).update({l: v for l, v in got.items() if l in LANGS and isinstance(v, dict) and v.get("title")})
            json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
        for s in stories:
            s["tr"] = cache.get(s["id"], {}); s["tr"][s["lang"]] = {"title": s["title"], "summary": s["summary"]}
        json.dump({"country": cc, "name": c["name"], "lang": c["lang"], "updated": index["updated"], "stories": stories},
                  open(os.path.join(DATA, f"{cc}.json"), "w"), ensure_ascii=False)
        index["countries"][cc] = {"name": c["name"], "lang": c["lang"], "flag": c.get("flag", ""), "n": len(stories),
                                  "outlets": sorted({s["outlet"] for s in stories})}
        log(f"{cc} {c['name']}: {len(stories)} stories from {len(index['countries'][cc]['outlets'])} outlets, {len(todo)} newly translated")
    if only:   # keep the other countries in the index
        old = json.load(open(os.path.join(DATA, "index.json"))) if os.path.exists(os.path.join(DATA, "index.json")) else {"countries": {}}
        for cc, v in old.get("countries", {}).items(): index["countries"].setdefault(cc, v)
    json.dump(index, open(os.path.join(DATA, "index.json"), "w"), ensure_ascii=False)
    # prune the cache to stories seen in the last 3 days of builds (ids referenced now stay)
    live = {s["id"] for cc in index["countries"] if os.path.exists(os.path.join(DATA, f"{cc}.json")) for s in json.load(open(os.path.join(DATA, f"{cc}.json")))["stories"]}
    if len(cache) > 5000:
        cache = {k: v for k, v in cache.items() if k in live}; json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    log(f"done; translation tokens in {tin} out {tout} (about ${tin/1e6*1 + tout/1e6*5:.2f} at Haiku prices)")

if __name__ == "__main__": main()
