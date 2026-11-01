#!/usr/bin/env python3
"""Render the city's pages from the shared templates and city.json.

    scripts/build.py           # writes docs/index.html and docs/ROUTINE.md
    scripts/build.py --check   # exit 1 if the rendered files differ from what is committed

Everything city-specific (name, palette, colleges and coordinates, map centre, student press) lives in
city.json. Everything shared (page markup and script, routine wording, tests, scripts, workflow) lives in
site/, scripts/, tests/ and .github/, and is copied between city repositories by scripts/sync_template.sh.
"""
import json, pathlib, sys, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
CITY = json.loads((ROOT / "city.json").read_text())
FEATURES = json.loads((ROOT / "site" / "features.json").read_text())
FORMALS = bool(FEATURES.get("formals"))

TOKEN_ORDER = ["bg", "fg", "muted", "rule", "cam", "cam-ink", "cam-tint", "accent", "field", "pin-ring", "hl", "hl-line", "on-badge", "tile-filter"]


def tokens(theme, indent):
    pal = CITY["palette"][theme]
    missing = [k for k in TOKEN_ORDER if k not in pal]
    if missing:
        sys.exit(f"city.json palette.{theme} is missing {missing}")
    return "\n".join(f"{indent}--{k}: {pal[k]};" for k in TOKEN_ORDER)


def favicon():
    f = CITY["favicon"]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="9" fill="%s"/>'
           '<clipPath id="c"><circle cx="20" cy="20" r="14"/></clipPath><circle cx="20" cy="20" r="14" fill="%s"/>'
           '<g clip-path="url(#c)" stroke="%s" stroke-width="1.8"><path d="M4 11h32M4 16h32M4 20h32M4 24h32M4 29h32"/>'
           '<path d="M11 4v32M16 4v32M20 4v32M24 4v32M29 4v32"/></g></svg>') % (f["tile"], f["ball"], f["lines"])
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def analytics():
    """GoatCounter (gc.zgo.at): cookieless pageview counting, no consent banner needed. Empty code -> no analytics at all."""
    code = (CITY.get("analytics") or {}).get("goatcounter", "")
    if not code:
        return ""
    if not __import__("re").fullmatch(r"[a-z0-9-]+", code):
        sys.exit(f"city.json analytics.goatcounter must be a GoatCounter site code (lowercase letters, digits, dashes), got {code!r}")
    # Pageviews are counted under /<slug> rather than /, so several cities can share one GoatCounter site and still be told apart.
    settings = json.dumps({"path": "/" + CITY["slug"]})
    return f'<script data-goatcounter="https://{code}.goatcounter.com/count" data-goatcounter-settings=\'{settings}\' async src="https://gc.zgo.at/count.js"></script>'


def colleges_js():
    items = [f'    {json.dumps(n, ensure_ascii=False)}: [{lat}, {lng}]' for n, (lat, lng) in CITY["colleges"].items()]
    return "{\n" + ",\n".join(items) + "\n  }"


def verification():
    """Google Search Console ownership tag, from city.json "google_site_verification" (empty: no tag)."""
    code = CITY.get("google_site_verification", "")
    if code and not __import__("re").fullmatch(r"[A-Za-z0-9_-]{20,80}", code):
        sys.exit(f"city.json google_site_verification looks wrong: {code!r}")
    return f'\n<meta name="google-site-verification" content="{code}">' if code else ""


