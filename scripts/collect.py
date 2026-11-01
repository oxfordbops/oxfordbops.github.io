#!/usr/bin/env python3
"""Fetch every readable registered source once and write a compact digest for the daily routine.

    python3 scripts/collect.py [--out /tmp/collect] [--render]

For each registry source that is not Instagram or Facebook it:
  - fetches the page (ordinary browser User-Agent; one retry on a timeout or connection error, never on a refusal;
    a 45 s and 8 MB cap per response; the declared character set is honoured),
  - follows up to 6 same-site links whose address or text looks like events, ents, calendar, termcard,
    formal hall, dining or balls,
  - reads embedded Google Calendars as their public iCal feeds, expanding recurring events (with exclusions,
    moved occurrences and the original timezone) into the window,
  - reads linked PDFs with pdftotext when it is installed,
  - with --render, renders JavaScript-only pages with headless Chromium (Playwright, if installed).

Output in --out:
  digest.md     what the routine reads: warnings, unreadable sources, regular formal halls expanded from the
                registry's weekdays inside Full Term, calendar events, and dated snippets
  status.json   one record per registry URL: ok, code, note, followed links
  pages/*.txt   full text of every page fetched, for checking a snippet in context
The routine still decides what counts; this script only gathers. Recurrences use python-dateutil when it is
installed (CI and the routine install it); without it a simpler expansion is used and the digest says so.
"""
import argparse, base64, concurrent.futures as cf, datetime as dt, html, json, os, pathlib, re, shutil, subprocess, sys, threading, time
import urllib.parse, urllib.request
from zoneinfo import ZoneInfo

try:
    from dateutil.rrule import rrulestr
except ImportError:   # pragma: no cover - exercised only where dateutil is missing
    rrulestr = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_BYTES, DEADLINE = 8_000_000, 45
FOLLOW = re.compile(r"event|ents?\b|entz|calendar|term-?card|formal|dining|hall|whats-?on|ball|social", re.I)
SKIP = re.compile(r"login|signin|sign-in|raven|shibboleth|webauth|\.(jpg|jpeg|png|gif|svg|zip|docx?)$|mailto:|tel:", re.I)
KEYWORDS = re.compile(r"\b(bops?|super ?bop|formals?|formal hall|super ?hall|guest night|swap|feast|may ball|june event|commem|ball\b|halloween|bonfire|christmas|burns|diwali|bar night|party|ents night)\b", re.I)
BALL = re.compile(r"\bmay ball\b|\bjune event\b|\bcommem|\bball\b", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(\d{4}))?|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", re.I)
NUMERIC = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
SCHEDULE = re.compile(r"\bformal(?:s| hall)?\b[^.\n]{0,80}\b(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|every (?:night|evening|day)|nights? a week|times a week)\b|\b(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b[^.\n]{0,60}\bformal", re.I)
EVENTISH_KINDS = {"JCR events", "MCR events", "Termcard", "College events", "Ents site", "Formal hall"}


# ---------- fetching ----------

def fetch(url, timeout=20):
    r = _fetch(url, timeout)
    if r["code"] == 0:   # timeout or connection error: one retry, a little later; a refusal is never retried
        time.sleep(2)
        r = _fetch(url, timeout + 10)
    return r


def _fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,text/calendar,application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            start, chunks, size, truncated = time.monotonic(), [], 0, False
            while True:
                if time.monotonic() - start > DEADLINE:
                    truncated = True; break
                c = r.read(65536)
                if not c:
                    break
                chunks.append(c); size += len(c)
                if size > MAX_BYTES:
                    truncated = True; break
            return {"code": r.status, "final": r.geturl(), "type": r.headers.get("Content-Type", ""),
                    "charset": r.headers.get_content_charset(), "body": b"".join(chunks), "truncated": truncated}
    except urllib.error.HTTPError as e:
        return {"code": e.code, "final": url, "type": "", "charset": None, "body": b"", "note": f"HTTP {e.code}", "truncated": False}
    except Exception as e:
        return {"code": 0, "final": url, "type": "", "charset": None, "body": b"", "note": type(e).__name__ + ": " + str(e)[:80], "truncated": False}


