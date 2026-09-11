#!/bin/bash
# International News Hub: hourly build on John's Mac, then push the generated data so GitHub Pages republishes.
# Runs under launchd (com.inh.build) from ~/Sites/international-news-hub (outside the Desktop, which macOS gates). One at a time via a lock directory.
cd "$(dirname "$0")" || exit 1
if ! mkdir .build.lock 2>/dev/null; then
  if [ -n "$(find .build.lock -mmin +90 2>/dev/null)" ]; then rmdir .build.lock; mkdir .build.lock; else echo "$(date '+%F %T') skipped: build already running"; exit 0; fi
fi
trap 'rmdir .build.lock 2>/dev/null' EXIT
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
echo "$(date '+%F %T') build start"
git pull -q --rebase origin main 2>/dev/null || echo "$(date '+%F %T') pull failed (continuing)"
/usr/bin/python3 build.py || echo "$(date '+%F %T') build.py exited $?"
git add -A site/data summaries.json >/dev/null 2>&1
if git commit -qm "hourly build $(date -u '+%Y-%m-%dT%H:%MZ')" 2>/dev/null; then
  git push -q origin main && echo "$(date '+%F %T') pushed" || echo "$(date '+%F %T') push failed"
else
  echo "$(date '+%F %T') nothing new"
fi
