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

TOKEN_ORDER = ["bg", "fg", "muted", "rule", "cam", "cam-ink", "cam-tint", "accent", "field", "pin-ring", "hl", "hl-line", "on-badge", "tile-filter"]


def tokens(theme, indent):
    pal = CITY["palette"][theme]
    missing = [k for k in TOKEN_ORDER if k not in pal]
    if missing:
        sys.exit(f"city.json palette.{theme} is missing {missing}")
    return "\n".join(f"{indent}--{k}: {pal[k]};" for k in TOKEN_ORDER) + ("" if theme == "light" else f"\n{indent}color-scheme: dark;")


def favicon():
    f = CITY["favicon"]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="9" fill="%s"/>'
           '<clipPath id="c"><circle cx="20" cy="20" r="14"/></clipPath><circle cx="20" cy="20" r="14" fill="%s"/>'
           '<g clip-path="url(#c)" stroke="%s" stroke-width="1.8"><path d="M4 11h32M4 16h32M4 20h32M4 24h32M4 29h32"/>'
           '<path d="M11 4v32M16 4v32M20 4v32M24 4v32M29 4v32"/></g></svg>') % (f["tile"], f["ball"], f["lines"])
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def colleges_js():
    items = [f'    {json.dumps(n, ensure_ascii=False)}: [{lat}, {lng}]' for n, (lat, lng) in CITY["colleges"].items()]
    return "{\n" + ",\n".join(items) + "\n  }"


def render_page():
    t = (ROOT / "site" / "index.template.html").read_text()
    values = {
        "city": CITY["name"], "tagline": CITY["tagline"], "favicon": favicon(), "colleges_js": colleges_js(),
        "map_center": json.dumps(CITY["map_center"]), "map_zoom": str(CITY.get("map_zoom", 14)),
        "tokens_light": tokens("light", "  "), "tokens_dark": tokens("dark", "  "), "tokens_dark_indented": tokens("dark", "    "),
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
        "source_count": str(CITY.get("source_count_hint", 150)),
    }
    for k, v in values.items():
        t = t.replace("{{" + k + "}}", v)
    left = [w for w in set(__import__("re").findall(r"\{\{(\w+)\}\}", t))]
    if left:
        sys.exit(f"unfilled placeholders in the routine template: {left}")
    return t


def main():
    outputs = {ROOT / "docs" / "index.html": render_page(), ROOT / "docs" / "ROUTINE.md": render_routine()}
    if "--check" in sys.argv:
        stale = [str(p.relative_to(ROOT)) for p, content in outputs.items() if not p.exists() or p.read_text() != content]
        if stale:
            print("out of date, run scripts/build.py:", ", ".join(stale)); sys.exit(1)
        print("docs are up to date"); return
    for p, content in outputs.items():
        p.write_text(content); print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
