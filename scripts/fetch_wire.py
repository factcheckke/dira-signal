"""Builds wire.json: the latest headlines from named sources, linked to the original.

Headlines only. We never copy or rewrite another outlet's story; every item is
labelled "Reported by <source>" and links out. A feed that fails is skipped and
the previous items for it are kept, so one broken source never empties the wire.
"""
import json, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS = json.loads((ROOT / "scripts" / "feeds.json").read_text())
OUT = ROOT / "wire.json"
PER_FEED, MAX_ITEMS = 8, 60
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
    return items[:PER_FEED]

def main():
    old = {}
    if OUT.exists():
        for it in json.loads(OUT.read_text()).get("items", []):
            old.setdefault(it["source"], []).append(it)
    items, report = [], []
    for feed in FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                got = parse(r.read())
            for it in got:
                it.update(source=feed["name"], tier=feed["tier"], geo=feed["geo"])
            items += got
            report.append(f"ok   {feed['name']}: {len(got)}")
        except Exception as e:
            items += old.get(feed["name"], [])
            report.append(f"fail {feed['name']}: {type(e).__name__}")
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: x.get("at") or "", reverse=True):
        if it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.write_text(json.dumps({"updated": now, "items": unique[:MAX_ITEMS]}, indent=1, ensure_ascii=False))
    print("\n".join(report))
    print(f"wire.json: {len(unique[:MAX_ITEMS])} items")

if __name__ == "__main__":
    sys.exit(main())
