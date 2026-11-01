#!/usr/bin/env python3
"""Draw the link-preview image docs/og.png (1200 x 630) from city.json, with headless Chromium. Run once per city,
and again after changing the name, palette or tagline; the file is committed.

    python3 scripts/og_image.py
"""
import html, json, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
city = json.loads((ROOT / "city.json").read_text())
pal, f = city["palette"]["light"], city["favicon"]
ball = (f'<svg width="150" height="150" viewBox="0 0 40 40"><clipPath id="c"><circle cx="20" cy="20" r="18"/></clipPath><circle cx="20" cy="20" r="18" fill="{pal["cam"]}"/>'
        f'<g clip-path="url(#c)" stroke="{pal["bg"]}" stroke-width="1.6"><path d="M2 8h36M2 14h36M2 20h36M2 26h36M2 32h36"/><path d="M8 2v36M14 2v36M20 2v36M26 2v36M32 2v36"/></g></svg>')
doc = f"""<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@400;600&display=block"></head>
<body style="margin:0;width:1200px;height:630px;background:{pal['bg']};display:flex;align-items:center;padding:0 90px;box-sizing:border-box;gap:60px;font-family:'IBM Plex Sans',sans-serif">
{ball}<div><div style="font-family:'Instrument Serif',serif;font-size:118px;line-height:1;color:{pal['fg']}">{html.escape(city['name'])} <em style="background:linear-gradient(transparent 60%,{pal['hl']} 60%,{pal['hl']} 92%,transparent 92%)">Bops</em></div>
<div style="font-size:34px;color:{pal['muted']};margin-top:28px;max-width:820px">{html.escape(city['tagline'])}</div>
<div style="font-size:26px;color:{pal['accent']};margin-top:22px;font-weight:600">{html.escape(city['site'].replace('https://','').rstrip('/'))}</div></div></body></html>"""
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page(viewport={"width": 1200, "height": 630})
    p.set_content(doc); p.wait_for_timeout(1500)
    p.screenshot(path=str(ROOT / "docs" / "og.png")); b.close()
print("wrote docs/og.png")
