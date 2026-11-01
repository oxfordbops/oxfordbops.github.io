#!/usr/bin/env python3
"""Mechanical safety scan of docs/events.json. Judgement (who runs an event, whether it is in a college or university space,
whether it is safe, whether a cross-college listing is really that college's away leg) belongs to the language model in the
weekly routine and the daily check, which must quote its evidence in each listing's `evidence`. This scan checks only what
code can check reliably: links, structure, personal data, tampering, that the model's quotes state the listing's date and
time, and a short backstop of unambiguous danger words.

    python3 scripts/safety_scan.py            # report violations as JSON lines; exit 1 if any
    python3 scripts/safety_scan.py --fix      # also remove every violating entry from docs/events.json (the routine runs this)

Each violation names its rule: organiser, place, link, danger, personal, tampering. The weekly routine reports removed
entries in its FLAGGED line, so a person sees them; nothing flagged is ever published. tests/test_safety.py runs the same
scan on the committed data and checks the scanner itself on known good and bad examples.
"""
import ipaddress, json, pathlib, re, sys, unicodedata
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly", "is.gd", "rebrand.ly", "linktr.ee", "lnkd.in", "cutt.ly", "shorturl.at",
              "forms.gle", "tiny.cc", "rb.gy", "s.id", "qr.link", "beacons.ai", "linkin.bio"}
TICKETING = {"fixr.co", "ra.co", "eventbrite.co.uk", "eventbrite.com", "skiddle.com", "dice.fm", "ticketmaster.co.uk", "seetickets.com",
             "tickettailor.com", "luma.com", "lu.ma", "wegottickets.com", "twickets.live", "stubhub.co.uk", "viagogo.co.uk", "ticketswap.com"}
FORMS = re.compile(r"docs\.google\.com/forms|forms\.office\.com|forms\.microsoft\.com|typeform\.com|jotform\.com|surveymonkey\.com|tally\.so", re.I)
DOWNLOADS = re.compile(r"\.(exe|zip|rar|7z|dmg|apk|msi|bat|cmd|scr|js|jar|iso|ps1|sh|vbs|docm|xlsm)$", re.I)

# Backstop only: words that are never part of a safe listing, whatever the context. Judging safety is the model's job.
BACKSTOP = re.compile(r"\b(cocaine|mdma|ecstasy|ketamine|lsd|nitrous oxide|magic mushrooms|initiations?|hazing|drinking games?|"
                      r"strip ?(club|tease|poker)|lap ?danc\w*|escorts?|fake ids?|underage drinking|fight club|weapons?)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b|\+44\s?\(?0?\)?\s?[12]\d{2,3}\s?\d{3}\s?\d{3,4}\b|\b0[12]\d{2,3}\s?\d{3}\s?\d{3,4}\b")
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
MARKUP = re.compile(r"<\s*/?\s*[a-z!]|javascript:|data:text|on\w+\s*=", re.I)
TEXT_FIELDS = ("title", "details", "venue", "host", "price", "guests", "dress", "society")
MAX_LEN = {"title": 160, "details": 320, "venue": 160, "host": 160, "price": 120, "guests": 200, "dress": 120, "society": 80}


def _host(u):
    return (urlparse(u).hostname or "").lower()