def render_page():
    t = (ROOT / "site" / "index.template.html").read_text()
    values = {
        "city": CITY["name"], "slug": CITY["slug"], "tagline": CITY["tagline"], "favicon": favicon(), "colleges_js": colleges_js(),
        "map_center": json.dumps(CITY["map_center"]), "map_zoom": str(CITY.get("map_zoom", 14)), "analytics": analytics(),
        "ball_tab": CITY["balls"]["tab"], "ball_one": CITY["balls"]["one"], "ball_many": CITY["balls"]["many"],
        "tokens_light": tokens("light", "  "), "site": CITY["site"],
        "formals_comma": "formals, " if FORMALS else "", "formal_or": "formal, " if FORMALS else "", "formal_hall_comma": "formal hall, " if FORMALS else "",
        "kinds_js": json.dumps(["bop"] + (["formal"] if FORMALS else []) + ["ball", "society", "other"]),
        "formal_tab": '<button type="button" data-kind="formal" aria-pressed="false">Formals<span class="n" hidden></span></button>' if FORMALS else "<!-- Formals are paused (site/features.json) -->",
        "formals_nav": '<a href="formals/">Formals</a>' if FORMALS else "",
        "formal_about": " Formal hall is the college's gowned dinner, from regular formal nights to themed formals, feasts and swaps." if FORMALS else "", "terms_version": TERMS_VERSION, "ball_slug": __import__("re").sub(r"[^a-z0-9]+", "-", CITY["balls"]["many"].lower()).strip("-"), "verification": verification(),
        "ld_dataset": json.dumps({"@context": "https://schema.org", "@type": "Dataset", "name": f"{CITY['name']} Bops student event listings",
                                  "description": f"Unofficial, automatically gathered listings of college bops, formal halls, balls, society events and other student events in {CITY['name']}, updated weekly from the organisers' own public pages. Not verified: confirm with the organiser.",
                                  "url": CITY["site"], "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
                                  "creditText": f"Source: {CITY['name']} Bops ({CITY['site']})",
                                  "creator": {"@type": "Organization", "name": f"{CITY['name']} Bops", "url": CITY["site"]},
                                  "keywords": [f"{CITY['name']} bops", f"{CITY['name']} formal hall", CITY["balls"]["many"], "student events", f"{CITY['name']} societies"],
                                  "spatialCoverage": {"@type": "Place", "name": f"{CITY['name']}, United Kingdom"},
                                  "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": CITY["site"] + "events.json"},
                                                   {"@type": "DataDownload", "encodingFormat": "text/plain", "contentUrl": CITY["site"] + "llms-full.txt"}]},
                                 ensure_ascii=False).replace("</", "<\\/"),
        "ld_site": json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": f"{CITY['name']} Bops", "url": CITY["site"],
                               "alternateName": [f"{CITY['name']} bops", f"{CITY['name']} college bops", f"{CITY['name']} formals"],
                               "description": CITY["tagline"]}, ensure_ascii=False).replace("</", "<\\/"),
    }
    for k, v in values.items():
        t = t.replace("{{" + k + "}}", v)
    left = [w for w in set(__import__("re").findall(r"\{\{(\w+)\}\}", t))]
    if left:
        sys.exit(f"unfilled placeholders in the page template: {left}")
    return t


def render_routine():
    t = (ROOT / "site" / "ROUTINE.template.md").read_text()
    r = CITY["routine"]
    press = " and ".join(f"{p['name']} ({p['url']})" for p in r["press"])
    values = {
        "city": CITY["name"], "org": CITY["org"], "repo": f"{CITY['org']}/{CITY['org']}.github.io",
        "common_rooms": r["common_rooms"], "su_name": r["su"]["name"], "su_url": r["su"]["url"], "press": press,
        "press_names": ", ".join(p["name"] for p in r["press"]), "js_rendered_examples": r["js_rendered_examples"],
        "college_count": str(len(CITY["colleges"])), "college_list": ", ".join(CITY["colleges"]),
        "ball_routine": CITY["balls"]["routine"], "ball_many": CITY["balls"]["many"],
        "formals_paused": "" if FORMALS else "\n**Formals are paused** (`site/features.json`): do not list any formal hall, formal dinner, feast, guest night or formal swap, under any kind. Ignore the formal rules below until they are switched back on.\n", "university_domain": CITY.get("university_domain", "the university domain"),
        "source_count": str(CITY.get("source_count_hint", 150)),
    }
    for k, v in values.items():
        t = t.replace("{{" + k + "}}", v)
    left = [w for w in set(__import__("re").findall(r"\{\{(\w+)\}\}", t))]
    if left:
        sys.exit(f"unfilled placeholders in the routine template: {left}")
    return t


TERMS_VERSION = "2026-11-01.3"   # change when the terms change: every visitor is asked to accept the new version


def render_terms():
    t = (ROOT / "site" / "terms.template.html").read_text()
    pal = CITY["palette"]["light"]
    values = {"city": CITY["name"], "site": CITY["site"], "repo": f"{CITY['org']}/{CITY['org']}.github.io", "terms_version": TERMS_VERSION,
              "bg": pal["bg"], "fg": pal["fg"], "muted": pal["muted"], "accent": pal["accent"], "cam": pal["cam"], "field": pal["field"]}
    for k, v in values.items():
        t = t.replace("{{" + k + "}}", v)
    left = __import__("re").findall(r"\{\{(\w+)\}\}", t)
    if left:
        sys.exit(f"unfilled placeholders in the terms template: {left}")
    return t


def main():
    (ROOT / "docs" / "terms").mkdir(exist_ok=True)
    outputs = {ROOT / "docs" / "index.html": render_page(), ROOT / "docs" / "ROUTINE.md": render_routine(), ROOT / "docs" / "terms" / "index.html": render_terms()}
    if "--check" in sys.argv:
        stale = [str(p.relative_to(ROOT)) for p, content in outputs.items() if not p.exists() or p.read_text() != content]
        if stale:
            print("out of date, run scripts/build.py:", ", ".join(stale)); sys.exit(1)
        print("docs are up to date"); return
    for p, content in outputs.items():
        p.write_text(content); print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
