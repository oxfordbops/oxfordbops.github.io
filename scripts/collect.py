#!/usr/bin/env python3
"""Fetch every readable registered source once and write a compact digest for the daily routine.

    python3 scripts/collect.py [--out /tmp/collect] [--render]

Stdlib only. For each registry source that is not Instagram or Facebook it:
  - fetches the page (ordinary browser User-Agent, 20 s timeout, no retries past a 403 or a login page),
  - follows up to 6 same-site links whose address or text looks like events, ents, calendar, termcard,
    formal hall, dining or balls,
  - reads embedded Google Calendars as their public iCal feeds and keeps the events in the window,
  - reads linked PDFs with pdftotext when it is installed,
  - with --render, renders pages that came back empty with headless Chromium (Playwright, if installed).

Output in --out:
  digest.md     what the routine reads: unreadable sources, calendar events in the window, and
                keyword snippets (bop, formal, ball, ...) with the page they came from
  status.json   one record per registry URL: ok, code, note, followed links
  pages/*.txt   full text of every page fetched, for checking a snippet in context
The routine still decides what counts; this script only gathers.
"""
import argparse, base64, concurrent.futures as cf, datetime as dt, html, json, pathlib, re, shutil, subprocess, sys
import urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
FOLLOW = re.compile(r"event|ents?\b|entz|calendar|term-?card|formal|dining|hall|whats-?on|ball|social", re.I)
SKIP = re.compile(r"login|signin|sign-in|raven|shibboleth|webauth|\.(jpg|jpeg|png|gif|svg|zip|docx?)$|mailto:|tel:|#", re.I)
KEYWORDS = re.compile(r"\b(bops?|super ?bop|formals?|formal hall|super ?hall|guest night|swap|feast|may ball|june event|commem|ball\b|halloween|bonfire|christmas|burns|diwali|bar night|party|ents night)\b", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
SCHEDULE = re.compile(r"\bformal(?:s| hall)?\b[^.\n]{0,80}\b(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|every (?:night|evening|day)|nights? a week|times a week)\b|\b(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b[^.\n]{0,60}\bformal", re.I)
DATEISH = re.compile(r"\b(\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|(mon|tue|wed|thu|fri|sat|sun)[a-z]*day|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|\d{1,2}/\d{1,2}|week\s*\d)\b", re.I)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,text/calendar,application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4_000_000)
            return {"code": r.status, "final": r.geturl(), "type": r.headers.get("Content-Type", ""), "body": body}
    except urllib.error.HTTPError as e:
        return {"code": e.code, "final": url, "type": "", "body": b"", "note": f"HTTP {e.code}"}
    except Exception as e:
        return {"code": 0, "final": url, "type": "", "body": b"", "note": type(e).__name__ + ": " + str(e)[:80]}


def to_text(raw):
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|section|article)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def links(raw, base):
    out = []
    for m in re.finditer(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw.decode("utf-8", "replace")):
        href, text = m.group(1), html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        url = urllib.parse.urljoin(base, href)
        if url.startswith("http"):
            out.append((url.split("#")[0], " ".join(text.split())[:80]))
    return out


def calendar_ids(raw):
    s = urllib.parse.unquote(html.unescape(raw.decode("utf-8", "replace")))
    ids = set(re.findall(r"calendar/ical/([^/\s\"'<>]+)/public", s))
    for v in re.findall(r"calendar\.google\.com/calendar/(?:u/\d/)?embed\?[^\"'<>\s]*", s):
        for src in urllib.parse.parse_qs(urllib.parse.urlparse(v.replace("&amp;", "&")).query).get("src", []):
            ids.add(src)
    good = set()
    for i in ids:
        if "@" not in i:   # newer embeds base64-encode the id
            try:
                d = base64.b64decode(i + "=" * (-len(i) % 4)).decode()
                if "@" in d:
                    i = d
            except Exception:
                continue
        if "@" in i and "holiday" not in i:
            good.add(i)
    return good


DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def occurrences(start, rule, lo, hi):
    """Dates of a recurring event that fall in [lo, hi]. Handles DAILY and WEEKLY (INTERVAL, BYDAY, COUNT, UNTIL);
    MONTHLY and YEARLY are checked by day of month and by date."""
    r = dict(x.split("=", 1) for x in rule.split(";") if "=" in x)
    freq, step = r.get("FREQ"), int(r.get("INTERVAL", "1") or 1)
    until = dt.datetime.strptime(r["UNTIL"][:8], "%Y%m%d").date() if "UNTIL" in r else None
    count = int(r["COUNT"]) if "COUNT" in r else None
    byday = [d[-2:] for d in r.get("BYDAY", "").split(",") if d] or [DAYS[start.weekday()]]
    out, n, day = [], 0, start.date()
    end = min(hi, until) if until else hi
    while day <= end and (count is None or n < count):
        ok = False
        if freq == "DAILY":
            ok = (day - start.date()).days % step == 0
        elif freq == "WEEKLY":
            ok = DAYS[day.weekday()] in byday and ((day - start.date()).days // 7) % step == 0
        elif freq == "MONTHLY":
            ok = day.day == start.day
        elif freq == "YEARLY":
            ok = (day.month, day.day) == (start.month, start.day)
        if ok:
            n += 1
            if day >= lo:
                out.append(day)
        day += dt.timedelta(days=1)
        if count is None and day < lo - dt.timedelta(days=1) and freq in ("DAILY", "WEEKLY"):
            # jump close to the window for long-running series without a COUNT
            gap = (lo - day).days // (7 * step) * (7 * step)
            day += dt.timedelta(days=max(gap - 7 * step, 0))
    return out


def ics_events(text, lo, hi, ball_hi):
    text = re.sub(r"\r?\n[ \t]", "", text)   # unfold
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in block.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                f.setdefault(k.split(";")[0], (k, v))
        if "DTSTART" not in f:
            continue
        key, val = f["DTSTART"]
        try:
            if "VALUE=DATE" in key or len(val) == 8:
                start = dt.datetime.strptime(val[:8], "%Y%m%d").replace(hour=12, tzinfo=LONDON)
            elif val.endswith("Z"):
                start = dt.datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(LONDON)
            else:
                tz = re.search(r"TZID=([^;:]+)", key)
                start = dt.datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(tz.group(1)) if tz else LONDON).astimezone(LONDON)
        except Exception:
            continue
        summary = f.get("SUMMARY", ("", ""))[1].replace("\\,", ",").replace("\\n", " ")
        day = start.date()
        limit = ball_hi if re.search(r"\bball\b|june event|commem", summary, re.I) else hi
        if "RRULE" in f:
            try:
                days = occurrences(start, f["RRULE"][1], lo, limit)
            except Exception:
                days = []
        else:
            days = [day] if lo <= day <= limit else []
        for d in days:
            when = dt.datetime.combine(d, start.timetz())
            out.append({"start": when.isoformat(timespec="minutes"), "summary": summary[:100],
                        "location": f.get("LOCATION", ("", ""))[1].replace("\\,", ",")[:60],
                        "status": f.get("STATUS", ("", ""))[1], "recurring": "RRULE" in f})
    return out


def dates_in(chunk, years):
    out = set()
    for m in DAY_MONTH.finditer(chunk):
        d, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        for y in years:
            try:
                out.add(dt.date(y, MONTHS[mon[:3].lower()], int(d)))
            except ValueError:
                pass
    return out