def decode(body, charset=None):
    """Bytes to text using the declared charset (HTTP header, then <meta>), falling back to UTF-8 and Windows-1252."""
    if not charset:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', body[:4096], re.I)
        charset = m.group(1).decode("ascii", "ignore") if m else None
    for enc in (charset, "utf-8"):
        if enc:
            try:
                return body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                pass
    return body.decode("cp1252", "replace")


def to_text(raw, charset=None):
    s = decode(raw, charset) if isinstance(raw, bytes) else raw
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|section|article)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def links(raw, base, charset=None):
    out = []
    page = decode(raw, charset) if isinstance(raw, bytes) else raw
    for m in re.finditer(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', page):
        href, text = html.unescape(m.group(1)), html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        url = urllib.parse.urljoin(base, href).split("#")[0]
        if url.startswith("http"):
            out.append((url, " ".join(text.split())[:80]))
    return out


def calendar_ids(raw):
    s = urllib.parse.unquote(html.unescape(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw))
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


# ---------- iCal ----------

def _props(block):
    """Property name -> list of (params, value); repeated properties (EXDATE, RDATE) keep every line."""
    f = {}
    for line in block.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            name, _, params = k.partition(";")
            f.setdefault(name.upper(), []).append((params, v.strip()))
    return f


def _when(params, val):
    """(datetime, all_day): UTC stays UTC, TZID keeps its zone, floating times are London."""
    if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", val):
        return dt.datetime.strptime(val[:8], "%Y%m%d").replace(tzinfo=LONDON), True
    if val.endswith("Z"):
        return dt.datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc), False
    tz = re.search(r"TZID=\"?([^;:\"]+)", params)
    try:
        zone = ZoneInfo(tz.group(1)) if tz else LONDON
    except Exception:
        zone = LONDON
    return dt.datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone), False


def _text(f, name, n):
    return f.get(name, [("", "")])[0][1].replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")[:n]


