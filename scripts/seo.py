#!/usr/bin/env python3
"""Deploy-time additions for search engines, written into the published copy only (the committed files are untouched).

    python3 scripts/seo.py docs

1. Prerenders the upcoming listings as plain HTML inside the home page's #list (the page's script replaces them on load).
2. Writes static pages that answer what students search for, rebuilt on every deploy from docs/events.json:
   /bops/, /formals/, /<balls>/ (e.g. /may-balls/), /other-events/, /colleges/ and /colleges/<college>/,
   each with its own title, description, listings, the college's formal-hall schedule and where it announces events.
3. Writes sitemap.xml and robots.txt.
Per-event schema.org markup is deliberately absent: college events are for members, and Google's event results are
for events the public can attend. Pages carry WebSite/BreadcrumbList data only.
"""
import datetime as dt, html, json, pathlib, re, sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
MARK = '<p class="status" id="loading">Loading…</p>'
DAYS = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
esc = html.escape


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("&", "and").replace("'", "").replace("’", "")).strip("-")


def full_name(college):
    """'Jesus' -> 'Jesus College'; names that already say what they are stay as they are."""
    return college if re.search(r"(College|Hall|Church)$", college) or college == "Peterhouse" else college + " College"


def start(e):
    return dt.datetime.fromisoformat(e["starts_at"].replace("Z", "+00:00")).astimezone(LONDON)


def upcoming(events, today):
    out = []
    for e in events:
        d = start(e).date()
        if today <= d <= today + dt.timedelta(days=400 if e.get("kind") == "ball" else 14):
            out.append(e)
    return sorted(out, key=lambda e: e["starts_at"])


def item(e, with_college=True):
    s = start(e)
    when = s.strftime("%A %-d %B") + ("" if e.get("kind") == "ball" and s.hour == 21 and s.minute == 0 else s.strftime(", %H:%M"))
    if e.get("kind") == "ball" and s.year != dt.date.today().year:
        when = s.strftime("%A %-d %B %Y")
    bits = [esc(full_name(e["college"]))] if with_college and e.get("college") else []
    if e.get("venue") and e.get("venue") != e.get("college"):
        bits.append(esc(e["venue"]))
    if e.get("price"):
        bits.append(esc(e["price"]))
    if e.get("dress"):
        bits.append(esc(e["dress"]))
    title = esc(e["title"])
    url = e.get("url", "")
    if re.match(r"https?://", url):
        title = f'<a href="{esc(url)}" rel="noopener">{title}</a>'
    det = f'<br><span class="d">{esc(e["details"])}</span>' if e.get("details") and e["details"] != "Time not stated." else ""
    return f'<li><time datetime="{esc(e["starts_at"])}">{esc(when)}</time> <strong>{title}</strong>' + (f' <span class="w">{" · ".join(bits)}</span>' if bits else "") + det + "</li>"


def listing(entries, empty, with_college=True):
    return "<ul class=\"ev\">" + "".join(item(e, with_college) for e in entries) + "</ul>" if entries else f'<p class="empty">{esc(empty)}</p>'


