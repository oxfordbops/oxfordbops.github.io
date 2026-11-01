#!/usr/bin/env python3
"""Deploy-time additions for search engines, applied to the published copy only (the committed page is untouched).

    python3 scripts/seo.py docs

1. Prerenders the upcoming listings as plain HTML inside #list, so crawlers that do not run JavaScript still see
   "<College> <title> on <day>" text; the page's script replaces it on load.
2. Writes sitemap.xml (with the data's last update) and robots.txt pointing to it.
Per-event schema.org markup is deliberately absent: college events are for members, and Google's event results are
for events the public can attend.
"""
import datetime as dt, html, json, pathlib, sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
LABEL = {"bop": "Bop", "formal": "Formal", "ball": "Ball", "other": "Event"}
MARK = '<p class="status" id="loading">Loading…</p>'


def prerender(events, city, now, limit=60):
    rows, today = [], now.astimezone(LONDON).date()
    for e in sorted(events, key=lambda e: e["starts_at"]):
        start = dt.datetime.fromisoformat(e["starts_at"].replace("Z", "+00:00")).astimezone(LONDON)
        horizon = 400 if e.get("kind") == "ball" else 14
        if not today <= start.date() <= today + dt.timedelta(days=horizon):
            continue
        where = e.get("college") or city
        rows.append(f"<li>{start:%a %d %b %H:%M}: {html.escape(e['title'])}, {html.escape(where)} ({LABEL.get(e.get('kind'), 'Bop')})</li>")
        if len(rows) >= limit:
            break
    if not rows:
        return ""
    return f'<div id="prerender"><h2>{html.escape(city)} bops, formals and college events coming up</h2><ul>' + "".join(rows) + "</ul></div>"


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
    city = json.loads((ROOT / "city.json").read_text())
    data = json.loads((out / "events.json").read_text())
    page = (out / "index.html").read_text()
    if MARK not in page:
        sys.exit("seo.py: the loading placeholder is missing from index.html")
    now = dt.datetime.now(dt.timezone.utc)
    page = page.replace(MARK, MARK + prerender(data.get("bops", []), city["name"], now), 1)
    (out / "index.html").write_text(page)
    site = city["site"].rstrip("/") + "/"
    lastmod = (data.get("generated") or now.isoformat())[:10]
    (out / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     f'  <url><loc>{site}</loc><lastmod>{lastmod}</lastmod><changefreq>daily</changefreq></url>\n</urlset>\n')
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site}sitemap.xml\n")
    print(f"seo: prerendered {page.count('<li>')} listings, sitemap lastmod {lastmod}")


if __name__ == "__main__":
    main()
