"""International News Hub, version 1.1 (2026-09-11).
Pulls each country's outlets by RSS. Publishes, per story: the headline (translated), a one- or two-sentence SUMMARY IN OUR OWN WORDS
written by Claude from the feed's headline and excerpt, the outlet's name, and a link to the original. The feed excerpt itself is never
published (his ruling 9/11 16:17: rewrite, do not excerpt). Summaries are cached per story (summaries.json) so each story is written once.
Run hourly (hourly.sh under launchd) or by hand: python3 build.py [--countries US,FR] [--no-translate]."""
import feedparser, json, os, re, sys, time, hashlib, html, datetime, concurrent.futures
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site"); DATA = os.path.join(SITE, "data"); CACHE = os.path.join(ROOT, "summaries.json")
LANGS = {"en": "English", "es": "Español", "fr": "Français", "pt": "Português", "de": "Deutsch", "it": "Italiano", "ru": "Русский",
         "ar": "العربية", "hi": "हिन्दी", "zh": "中文", "ja": "日本語", "ko": "한국어"}
PER_COUNTRY = 24          # stories kept per country per build
EXCERPT_CHARS = 600       # how much of the feed excerpt the model may read as input; none of it is published
MODEL = "claude-haiku-4-5-20251001"
UA = {"User-Agent": "Mozilla/5.0 (compatible; InternationalNewsHub/1.1; +https://internationalnewshub.com)"}

class _Strip(HTMLParser):
    def __init__(self): super().__init__(); self.out = []
    def handle_data(self, d): self.out.append(d)
def strip_html(s):
    p = _Strip(); p.feed(s or ""); t = html.unescape(" ".join(p.out))
    return re.sub(r"\s+", " ", t).strip()

def key(title, excerpt): return hashlib.sha1((title + "|" + excerpt).encode()).hexdigest()[:16]

def fetch_feed(outlet, url, lang, country):
    """One feed -> list of stories. Failures return [] and are logged; a dead feed never stops the build."""
    try:
        d = feedparser.parse(url, request_headers=UA)
        out = []
        for e in d.entries[:40]:
            title = strip_html(e.get("title", ""))
            if not title or len(title) < 8: continue
            excerpt = strip_html(e.get("summary") or e.get("description") or "")
            if excerpt.lower().startswith(title.lower()): excerpt = excerpt[len(title):].lstrip(" .:-–")
            excerpt = excerpt[:EXCERPT_CHARS]
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = int(time.mktime(ts)) if ts else None
            link = e.get("link") or ""
            if not link: continue
            out.append({"id": key(title, excerpt), "title": title, "excerpt": excerpt, "link": link, "outlet": outlet,
                        "lang": lang, "country": country, "time": when})
        if not out: log(f"empty feed {country} {outlet} {url} {d.get('bozo_exception', '')}")
        return out
    except Exception as ex:
        log(f"feed failed {country} {outlet}: {str(ex)[:100]}"); return []

def log(*a): print(datetime.datetime.utcnow().strftime("%H:%M:%S"), *a, flush=True)

def dedupe(stories):
    seen_links, seen_titles, out = set(), set(), []
    for s in sorted(stories, key=lambda s: -(s["time"] or 0)):
        t = re.sub(r"[^\w]+", " ", s["title"].lower()).strip()
        if s["link"] in seen_links or t in seen_titles: continue
        seen_links.add(s["link"]); seen_titles.add(t); out.append(s)
    return out

def write_batch(client, items, targets):
    """items: list of {id,title,excerpt,lang}; returns {id: {lang: {title, summary}}}. One call per batch of stories.
    title = the headline translated (or as-is in its own language); summary = one or two sentences in our own words, in that language."""
    src = "\n\n".join(f"[{i['id']}] (source language: {LANGS.get(i['lang'], i['lang'])}, outlet: {i['outlet']})\nHEADLINE: {i['title']}\nEXCERPT: {i['excerpt'] or '(none)'}" for i in items)
    prompt = (f"You write a neutral news digest. For EACH item below, produce, in EACH of these languages: {', '.join(targets)} (language codes):\n"
              f"- \"title\": the headline faithfully translated into that language (in the source language, keep it exactly as given). Keep names and numbers exact.\n"
              f"- \"summary\": one or two plain sentences IN YOUR OWN WORDS, in that language, stating what the outlet reports. Use only facts present in the headline and excerpt; "
              f"add nothing, speculate about nothing, quote nothing verbatim, and do not copy the excerpt's sentences. Neutral tone, no opinion, no 'the article says'. "
              f"If the excerpt is (none), summarize the headline alone in one sentence. Keep each summary under 45 words.\n"
              f"Return ONLY valid JSON (escape any double quotes inside strings as \\\"): {{\"<id>\": {{\"<lang>\": {{\"title\": \"...\", \"summary\": \"...\"}}, ...}}, ...}}\n\n{src}")
    r = client.messages.create(model=MODEL, max_tokens=12000, messages=[{"role": "user", "content": prompt}])
    txt = r.content[0].text; m = re.search(r"\{.*\}", txt, re.S)
    try: return (json.loads(m.group(0), strict=False) if m else {}), r.usage.input_tokens, r.usage.output_tokens
    except json.JSONDecodeError:
        if len(items) == 1: raise
        out = {}; a = b = 0                                       # a batch that came back malformed: retry story by story
        for it in items:
            try: res, x, y = write_batch(client, [it], targets); out.update(res); a += x; b += y
            except Exception as e_: log(f"summary failed {it['id']}: {str(e_)[:80]}")
        return out, r.usage.input_tokens + a, r.usage.output_tokens + b