def page(city, path, title, description, h1, body, crumbs, updated):
    pal = city["palette"]["light"]
    site = city["site"].rstrip("/") + "/"
    url = site + path
    kinds = nav_kinds(city)
    nav = " · ".join(f'<a href="/{p}/">{esc(n)}</a>' for p, n in kinds) + ' · <a href="/colleges/">Colleges</a>'
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": site + p} for i, (p, n) in enumerate([("", f"{city['name']} Bops")] + crumbs)]}
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(city['name'])} Bops">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{site}og.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>
<style>
body {{ margin: 0; background: {pal['bg']}; color: {pal['fg']}; font: 16px/1.55 "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; padding: 2rem 16px 3rem; }}
main {{ max-width: 42rem; margin: 0 auto; }}
a {{ color: {pal['accent']}; }}
.top {{ font-size: .9rem; color: {pal['muted']}; }}
.top a.home {{ font-weight: 600; color: {pal['fg']}; text-decoration: none; }}
h1 {{ font-family: Georgia, "Times New Roman", serif; font-weight: 400; font-size: 2.1rem; line-height: 1.15; margin: 1rem 0 .5rem; }}
h2 {{ font-family: Georgia, "Times New Roman", serif; font-weight: 400; font-size: 1.4rem; margin: 2rem 0 .4rem; }}
.lede {{ color: {pal['muted']}; margin: 0 0 1rem; }}
.cta {{ display: inline-block; margin: .5rem 0 1rem; padding: .6rem 1.1rem; border-radius: 999px; background: {pal['cam']}; color: {pal['cam-ink']}; font-weight: 600; text-decoration: none; }}
ul.ev {{ list-style: none; padding: 0; margin: 0; }}
ul.ev li {{ padding: .5rem 0; border-top: 1px solid {pal['rule']}; }}
ul.ev time {{ display: block; font-size: .85rem; color: {pal['muted']}; }}
ul.ev strong a {{ color: inherit; }}
.w, .d {{ color: {pal['muted']}; font-size: .9rem; }}
.empty {{ color: {pal['muted']}; }}
ul.cols {{ columns: 2; padding-left: 1.1rem; }}
footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid {pal['rule']}; color: {pal['muted']}; font-size: .85rem; }}
</style>
</head>
<body>
<main>
<p class="top"><a class="home" href="/">{esc(city['name'])} Bops</a> · {nav}</p>
<h1>{esc(h1)}</h1>
{body}
<footer>Updated {esc(updated)} from the colleges', JCRs' and MCRs' own public pages. Details change: check the linked page before you go. <a href="/">All listings</a> · <a href="/colleges/">All colleges</a></footer>
</main>
</body>
</html>
"""


def nav_kinds(city):
    return [("bops", "Bops"), ("formals", "Formals"), (slug(city["balls"]["many"]), city["balls"]["many"]), ("societies", "Societies"), ("other-events", "Other events")]


def build(out, city, data, sources, now, societies=()):
    today = now.astimezone(LONDON).date()
    up = upcoming(data.get("bops", []), today)
    updated = start({"starts_at": data.get("generated") or now.isoformat()}).strftime("%-d %B %Y")
    name, balls = city["name"], city["balls"]
    pages = {}
    colleges = list(city["colleges"])
    by_kind = {k: [e for e in up if e.get("kind", "bop") == k] for k in ("bop", "formal", "ball", "society", "other")}

    def college_links(entries):
        cs = sorted({e["college"] for e in entries if e.get("college") in city["colleges"]})
        return ("<p>By college: " + ", ".join(f'<a href="/colleges/{slug(c)}/">{esc(c)}</a>' for c in cs) + ".</p>") if cs else ""

    kpages = [
        ("bops", "bop", f"{name} bops this week and next: every college bop | {name} Bops",
         f"Every {name} college bop in the next fortnight: Halloween, Christmas, themed and super bops at each college, with times, prices and links, updated every Sunday.",
         f"{name} bops in the next fortnight",
         f"Bops are college party nights run by the JCR, MCR or ents committee. These are every bop announced on the colleges' own pages for the next 14 days.",
         "No bops have been announced for the next fortnight yet. Bops are usually announced a week or two ahead."),
        ("formals", "formal", f"{name} formal halls this fortnight: every college formal | {name} Bops",
         f"Every {name} college formal hall in the next fortnight: regular formal nights, themed formals, feasts, super halls, guest nights and swaps, with times and booking links.",
         f"{name} formals in the next fortnight",
         f"Formal hall is the college's gowned dinner. Listed here: each college's regular formal nights in term and every themed formal, feast, guest night and swap it announces.",
         "No formals are listed for the next fortnight, usually because it is outside term."),
        (slug(balls["many"]), "ball", f"{name} {balls['many']}: dates of every {balls['one']} | {name} Bops",
         f"Dates of the {name} {balls['many']} as each college announces them, with links to each ball's own site.",
         f"{name} {balls['many']}",
         f"The {balls['routine']}. Each is listed from the day its date is announced until it has happened.",
         f"No {balls['one']} dates have been announced yet. They are usually announced in the autumn and winter."),
        ("other-events", "other", f"{name} college events this fortnight: socials, quizzes and more | {name} Bops",
         f"Other {name} college events in the next fortnight: JCR and MCR socials, quizzes, film nights, open mics, concerts and talks, from the colleges' own pages.",
         f"Other {name} college events",
         f"JCR and MCR socials, quizzes, film nights, open mics, concerts and talks announced on the colleges' own pages for the next 14 days.",
         "No other college events are listed for the next fortnight."),
    ]
    for path, kind, title, desc, h1, lede, empty in kpages:
        body = (f'<p class="lede">{esc(lede)}</p><a class="cta" href="/?kind={kind}">Open the live list with filters and map</a>'
                + listing(by_kind[kind], empty) + college_links(by_kind[kind]))
        pages[path + "/"] = page(city, path + "/", title, desc, h1, body, [(path + "/", h1)], updated)

    # One page per college.
    formal_src = {}
    for s in sources:
        if s["kind"] == "Formal hall":
            formal_src.setdefault(s["college"], s)
    idx = []
    for c in colleges:
        fn, sl = full_name(c), slug(c)
        mine = [e for e in up if e.get("college") == c]
        n_up = len(mine)
        idx.append(f'<li><a href="/colleges/{sl}/">{esc(fn)}</a>' + (f" ({n_up} upcoming)" if n_up else "") + "</li>")
        sec = []
        for kind, label in (("bop", "Bops"), ("formal", "Formals"), ("ball", balls["one"]), ("other", "Other events")):
            ents = [e for e in mine if e.get("kind", "bop") == kind]
            if ents:
                sec.append(f"<h2>{esc(label)}</h2>" + listing(ents, "", with_college=False))
        if not sec:
            sec.append(f'<p class="empty">Nothing is announced at {esc(fn)} for the next fortnight yet.</p>')
        fs = formal_src.get(c)
        if fs:
            days = fs.get("formal_days") or []
            sched = (f"Formal hall at {esc(fn)} runs on " + ", ".join(DAYS[d] for d in days) + " in Full Term" + (f" ({esc(fs['note'])})" if fs.get("note") else "") + ". "
                     if days else "")
            sec.append(f'<h2>Formal hall</h2><p>{sched}See <a href="{esc(fs["url"])}" rel="noopener">{esc(fs["name"])}</a> for booking and menus.</p>')
        where = [s for s in sources if s["college"] == c and s["kind"] != "Formal hall"]
        if where:
            sec.append("<h2>Where " + esc(fn) + " announces events</h2><ul>" + "".join(
                f'<li><a href="{esc(s["url"])}" rel="noopener">{esc(s["name"])}</a> ({esc(s["kind"])})</li>' for s in where) + "</ul>")
        title = f"{fn} bops, formals and events | {name} Bops"
        desc = (f"Upcoming bops, formal halls and college events at {fn}, {name}: dates, times and links to the JCR, MCR and college pages, updated every Sunday."
                + (f" {n_up} listed now." if n_up else ""))
        body = (f'<p class="lede">Every bop, formal and event announced at {esc(fn)} for the next fortnight, and its {esc(balls["one"])} date when announced.</p>'
                f'<a class="cta" href="/?college={html.escape(c, quote=True)}">Open {esc(c)} in the live list</a>' + "".join(sec))
        pages[f"colleges/{sl}/"] = page(city, f"colleges/{sl}/", title, desc, f"{fn}: bops, formals and events", body,
                                        [("colleges/", "Colleges"), (f"colleges/{sl}/", fn)], updated)
    # Societies: an index in order of popularity, and one page per society.
    ranked = {}
    for x in sorted(societies, key=lambda x: x["rank"]):
        ranked.setdefault(x["society"], []).append(x)
    rows = []
    for soc, regs in ranked.items():
        mine = [e for e in by_kind["society"] if e.get("society") == soc]
        sl = slug(soc)
        rows.append(f'<li><a href="/societies/{sl}/">{esc(regs[0].get("name", soc))}</a>' + (f" ({len(mine)} upcoming)" if mine else "") + "</li>")
        body = (f'<p class="lede">Every event {esc(soc)} announces for the next fortnight, from its own pages, updated every Sunday.</p>'
                f'<a class="cta" href="/?kind=society&amp;society={html.escape(soc, quote=True)}">Open {esc(soc)} in the live list</a>'
                + listing(mine, f"No {soc} events are announced for the next fortnight yet.")
                + f"<h2>Where {esc(soc)} announces events</h2><ul>" + "".join(
                    f'<li><a href="{esc(x["url"])}" rel="noopener">{esc(x["name"])}</a> ({esc(x["kind"])})</li>' for x in regs) + "</ul>")
        pages[f"societies/{sl}/"] = page(city, f"societies/{sl}/", f"{soc} events in {name}: talks, socials and shows | {name} Bops",
                                         f"Upcoming {soc} events in {name}: dates, times and links to the society's own pages, updated every Sunday."
                                         + (f" {len(mine)} listed now." if mine else ""),
                                         f"{soc} events", body, [("societies/", "Societies"), (f"societies/{sl}/", soc)], updated)
    if ranked:
        body = (f'<p class="lede">Events of {name}\'s most popular student societies for the next fortnight, most popular first. '
                'Popularity is judged from membership, followers, press coverage and the size of their events, and reviewed every two months.</p>'
                '<a class="cta" href="/?kind=society">Open societies in the live list</a>'
                + listing(by_kind["society"], "No society events are announced for the next fortnight yet.")
                + "<h2>Societies we follow</h2><ol>" + "".join(rows) + "</ol>")
        pages["societies/"] = page(city, "societies/", f"{name} society events this fortnight: the most popular societies | {name} Bops",
                                   f"Events of {name}'s most popular student societies in the next fortnight: talks, debates, socials, shows and parties, from the societies' own pages.",
                                   f"{name} society events", body, [("societies/", "Societies")], updated)

    pages["colleges/"] = page(city, "colleges/", f"{name} colleges: bops, formals and events at each college | {name} Bops",
                              f"Bops, formal halls and events at each of the {len(colleges)} {name} colleges, with where each college announces them.",
                              f"Bops and formals at each {name} college", '<ul class="cols">' + "".join(idx) + "</ul>", [("colleges/", "Colleges")], updated)

    for path, text in pages.items():
        f = out / path / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return pages


def prerender(entries, city, limit=60):
    rows = [item(e) for e in entries[:limit]]
    if not rows:
        return ""
    return f'<div id="prerender"><h2>{esc(city)} bops, formals and college events coming up</h2><ul>' + "".join(rows) + "</ul></div>"


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
    city = json.loads((ROOT / "city.json").read_text())
    data = json.loads((out / "events.json").read_text())
    sources = json.loads((ROOT / "docs" / "sources.json").read_text())["sources"]
    page_html = (out / "index.html").read_text()
    if MARK not in page_html:
        sys.exit("seo.py: the loading placeholder is missing from index.html")
    now = dt.datetime.now(dt.timezone.utc)
    up = upcoming(data.get("bops", []), now.astimezone(LONDON).date())
    page_html = page_html.replace(MARK, MARK + prerender(up, city["name"]), 1)
    (out / "index.html").write_text(page_html)
    societies = json.loads((ROOT / "docs" / "sources.json").read_text()).get("societies", [])
    pages = build(out, city, data, sources, now, societies)
    site = city["site"].rstrip("/") + "/"
    lastmod = (data.get("generated") or now.isoformat())[:10]
    urls = [""] + sorted(pages)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{site}{u}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq></url>\n" for u in urls)
                                     + "</urlset>\n")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site}sitemap.xml\n")
    print(f"seo: prerendered {min(len(up), 60)} listings, {len(pages)} pages, sitemap of {len(urls)} URLs, lastmod {lastmod}")


if __name__ == "__main__":
    main()
