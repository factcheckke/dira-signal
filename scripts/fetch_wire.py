"""Builds wire.json: the latest headlines from named sources, linked to the original.

Headlines only. We never copy or rewrite another outlet's story; every item is
labelled "Reported by <source>" and links out. A feed that fails is skipped and
the previous items for it are kept, so one broken source never empties the wire.

Every headline is also kept for good in archive/YYYY-MM.json (from ARCHIVE_FROM
onwards), so readers can search past news. Run with --backfill once to page back
through each feed's history (WordPress-style ?paged=N) to fill in older items.
"""
import json, sys, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS = json.loads((ROOT / "scripts" / "feeds.json").read_text())
OUT = ROOT / "wire.json"
PER_FEED, MAX_ITEMS = 15, 150
ARCHIVE = ROOT / "archive"
ARCHIVE_FROM = "2026-10-01"
BACKFILL_PAGES = 40
UA = "Mozilla/5.0 (compatible; DiraSignalWire/1.0)"

def when(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")

def local(tag):
    return tag.rsplit("}", 1)[-1]

def parse(xml):
    root = ET.fromstring(xml)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {local(c.tag): c for c in el}
        title = (f.get("title").text or "").strip() if f.get("title") is not None else ""
        link = ""
        if f.get("link") is not None:
            link = (f["link"].text or f["link"].get("href") or "").strip()
        date = None
        for k in ("pubDate", "published", "updated", "date"):
            if f.get(k) is not None:
                date = when(f[k].text)
                if date:
                    break
        if title and link.startswith("http"):
            items.append({"title": " ".join(title.split()), "url": link, "at": date})
    return items

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return parse(r.read())

def page_url(url, n):
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parts.query) + [("paged", str(n))]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))

def backfill(feed, first):
    """Pages back through a feed until items are older than ARCHIVE_FROM.
    Feeds that ignore ?paged= return the same page again, which stops the loop."""
    out, seen = [], {it["url"] for it in first}
    for n in range(2, BACKFILL_PAGES + 1):
        try:
            got = fetch(page_url(feed["url"], n))
        except Exception:
            break
        fresh = [it for it in got if it["url"] not in seen]
        if not fresh:
            break
        for it in fresh:
            seen.add(it["url"])
        out += fresh
        dated = [it["at"] for it in fresh if it["at"]]
        if dated and min(dated) < ARCHIVE_FROM:
            break
    return out

def update_archive(items, now):
    ARCHIVE.mkdir(exist_ok=True)
    months = {}
    for it in items:
        day = (it.get("at") or it.get("seen") or now)[:10]
        if day < ARCHIVE_FROM:
            continue
        months.setdefault(day[:7], []).append(it)
    added = 0
    for month, new in months.items():
        path = ARCHIVE / f"{month}.json"
        try:
            have = json.loads(path.read_text()).get("items", [])
        except (OSError, ValueError, AttributeError):
            have = []
        urls = {it["url"] for it in have}
        for it in new:
            if it["url"] not in urls:
                urls.add(it["url"])
                have.append(it)
                added += 1
        have.sort(key=lambda x: x.get("at") or x.get("seen") or "", reverse=True)
        path.write_text(json.dumps({"month": month, "items": have}, indent=0, ensure_ascii=False))
    index = []
    for path in sorted(ARCHIVE.glob("????-??.json"), reverse=True):
        try:
            count = len(json.loads(path.read_text()).get("items", []))
        except (OSError, ValueError, AttributeError):
            count = 0
        index.append({"month": path.stem, "count": count})
    (ARCHIVE / "index.json").write_text(json.dumps({"updated": now, "from": ARCHIVE_FROM, "months": index}, indent=1))
    return added

def main():
    do_backfill = "--backfill" in sys.argv
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = {}
    try:
        for it in json.loads(OUT.read_text()).get("items", []):
            old.setdefault(it["source"], []).append(it)
    except (OSError, ValueError, AttributeError, KeyError):
        pass  # missing, empty or hand-edited wire.json: start fresh
    items, archive_items, report = [], [], []
    for feed in FEEDS:
        try:
            got = fetch(feed["url"])
            if do_backfill:
                got += backfill(feed, got)
            for it in got:
                it.update(source=feed["name"], tier=feed["tier"], geo=feed["geo"], seen=now)
            archive_items += got
            items += got[:PER_FEED]
            report.append(f"ok   {feed['name']}: {len(got)}")
        except Exception as e:
            items += old.get(feed["name"], [])
            report.append(f"fail {feed['name']}: {type(e).__name__}")
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: x.get("at") or "", reverse=True):
        if it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    OUT.write_text(json.dumps({"updated": now, "items": unique[:MAX_ITEMS]}, indent=1, ensure_ascii=False))
    print("\n".join(report))
    print(f"wire.json: {len(unique[:MAX_ITEMS])} items")
    print(f"archive: {update_archive(archive_items, now)} new items")

if __name__ == "__main__":
    sys.exit(main())