def _simple_rrule(start, rule, lo_dt, hi_dt, exdates):
    """Fallback without dateutil: DAILY/WEEKLY with INTERVAL, BYDAY, COUNT, UNTIL; weeks anchored to start's week."""
    r = dict(x.split("=", 1) for x in rule.split(";") if "=" in x)
    freq, step = r.get("FREQ"), int(r.get("INTERVAL", "1") or 1)
    days = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    byday = [d[-2:] for d in r.get("BYDAY", "").split(",") if d] or [days[start.weekday()]]
    until = _when("", r["UNTIL"])[0] if "UNTIL" in r else None
    count = int(r["COUNT"]) if "COUNT" in r else None
    week0 = start.date() - dt.timedelta(days=start.weekday())
    out, n, day = [], 0, start.date()
    while (count is None or n < count) and day <= hi_dt.date() and (until is None or day <= until.date()):
        if freq == "DAILY":
            ok = (day - start.date()).days % step == 0
        elif freq == "WEEKLY":
            ok = days[day.weekday()] in byday and ((day - week0).days // 7) % step == 0
        else:
            ok = False
        if ok:
            n += 1
            occ = start.replace(year=day.year, month=day.month, day=day.day)
            if occ >= lo_dt and occ not in exdates:
                out.append(occ)
        day += dt.timedelta(days=1)
    return out


def ics_events(text, lo, hi, ball_hi):
    """Events whose London date falls in [lo, hi] (balls up to ball_hi), with recurrences expanded."""
    text = re.sub(r"\r?\n[ \t]", "", text)   # unfold
    blocks = [_props(b) for b in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)]
    overrides = {}   # UID -> {original start: override block}
    for f in blocks:
        if "RECURRENCE-ID" in f and "UID" in f:
            try:
                overrides.setdefault(f["UID"][0][1], {})[_when(*f["RECURRENCE-ID"][0])[0]] = f
            except Exception:
                pass
    out = []

    def emit(f, start, all_day, recurring):
        summary = _text(f, "SUMMARY", 100)
        london = start.astimezone(LONDON)
        limit = ball_hi if BALL.search(summary) else hi
        if not (lo <= london.date() <= limit):
            return
        out.append({"start": london.date().isoformat() if all_day else london.isoformat(timespec="minutes"), "all_day": all_day,
                    "summary": summary, "location": _text(f, "LOCATION", 60), "status": _text(f, "STATUS", 20).upper(), "recurring": recurring})

    for f in blocks:
        if "DTSTART" not in f or "RECURRENCE-ID" in f:
            continue
        try:
            start, all_day = _when(*f["DTSTART"][0])
        except Exception:
            continue
        uid = f.get("UID", [("", "")])[0][1]
        moved = overrides.get(uid, {})
        if "RRULE" not in f:
            emit(f, start, all_day, False)
            continue
        lo_dt = dt.datetime.combine(lo - dt.timedelta(days=1), dt.time(), LONDON)
        hi_dt = dt.datetime.combine(max(hi, ball_hi) + dt.timedelta(days=1), dt.time(), LONDON)
        exdates = set()
        for params, val in f.get("EXDATE", []):
            for v in val.split(","):
                try:
                    exdates.add(_when(params, v)[0])
                except Exception:
                    pass
        try:
            if rrulestr:
                rules = [f"RRULE:{f['RRULE'][0][1]}"]
                rules += [f"RDATE:{v}" for p, v in f.get("RDATE", []) if "PERIOD" not in p.upper() and "TZID" not in p.upper()]
                rs = rrulestr("\n".join(rules), dtstart=start, forceset=True)
                for x in exdates:
                    rs.exdate(x)
                occs = rs.between(lo_dt, hi_dt, inc=True)
            else:
                occs = _simple_rrule(start, f["RRULE"][0][1], lo_dt, hi_dt, exdates)
        except Exception:
            occs = []
        for occ in occs:
            if occ in moved:   # this occurrence was moved or cancelled; the override is emitted below
                continue
            emit(f, occ, all_day, True)
    for uid, moved in overrides.items():
        for f in moved.values():
            if "DTSTART" in f and _text(f, "STATUS", 20).upper() != "CANCELLED":
                try:
                    s, ad = _when(*f["DTSTART"][0])
                    emit(f, s, ad, True)
                except Exception:
                    pass
    return out


# ---------- snippets ----------

def dates_in(chunk, years):
    out = set()
    for m in DAY_MONTH.finditer(chunk):
        if m.group(1):
            d, mon, y = m.group(1), m.group(2), m.group(3)
        else:
            d, mon, y = m.group(5), m.group(4), m.group(6)
        for yy in ([int(y)] if y else years):
            try:
                out.add(dt.date(yy, MONTHS[mon[:3].lower()], int(d)))
            except ValueError:
                pass
    for m in NUMERIC.finditer(chunk):
        try:
            if m.group(4):
                out.add(dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6))))
            else:
                y = int(m.group(3)); y = y + 2000 if y < 100 else y
                out.add(dt.date(y, int(m.group(2)), int(m.group(1))))   # UK order: day/month/year
        except ValueError:
            pass
    return out