class Scanner:
    def __init__(self, city, registry, data_sources, evidence_required=False):
        self.city = city
        self.uni = city.get("university_domain", "")
        self.colleges = list(city["colleges"])
        self.venues = [v.lower() for v in city.get("university_venues", [])]
        self.societies = registry.get("societies", [])
        self.reg = registry["sources"] + self.societies
        self.reg_by_url = {s["url"]: s for s in self.reg}
        self.vetted = {_host(s["url"]) for s in self.reg if s["kind"] not in ("Instagram", "Facebook")}
        self.src = {s["slug"]: s for s in data_sources} if isinstance(data_sources, list) else {}
        self.evidence_required = evidence_required
        self.ball_hosts = {_host(s["url"]) for s in self.src.values() if s.get("kind") == "Ball site" and self._linked_ok(s)}

    MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    def states_date(self, quote, d, weekly):
        q = quote.lower()
        mon = self.MONTHS[d.month - 1]
        pats = [d.isoformat(), d.strftime("%Y%m%d"), d.strftime("%d/%m"), f"{d.day}/{d.month}/",
                rf"\b0?{d.day}(?:st|nd|rd|th)?(?: of)? {mon[:3]}", rf"\b{mon[:3]}\w* 0?{d.day}(?:st|nd|rd|th)?\b", d.strftime("%d.%m.%Y")]
        if any(re.search(p, q) for p in pats):
            return True
        return weekly and re.search(rf"\b{self.DAYS[d.weekday()]}s?\b", q) is not None   # a regular schedule names the weekday

    def states_time(self, quote, t):
        q = quote.lower().replace(" ", "")
        h12 = t.hour % 12 or 12
        pats = [f"{t.hour:02d}:{t.minute:02d}", f"{t.hour}:{t.minute:02d}", f"{t.hour:02d}.{t.minute:02d}", f"{t.hour:02d}{t.minute:02d}",
                f"{h12}.{t.minute:02d}", f"{h12}:{t.minute:02d}"]
        if t.minute == 0:
            pats += [f"{h12}pm", f"{h12}am", f"{h12}-", f"{h12}–", f"{h12}to", f"{h12}p.m."]
        return any(p in q for p in pats)

    def evidence_problems(self, b):
        import datetime as dt
        ev = b.get("evidence")
        if not isinstance(ev, dict) or not isinstance(ev.get("quote"), str) or len(ev["quote"].strip()) < 12:
            return [("evidence", "no quote from the source stating the event")]
        out = []
        q = ev["quote"]
        if len(q) > 400 or MARKUP.search(q) or HIDDEN.search(q):
            out.append(("evidence", "the quote is too long or contains markup"))
        start = dt.datetime.fromisoformat(b["starts_at"].replace("Z", "+00:00")).astimezone(LONDON)
        weekly = b.get("kind") == "formal" and b.get("special") is False
        if not self.states_date(q, start.date(), weekly):
            out.append(("evidence", f"the quote does not state {start:%a %d %b}"))
        if "time not stated" not in (b.get("details") or "").lower() and not self.states_time(q + " " + str(ev.get("time") or ""), start):
            out.append(("evidence", f"the quote does not state {start:%H:%M}"))
        if b.get("kind") not in ("formal", "ball") and not (isinstance(ev.get("where"), str) and ev["where"].strip()):
            out.append(("evidence", "no quote saying where it is held"))
        return out

    def on_uni(self, h):
        return bool(self.uni) and (h == self.uni or h.endswith("." + self.uni))

    def _linked_ok(self, s):
        lf = _host(s.get("linked_from", ""))
        return self.on_uni(lf) or lf in self.vetted

    def link_problem(self, u):
        p = urlparse(u or "")
        h = (p.hostname or "").lower()
        if p.scheme != "https":
            return "not https"
        if p.username or p.password or p.port not in (None, 443):
            return "credentials or a port in the link"
        try:
            ipaddress.ip_address(h)
            return "raw IP address"
        except ValueError:
            pass
        if "xn--" in h or any(ord(c) > 127 for c in h):
            return "internationalised (look-alike) domain"
        if h in SHORTENERS:
            return "link shortener"
        if any(h == t or h.endswith("." + t) for t in TICKETING):
            return "ticketing or resale site"
        if FORMS.search(u):
            return "a form"
        if DOWNLOADS.search(p.path):
            return "a file download"
        return None

    def check(self, b):
        """Violations of one listing, as (rule, reason) pairs; empty means safe to publish."""
        out = []
        kind = b.get("kind", "bop")
        s = self.src.get(b.get("source"), {})
        reg = self.reg_by_url.get(s.get("url"))
        # Links.
        u = b.get("url", "")
        why = self.link_problem(u)
        if why:
            out.append(("link", f"{u}: {why}"))
        else:
            h = _host(u)
            if not (self.on_uni(h) or h in self.vetted or h == "calendar.google.com"
                    or (h.endswith("instagram.com") and s.get("kind") == "Instagram")
                    or (kind == "ball" and h in self.ball_hosts)):
                out.append(("link", f"{h} is neither the university's domain nor a vetted page"))
        # Organiser (structure only; the model judges who really runs it and quotes it in evidence): the source is in the registry,
        # a society event cites its own society, a ball site is linked from an official page, and the press is never the only source.
        if kind == "society":
            if not reg or reg not in self.societies or reg["society"] != b.get("society"):
                if not (s.get("kind") == "Instagram" and reg):
                    out.append(("organiser", "a society event must cite its own registered society page"))
        elif kind == "ball" and s.get("kind") == "Ball site":
            if not self._linked_ok(s):
                out.append(("organiser", "ball site without an official page linking to it"))
        elif not reg:
            out.append(("organiser", "the source is not in the registry"))
        elif reg.get("kind") == "Student press":
            out.append(("organiser", "the student press reports events; it does not run them, so it cannot be the only source"))
        if kind != "society" and b.get("college") not in self.colleges:
            out.append(("place", "a college event must name its college"))
        # Evidence: the model's own quotes from the source. Code checks only that they exist and state this date and time.
        if self.evidence_required:
            out += self.evidence_problems(b)
        # Content.
        for f in TEXT_FIELDS:
            v = str(b.get(f) or "")
            m = BACKSTOP.search(v)
            if m:
                out.append(("danger", f"{f} says {m.group(0)!r}"))
            if EMAIL.search(v):
                out.append(("personal", f"{f} has an email address"))
            if PHONE.search(v):
                out.append(("personal", f"{f} has a phone number"))
            if f in ("details", "venue", "host") and POSTCODE.search(v) and not any(c.lower() in v.lower() for c in self.colleges):
                out.append(("personal", f"{f} has a postcode that is not a college's"))
            if HIDDEN.search(v):
                out.append(("tampering", f"{f} has hidden or direction-control characters"))
            if MARKUP.search(v):
                out.append(("tampering", f"{f} has markup or script"))
            if len(v) > MAX_LEN.get(f, 300):
                out.append(("tampering", f"{f} is {len(v)} characters long"))
            if any(unicodedata.category(c) == "Cc" for c in v):
                out.append(("tampering", f"{f} has control characters"))
        return out