def main():
    args = sys.argv[1:]; only = None; do_write = "--no-translate" not in args
    if "--countries" in args: only = args[args.index("--countries") + 1].split(",")
    feeds = json.load(open(os.path.join(ROOT, "feeds.json")))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    os.makedirs(DATA, exist_ok=True)
    client = None
    if do_write:
        import anthropic
        key_ = os.environ.get("ANTHROPIC_API_KEY") or json.load(open(os.path.expanduser("~/Desktop/Nicky Bot/config.json")))["anthropic"]["api_key"]
        client = anthropic.Anthropic(api_key=key_)
    tin = tout = 0; built = int(time.time()); index = {"updated": built, "languages": LANGS, "countries": {}}
    for cc, c in feeds.items():
        if only and cc not in only: continue
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            lists = list(ex.map(lambda f: fetch_feed(f["outlet"], f["url"], f.get("lang", c["lang"]), cc), c["feeds"]))
        stories = dedupe([s for l in lists for s in l])[:PER_COUNTRY]
        # every story gets a summary in every site language, its own included; cached by story id
        todo = [s for s in stories if any(l not in cache.get(s["id"], {}) for l in LANGS)]
        if do_write and todo:
            batches = [todo[i:i + 3] for i in range(0, len(todo), 3)]
            def run(batch):
                try: return write_batch(client, batch, [l for l in LANGS])
                except Exception as e_: log(f"summary failed {cc}: {str(e_)[:120]}"); return {}, 0, 0
            with concurrent.futures.ThreadPoolExecutor(6) as ex:
                for batch, (res, a, b) in zip(batches, ex.map(run, batches)):
                    tin += a; tout += b
                    for s in batch:
                        got = res.get(s["id"], {})
                        cache.setdefault(s["id"], {}).update({l: v for l, v in got.items() if l in LANGS and isinstance(v, dict) and v.get("title") and v.get("summary")})
            json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
        published = []
        for s in stories:
            tr = cache.get(s["id"], {})
            if not tr: continue                                    # no summary written yet: not published (never fall back to the excerpt)
            published.append({"id": s["id"], "title": s["title"], "link": s["link"], "outlet": s["outlet"], "lang": s["lang"],
                              "time": s["time"] or built, "dated": s["time"] is not None, "tr": tr})
        json.dump({"country": cc, "name": c["name"], "lang": c["lang"], "updated": built, "stories": published},
                  open(os.path.join(DATA, f"{cc}.json"), "w"), ensure_ascii=False)
        index["countries"][cc] = {"name": c["name"], "lang": c["lang"], "flag": c.get("flag", ""), "n": len(published),
                                  "outlets": sorted({s["outlet"] for s in published})}
        log(f"{cc} {c['name']}: {len(published)} stories published of {len(stories)} fetched, {len(todo)} newly summarized")
    if only:   # keep the other countries in the index
        old = json.load(open(os.path.join(DATA, "index.json"))) if os.path.exists(os.path.join(DATA, "index.json")) else {"countries": {}}
        for cc, v in old.get("countries", {}).items(): index["countries"].setdefault(cc, v)
    json.dump(index, open(os.path.join(DATA, "index.json"), "w"), ensure_ascii=False)
    live = {s["id"] for cc in index["countries"] if os.path.exists(os.path.join(DATA, f"{cc}.json")) for s in json.load(open(os.path.join(DATA, f"{cc}.json")))["stories"]}
    if len(cache) > 5000:                                          # keep the cache to what the site still shows
        cache = {k: v for k, v in cache.items() if k in live}; json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    log(f"done; tokens in {tin} out {tout} (about ${tin/1e6*1 + tout/1e6*5:.2f} at Haiku prices)")

if __name__ == "__main__": main()
