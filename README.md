# International News Hub

One country's news at a time, from its own press, in your language.

- `feeds.json` — 20 countries, 4 to 6 outlets each (RSS). Verified 2026-09-11.
- `build.py` — pulls the feeds, keeps headline + first paragraph + link, deduplicates, translates new stories once (cached in `translations.json`) into 12 languages with Claude, writes `site/data/*.json`. Runs hourly on the operator's machine; the API key never leaves it.
- `site/index.html` — the static page: country picker, language switch, "machine translated" tag, link to the original.
- `.github/workflows/build.yml` — publishes `site/` to GitHub Pages on every push.

Nothing is republished in full; every story links to its source.