def load():
    city = json.loads((ROOT / "city.json").read_text())
    registry = json.loads((ROOT / "docs" / "sources.json").read_text())
    data = json.loads((ROOT / "docs" / "events.json").read_text())
    return city, registry, data


def main():
    city, registry, data = load()
    sc = Scanner(city, registry, data.get("sources", []), evidence_required=(data.get("run") or {}).get("version", 1) >= 2)
    keep, flagged = [], []
    for b in data.get("bops", []):
        v = sc.check(b)
        if v:
            flagged.append({"title": b.get("title"), "college": b.get("college"), "society": b.get("society"), "starts_at": b.get("starts_at"),
                            "violations": [f"{r}: {w}" for r, w in v]})
        else:
            keep.append(b)
    for f in flagged:
        print(json.dumps(f, ensure_ascii=False))
    print(f"safety scan: {len(keep)} safe, {len(flagged)} flagged", file=sys.stderr)
    if "--fix" in sys.argv and flagged:
        p = ROOT / "docs" / "events.json"; text = p.read_text()
        indent = len(text.split("\n", 1)[1]) - len(text.split("\n", 1)[1].lstrip(" ")) if "\n" in text else 1
        data["bops"] = keep
        for s in data.get("sources", []) if isinstance(data.get("sources"), list) else []:
            s["found"] = sum(1 for b in keep if b.get("source") == s["slug"])
        p.write_text(json.dumps(data, indent=indent or 1, ensure_ascii=False) + "\n")
        print(f"removed {len(flagged)} flagged entries from docs/events.json", file=sys.stderr)
    sys.exit(1 if flagged and "--fix" not in sys.argv else 0)


if __name__ == "__main__":
    main()
