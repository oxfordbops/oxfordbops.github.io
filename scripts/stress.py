#!/usr/bin/env python3
"""Build stress-test variants of the page under a scratch directory, then drive them with the gstack browse tool.

    scripts/stress.py build <outdir>     # writes <case>.html + <case>.json variants of docs/index.html
    scripts/stress.py check <report.json>  # (used by the shell driver) asserts on the collected results

Each variant is docs/index.html with: the data file swapped for a generated JSON, an optional fake clock
(so "Tonight", "This weekend" and "Next week" can be tested on known days), and an optional forced theme.
"""
import json, pathlib, random, sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "index.html").read_text()
COLLEGES = json.loads((ROOT / "docs" / "sources.json").read_text())["colleges"]

CLOCK = """<script>(function(){const R=Date;const FIXED=new R("%s").getTime();const OFF=FIXED-R.now();
class D extends R{constructor(...a){if(a.length===0){super(R.now()+OFF)}else{super(...a)}}static now(){return R.now()+OFF}}
window.Date=D;})();</script>\n"""


def variant(name, data, clock=None, theme=None, json_name=None):
    html = PAGE.replace('fetch("events.json"', f'fetch("{json_name or name}.json"')
    if clock:
        html = html.replace("<head>", "<head>\n" + CLOCK % clock, 1)
    if theme:
        html = html.replace("<html lang=\"en-GB\">", f'<html lang="en-GB" data-theme="{theme}">', 1)
    return html, data


def iso(dt):
    return dt.isoformat(timespec="seconds")


def build(out):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    gen = {"generated": iso(now), "sources": [{"slug": "s", "name": "S", "kind": "JCR site", "url": "https://example.org/", "ok": True, "found": 0}]}
    cases = {}

    # 1. empty
    cases["empty"] = variant("empty", {**gen, "bops": []})

    # 2. many: 80 bops over 14 days, every college, long strings, missing fields, nulls, unicode
    rnd = random.Random(7); bops = []
    for i in range(80):
        day = rnd.randint(0, 13); hour = rnd.choice([19, 20, 21, 22, 23]); minute = rnd.choice([0, 15, 30])
        start = (now.replace(hour=0, minute=0) + timedelta(days=day, hours=hour, minutes=minute))
        college = COLLEGES[i % len(COLLEGES)] if i % 9 else None
        b = {"title": ("Very long bop title " * 6).strip()[:120] if i % 11 == 0 else f"Bop {i} — théme été ✨",
             "starts_at": iso(start), "college": college, "venue": "Somewhere off campus" if college is None else f"{college} bar",
             "url": "https://example.org/b/%d" % i, "source": "s"}
        if i % 3 == 0: b["ends_at"] = iso(start + timedelta(hours=3))        # past midnight
        if i % 4 == 0: b["price"] = "£3 members, £5 guests, free before 21:00"
        if i % 5 == 0: b["guests"] = "Guests welcome, signed in by a member"
        if i % 6 == 0: b["dress"] = "Black tie optional, costume encouraged"
        if i % 7 == 0: b["details"] = ("Details sentence that goes on for a while. " * 7)[:300]
        bops.append(b)
    cases["many"] = variant("many", {**gen, "bops": bops})

    # 3. hostile: XSS attempts in every string field, bad dates, ends before start, wrong college name, missing fields
    hostile = [
        {"title": "<img src=x onerror=\"window.__xss=1\">Bop", "starts_at": iso(now + timedelta(hours=5)), "college": "Jesus",
         "venue": "<script>window.__xss=2</script>", "host": "\"><b>bold</b>", "price": "<a href=x>x</a>", "details": "<svg onload=\"window.__xss=3\">", "url": "javascript:window.__xss=4", "source": "s"},
        {"title": "Bad date", "starts_at": "not a date", "college": "Clare", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Unknown college", "starts_at": iso(now + timedelta(days=2)), "college": "Hogwarts", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Ends before start", "starts_at": iso(now + timedelta(days=3)), "ends_at": iso(now + timedelta(days=2)), "college": "Selwyn", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Past", "starts_at": iso(now - timedelta(days=2)), "college": "Selwyn", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Far future", "starts_at": iso(now + timedelta(days=40)), "college": "Selwyn", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "No venue no college", "starts_at": iso(now + timedelta(days=1)), "url": "https://example.org", "source": "s"},
        {"starts_at": iso(now + timedelta(days=1, hours=3)), "college": "Girton", "venue": "x", "source": "s"},  # no title, no url
    ]
    cases["hostile"] = variant("hostile", {**gen, "bops": hostile})

    # 4. missing data file
    cases["missing"] = variant("missing", None, json_name="does-not-exist")

    # 5. malformed JSON
    cases["malformed"] = variant("malformed", "{not json")

    # 6. clocks: Sunday evening (weekend = today only), Monday (weekend = Fri-Sun ahead), Saturday 23:30, BST July, DST-change weekend
    fixture = [
        {"title": "Fri bop", "starts_at": "2026-11-06T21:00:00+00:00", "college": "Jesus", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Sat bop", "starts_at": "2026-11-07T21:00:00+00:00", "college": "Clare", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Sun bop", "starts_at": "2026-11-08T20:00:00+00:00", "college": "Selwyn", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Mon next week bop", "starts_at": "2026-11-09T21:00:00+00:00", "college": "Girton", "venue": "x", "url": "https://example.org", "source": "s"},
        {"title": "Late Sunday bop", "starts_at": "2026-11-08T23:30:00+00:00", "college": "Trinity", "venue": "x", "url": "https://example.org", "source": "s"},
    ]
    cases["clock_sunday"] = variant("clock_sunday", {**gen, "generated": "2026-11-08T06:00:00+00:00", "bops": fixture}, clock="2026-11-08T18:00:00Z")
    cases["clock_monday"] = variant("clock_monday", {**gen, "generated": "2026-11-02T06:00:00+00:00", "bops": fixture}, clock="2026-11-02T09:00:00Z")
    cases["clock_satlate"] = variant("clock_satlate", {**gen, "generated": "2026-11-07T06:00:00+00:00", "bops": fixture}, clock="2026-11-07T23:30:00Z")
    bst = [{"title": "July bop", "starts_at": "2027-07-03T21:00:00+01:00", "college": "Jesus", "venue": "x", "url": "https://example.org", "source": "s"}]
    cases["clock_bst"] = variant("clock_bst", {**gen, "generated": "2027-07-02T06:00:00+01:00", "bops": bst}, clock="2027-07-02T12:00:00Z")
    dst = [{"title": "Clocks go back bop", "starts_at": "2026-10-24T21:00:00+01:00", "college": "Jesus", "venue": "x", "url": "https://example.org", "source": "s"},
           {"title": "After the change", "starts_at": "2026-10-25T20:00:00+00:00", "college": "Clare", "venue": "x", "url": "https://example.org", "source": "s"}]
    cases["clock_dst"] = variant("clock_dst", {**gen, "generated": "2026-10-24T06:00:00+01:00", "bops": dst}, clock="2026-10-24T12:00:00Z")

    # 7. dark theme with the many fixture
    cases["dark"] = variant("dark", None, theme="dark", json_name="many")

    for name, (html, data) in cases.items():
        (out / f"{name}.html").write_text(html)
        if data is not None:
            (out / f"{name}.json").write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
    print("built", ", ".join(cases))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2])