def snippets(text, window, limit=6, ball_until=None):
    """Keyword snippets that name a date inside the window (balls: up to ball_until), plus formal-hall schedules."""
    found, seen = [], set()
    lo, hi = min(window), max(window)
    years = {lo.year, hi.year} | ({ball_until.year} if ball_until else set())
    for m in SCHEDULE.finditer(text):
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 80)
        chunk = " ".join(text[a:b].split())
        if chunk[:50] not in seen:
            seen.add(chunk[:50]); found.append("SCHEDULE: " + chunk)
    for m in KEYWORDS.finditer(text):
        a, b = max(0, m.start() - 90), min(len(text), m.end() + 130)
        chunk = " ".join(text[a:b].split())
        dates = dates_in(chunk, years)
        until = ball_until if (ball_until and BALL.search(m.group(0))) else hi
        if not any(lo <= d <= until for d in dates):
            continue
        if chunk[:60] in seen:
            continue
        seen.add(chunk[:60]); found.append(chunk)
        if len(found) >= limit:
            break
    return found


# ---------- rendering ----------

RENDER_JS = r"""const {chromium}=require('playwright');(async()=>{const b=await chromium.launch({headless:true});
for(const u of JSON.parse(process.argv[2])){let p;try{p=await b.newPage();await p.goto(u,{waitUntil:'networkidle',timeout:30000});
const t=await p.innerText('body');const h=await p.content();console.log(JSON.stringify({u,t,h}));}catch(e){console.log(JSON.stringify({u,t:'',h:''}));}
finally{if(p)await p.close().catch(()=>{});}}await b.close();})();"""