def snippets(text, window, limit=6):
    """Keyword snippets that name a date inside the window, plus formal-hall weekday schedules."""
    found, seen = [], set()
    years = {d.year for d in window}
    for m in SCHEDULE.finditer(text):
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 80)
        chunk = " ".join(text[a:b].split())
        if chunk[:50] not in seen:
            seen.add(chunk[:50]); found.append("SCHEDULE: " + chunk)
    for m in KEYWORDS.finditer(text):
        a, b = max(0, m.start() - 90), min(len(text), m.end() + 130)
        chunk = " ".join(text[a:b].split())
        if not (dates_in(chunk, years) & window):
            continue
        key = chunk[:60]
        if key in seen:
            continue
        seen.add(key)
        found.append(chunk)
        if len(found) >= limit:
            break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/collect")
    ap.add_argument("--render", action="store_true", help="render empty pages with Playwright if available")
    a = ap.parse_args()
    out = pathlib.Path(a.out); shutil.rmtree(out, ignore_errors=True); (out / "pages").mkdir(parents=True)
    reg = json.loads((ROOT / "docs" / "sources.json").read_text())["sources"]
    today = dt.datetime.now(LONDON).date()
    lo, hi, ball_hi = today - dt.timedelta(days=1), today + dt.timedelta(days=14), today + dt.timedelta(days=400)
    readable = [s for s in reg if s["kind"] not in ("Instagram", "Facebook")]
    window = {today + dt.timedelta(days=k) for k in range(15)}
    city = json.loads((ROOT / "city.json").read_text())
    terms = [(dt.date.fromisoformat(t["from"]), dt.date.fromisoformat(t["to"]), t["name"]) for t in city.get("full_terms", [])]
    pdftotext = shutil.which("pdftotext")

    def page_text(r):
        if "pdf" in r["type"] or r["body"][:4] == b"%PDF":
            if not pdftotext:
                return ""
            p = subprocess.run([pdftotext, "-layout", "-", "-"], input=r["body"], capture_output=True, timeout=30)
            return p.stdout.decode("utf-8", "replace")
        return to_text(r["body"])

    cal_cache, cal_lock = {}, __import__("threading").Lock()

    def calendar(cid):
        with cal_lock:
            if cid in cal_cache:
                return cal_cache[cid]
            cal_cache[cid] = []
        rr = fetch(f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(cid)}/public/basic.ics")
        ev = ics_events(rr["body"].decode("utf-8", "replace"), lo, hi, ball_hi) if rr["code"] == 200 else []
        with cal_lock:
            cal_cache[cid] = ev
        return ev

    def one(i_s):
        try:
            return one_inner(i_s)
        except Exception as e:   # one bad source never stops the run
            i, s = i_s
            return {"college": s["college"], "name": s["name"], "kind": s["kind"], "url": s["url"], "followed": [],
                    "code": 0, "ok": False, "note": "collector error: " + type(e).__name__, "page_file": "", "snippets": [], "events": []}

    def one_inner(i_s):
        i, s = i_s
        rec = {"college": s["college"], "name": s["name"], "kind": s["kind"], "url": s["url"], "followed": []}
        r = fetch(s["url"])
        rec["code"] = r["code"]
        text = page_text(r) if r["code"] == 200 else ""
        rec["ok"] = r["code"] == 200 and len(text) > 200 and not re.search(r"(?i)raven|sign in to continue|log ?in required", text[:2000])
        rec["note"] = r.get("note") or ("" if rec["ok"] else ("empty or JavaScript-only page" if r["code"] == 200 else ""))
        texts = [(s["url"], text)]
        cal = calendar_ids(r["body"]) if r["body"] else set()
        if r["code"] == 200 and r["body"]:
            host = urllib.parse.urlparse(r["final"]).hostname
            picked = []
            for url, label in links(r["body"], r["final"]):
                if len(picked) >= 6 or url in picked or SKIP.search(url) or url.rstrip("/") == s["url"].rstrip("/"):
                    continue
                if urllib.parse.urlparse(url).hostname == host and (FOLLOW.search(url) or FOLLOW.search(label)):
                    picked.append(url)
            for url in picked:
                rr = fetch(url)
                if rr["code"] == 200:
                    texts.append((url, page_text(rr)))
                    cal |= calendar_ids(rr["body"])
                rec["followed"].append(f"{url} {rr['code']}")
        events = [dict(e, calendar=cid) for cid in sorted(cal) for e in calendar(cid)]
        (out / "pages" / f"{i:03d}.txt").write_text("\n\n".join(f"=== {u}\n{t}" for u, t in texts))
        rec["page_file"] = f"pages/{i:03d}.txt"
        seen_sn, rec["snippets"] = set(), []
        for u, t in texts:
            for sn in snippets(t, window):
                if sn[:60] not in seen_sn:
                    seen_sn.add(sn[:60]); rec["snippets"].append((u, sn))
        rec["events"] = events
        return rec

    with cf.ThreadPoolExecutor(16) as ex:
        recs = list(ex.map(one, enumerate(readable)))

    if a.render and shutil.which("node"):
        empty = [r for r in recs if r["code"] == 200 and not r["ok"]]
        if empty:
            js = out / "render.js"
            js.write_text("""const {chromium}=require('playwright');(async()=>{const b=await chromium.launch({headless:true});const out={};
for(const u of JSON.parse(process.argv[2])){try{const p=await b.newPage();await p.goto(u,{waitUntil:'networkidle',timeout:30000});out[u]=await p.innerText('body');await p.close();}catch(e){out[u]='';}}
console.log(JSON.stringify(out));await b.close();})();""")
            try:
                import os
                root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
                env = dict(os.environ, NODE_PATH=os.pathsep.join(x for x in (os.environ.get("NODE_PATH", ""), root) if x))
                p = subprocess.run(["node", str(js), json.dumps([r["url"] for r in empty])], capture_output=True, text=True, timeout=600, env=env)
                rendered = json.loads(p.stdout or "{}")
                for r in empty:
                    t = rendered.get(r["url"], "")
                    if len(t) > 200:
                        r["ok"], r["note"] = True, "rendered with headless Chromium"
                        pathlib.Path(out / r["page_file"]).write_text(f"=== {r['url']} (rendered)\n{t}")
                        r["snippets"] = [(r["url"], sn) for sn in snippets(t, window)]
            except Exception as e:
                print("render skipped:", e, file=sys.stderr)

    (out / "status.json").write_text(json.dumps([{k: r[k] for k in ("college", "name", "kind", "url", "ok", "code", "note", "followed", "page_file")} for r in recs], indent=1))
    lines = [f"# Collected {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}: window {today} to {today + dt.timedelta(days=14)}",
             f"{sum(r['ok'] for r in recs)} of {len(recs)} readable sources read. Full text of each page is in the file named after it.", ""]
    bad = [r for r in recs if not r["ok"]]
    if bad:
        lines += ["## Not readable", ""] + [f"- {r['college']} | {r['name']} | {r['url']} | {r['note'] or r['code']}" for r in bad] + [""]
    # Regular formal halls: registry pages that name fixed weekdays, expanded over the window inside Full Term.
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    in_term = {d: name for d in sorted(window) for a_, b_, name in terms if a_ <= d <= b_}
    lines += ["## Regular formal halls (registry weekdays, Full Term only)", ""]
    if not terms or not in_term and today > max(b_ for _, b_, _ in terms):
        lines.append("- WARNING: no Full Term dates in city.json cover today; add the next term's dates.")
    by_url = {r["url"]: r for r in recs}
    for s in readable:
        days = s.get("formal_days")
        if not days:
            continue
        r = by_url.get(s["url"], {})
        if not r.get("ok"):
            lines.append(f"- {s['college']} | page not readable today ({r.get('note') or r.get('code')}); keep yesterday's regular entries | {s['url']}")
            continue
        dates = [d for d in sorted(in_term) if names[d.weekday()] in days]
        if dates:
            lines.append(f"- {s['college']} | {', '.join(d.strftime('%a %d %b') for d in dates)} | {s.get('note', '')} | {s['url']}")
    lines += ["", "## Calendar events (window, plus balls up to a year ahead)", ""]
    shown = set()
    for r in recs:
        for e in sorted(r["events"], key=lambda e: e["start"]):
            key = (e["calendar"], e["start"], e["summary"])
            if key in shown:
                continue
            shown.add(key)
            extra = (" | " + e["status"] if e["status"] and e["status"] != "CONFIRMED" else "") + (" | weekly" if e["recurring"] else "")
            lines.append(f"- {r['college']} | {e['start'][:16]} | {e['summary']} | {e['location']}{extra} | from {r['url']}")
    lines += ["", "## Page snippets with event words and dates", ""]
    for r in recs:
        if r["snippets"]:
            lines.append(f"### {r['college']} | {r['name']} | {r['page_file']}")
            lines += [f"- {sn}  ({u})" for u, sn in r["snippets"]]
    (out / "digest.md").write_text("\n".join(lines) + "\n")
    size = (out / "digest.md").stat().st_size
    print(f"{sum(r['ok'] for r in recs)}/{len(recs)} readable, {len(shown)} calendar events, digest {size // 1024} KB (about {size // 4000}k tokens) at {out / 'digest.md'}")


if __name__ == "__main__":
    main()