def render(urls, workdir, budget=900):
    """Rendered {url: (text, html)} for each URL, read line by line so a stall loses only the pages after it."""
    js = workdir / "render.js"; js.write_text(RENDER_JS)
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = dict(os.environ, NODE_PATH=os.pathsep.join(x for x in (os.environ.get("NODE_PATH", ""), root) if x))
    got = {}
    p = subprocess.Popen(["node", str(js), json.dumps(urls)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    t0 = time.monotonic()
    try:
        for line in p.stdout:
            try:
                o = json.loads(line); got[o["u"]] = (o["t"], o["h"])
            except Exception:
                pass
            if time.monotonic() - t0 > budget:
                break
    finally:
        p.kill()
    return got


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/collect")
    ap.add_argument("--render", action="store_true", help="render JavaScript-only pages with Playwright if available")
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
    warnings = []
    if not pdftotext:
        warnings.append("pdftotext is not installed, so PDF termcards were not read (apt-get install poppler-utils).")
    if not rrulestr:
        warnings.append("python-dateutil is not installed; recurring calendar events used a simpler expansion (python3 -m pip install python-dateutil).")

    def page_text(r):
        try:
            if "pdf" in r["type"] or r["body"][:4] == b"%PDF":
                if not pdftotext or r.get("truncated"):
                    return ""
                p = subprocess.run([pdftotext, "-layout", "-", "-"], input=r["body"], capture_output=True, timeout=30)
                return p.stdout.decode("utf-8", "replace")
            return to_text(r["body"], r.get("charset"))
        except Exception:   # one bad document never loses the rest of the source
            return ""

    cal_cache, cal_locks, cal_guard = {}, {}, threading.Lock()

    def calendar(cid):
        """(feed HTTP status, events). Each calendar is fetched once, even when several sources embed it."""
        with cal_guard:
            lock = cal_locks.setdefault(cid, threading.Lock())
        with lock:
            if cid not in cal_cache:
                rr = fetch(f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(cid)}/public/basic.ics")
                ev = []
                if rr["code"] == 200 and not rr["truncated"]:
                    try:
                        ev = ics_events(decode(rr["body"], "utf-8"), lo, hi, ball_hi)
                    except Exception:
                        ev = []
                cal_cache[cid] = (rr["code"], ev)
            return cal_cache[cid]

    def one(i_s):
        try:
            return one_inner(i_s)
        except Exception as e:   # one bad source never stops the run
            i, s = i_s
            return {"college": s["college"], "name": s["name"], "kind": s["kind"], "url": s["url"], "followed": [],
                    "code": 0, "ok": False, "note": "collector error: " + type(e).__name__, "page_file": "", "snippets": [], "events": [], "datedless": False}

    def one_inner(i_s):
        i, s = i_s
        rec = {"college": s["college"], "name": s["name"], "kind": s["kind"], "url": s["url"], "followed": []}
        r = fetch(s["url"])
        rec["code"] = r["code"]
        text = page_text(r) if r["code"] == 200 else ""
        login = re.search(r"(?i)raven|sign in to continue|log ?in required", text[:2000])
        rec["ok"] = r["code"] == 200 and len(text) > 200 and not login
        rec["note"] = r.get("note") or ("" if rec["ok"] else ("login page" if login else "empty or JavaScript-only page" if r["code"] == 200 else ""))
        if r.get("truncated"):
            rec["note"] = (rec["note"] + "; " if rec["note"] else "") + "response cut off at the size or time limit"
        texts = [(s["url"], text)]
        cal = (calendar_ids(r["body"]) if r["body"] else set()) | calendar_ids(s["url"])
        if r["code"] == 200 and r["body"] and not login:
            host = urllib.parse.urlparse(r["final"]).hostname
            picked = []
            for url, label in links(r["body"], r["final"], r.get("charset")):
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
        feeds = {cid: calendar(cid) for cid in sorted(cal)}
        rec["events"] = [dict(e, calendar=cid) for cid, (code, evs) in feeds.items() for e in evs]
        bad_feeds = [cid for cid, (code, _) in feeds.items() if code != 200]
        if bad_feeds:
            rec["note"] = (rec["note"] + "; " if rec["note"] else "") + f"calendar feed unreadable: {', '.join(bad_feeds)}"
        if "calendar.google.com" in s["url"] and feeds and not bad_feeds:   # the embed page is JavaScript, but its feed was read
            rec["ok"], rec["note"] = True, "read as its iCal feed"
        (out / "pages" / f"{i:03d}.txt").write_text("\n\n".join(f"=== {u}\n{t}" for u, t in texts))
        rec["page_file"] = f"pages/{i:03d}.txt"
        seen_sn, rec["snippets"] = set(), []
        for u, t in texts:
            for sn in snippets(t, window, ball_until=ball_hi):
                if sn[:60] not in seen_sn:
                    seen_sn.add(sn[:60]); rec["snippets"].append((u, sn))
        # A readable events page with no dates and no calendar is probably filled in by JavaScript.
        rec["datedless"] = rec["ok"] and s["kind"] in EVENTISH_KINDS and not cal and not any(dates_in(t, {today.year, today.year + 1}) for _, t in texts)
        return rec

    with cf.ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(one, enumerate(readable)))

    if a.render and shutil.which("node"):
        targets = [r for r in recs if (r["code"] == 200 and not r["ok"] and "login" not in r["note"]) or r.get("datedless")][:40]
        if targets:
            try:
                got = render([r["url"] for r in targets], out)
                for r in targets:
                    t, h = got.get(r["url"], ("", ""))
                    if len(t) <= 200:
                        continue
                    r["ok"], r["note"] = True, "rendered with headless Chromium"
                    pathlib.Path(out / r["page_file"]).write_text(f"=== {r['url']} (rendered)\n{t}")
                    r["snippets"] = [(r["url"], sn) for sn in snippets(t, window, ball_until=ball_hi)]
                    for cid in calendar_ids(h):
                        code, evs = calendar(cid)
                        r["events"] += [dict(e, calendar=cid) for e in evs]
            except Exception as e:
                warnings.append(f"rendering skipped ({type(e).__name__}).")

    ok = sum(r["ok"] for r in recs)
    if ok < len(recs) / 2:
        warnings.append(f"only {ok} of {len(recs)} readable sources could be read; coverage has collapsed, check the network or the registry.")
    last_end = max((b_ for _, b_, _ in terms), default=None)
    if not terms or today > last_end:
        warnings.append("no Full Term dates in city.json cover today; add the next terms' dates.")
    elif (last_end - today).days < 45:
        warnings.append(f"the last Full Term in city.json ends {last_end}; add the next year's terms.")

    (out / "status.json").write_text(json.dumps([{k: r[k] for k in ("college", "name", "kind", "url", "ok", "code", "note", "followed", "page_file")} for r in recs], indent=1))
    lines = [f"# Collected {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}: window {today} to {today + dt.timedelta(days=14)}",
             f"{ok} of {len(recs)} readable sources read. Full text of each page is in the file named after it.", ""]
    if warnings:
        lines += ["## Warnings (report each in REGISTRY)", ""] + [f"- WARNING: {w}" for w in warnings] + [""]
    bad = [r for r in recs if not r["ok"]]
    if bad:
        lines += ["## Not readable", ""] + [f"- {r['college']} | {r['name']} | {r['url']} | {r['note'] or r['code']}" for r in bad] + [""]

    # Regular formal halls: registry pages that name fixed weekdays, expanded over the window inside Full Term.
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    full = {"Mon": "monday", "Tue": "tuesday", "Wed": "wednesday", "Thu": "thursday", "Fri": "friday", "Sat": "saturday", "Sun": "sunday"}
    in_term = [d for d in sorted(window) if any(a_ <= d <= b_ for a_, b_, _ in terms)]
    lines += ["## Regular formal halls (registry weekdays, Full Term only)", ""]
    by_url = {r["url"]: r for r in recs}
    for s in readable:
        days = s.get("formal_days")
        if not days:
            continue
        r = by_url.get(s["url"], {})
        if not r.get("ok"):
            lines.append(f"- {s['college']} | page not readable today ({r.get('note') or r.get('code')}); keep the regular nights already listed | {s['url']}")
            continue
        try:
            page = (out / r["page_file"]).read_text().lower()
        except Exception:
            page = ""
        every = len(days) == 7 and re.search(r"every (evening|night|day)|each (evening|night)|nightly", page)
        missing = [] if every else [d for d in days if full[d] not in page]
        if missing or re.search(r"\b(suspended|no formal halls?|not (?:be )?running|cancelled)\b", page):
            lines.append(f"- SCHEDULE CHECK {s['college']}: the registry says {', '.join(days)}; the page "
                         + (f"no longer names {', '.join(missing)}" if missing else "mentions a suspension or cancellation")
                         + f". Read it, list only the nights it states, and report it in REGISTRY | {s['url']}")
            continue
        dates = [d for d in in_term if names[d.weekday()] in days]
        if dates:
            lines.append(f"- {s['college']} | {', '.join(d.strftime('%a %d %b') for d in dates)} | {s.get('note', '')} | {s['url']}")

    lines += ["", "## Calendar events (window, plus balls up to a year ahead; 'date only' means no time was given)", ""]
    shown = set()
    for r in recs:
        for e in sorted(r["events"], key=lambda e: e["start"]):
            key = (e["calendar"], e["start"], e["summary"])
            if key in shown:
                continue
            shown.add(key)
            extra = (" | date only" if e["all_day"] else "") + (" | " + e["status"] if e["status"] and e["status"] != "CONFIRMED" else "") + (" | recurring" if e["recurring"] else "")
            lines.append(f"- {r['college']} | {e['start']} | {e['summary']} | {e['location']}{extra} | from {r['url']}")
    lines += ["", "## Page snippets with event words and dates", ""]
    for r in recs:
        if r["snippets"]:
            lines.append(f"### {r['college']} | {r['name']} | {r['page_file']}")
            lines += [f"- {sn}  ({u})" for u, sn in r["snippets"]]
    (out / "digest.md").write_text("\n".join(lines) + "\n")
    size = (out / "digest.md").stat().st_size
    print(f"{ok}/{len(recs)} readable, {len(shown)} calendar events, {len(warnings)} warnings, digest {size // 1024} KB (about {size // 4000}k tokens) at {out / 'digest.md'}")


if __name__ == "__main__":
    main()
