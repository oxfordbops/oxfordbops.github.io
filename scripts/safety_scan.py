#!/usr/bin/env python3
"""Safety scan of docs/events.json: every listing must be certainly run by a college or university body (or a registered
society), certainly held in a college or university space, link only to vetted pages, and be completely safe.

    python3 scripts/safety_scan.py            # report violations as JSON lines; exit 1 if any
    python3 scripts/safety_scan.py --fix      # also remove every violating entry from docs/events.json (the routine runs this)

Each violation names its rule: organiser, place, link, danger, personal, tampering. The weekly routine reports removed
entries in its FLAGGED line, so a person sees them; nothing flagged is ever published. tests/test_safety.py runs the same
scan on the committed data and checks the scanner itself on known good and bad examples.
"""
import ipaddress, json, pathlib, re, sys, unicodedata
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly", "is.gd", "rebrand.ly", "linktr.ee", "lnkd.in", "cutt.ly", "shorturl.at",
              "forms.gle", "tiny.cc", "rb.gy", "s.id", "qr.link", "beacons.ai", "linkin.bio"}
TICKETING = {"fixr.co", "ra.co", "eventbrite.co.uk", "eventbrite.com", "skiddle.com", "dice.fm", "ticketmaster.co.uk", "seetickets.com",
             "tickettailor.com", "luma.com", "lu.ma", "wegottickets.com", "twickets.live", "stubhub.co.uk", "viagogo.co.uk", "ticketswap.com"}
FORMS = re.compile(r"docs\.google\.com/forms|forms\.office\.com|forms\.microsoft\.com|typeform\.com|jotform\.com|surveymonkey\.com|tally\.so", re.I)
DOWNLOADS = re.compile(r"\.(exe|zip|rar|7z|dmg|apk|msi|bat|cmd|scr|js|jar|iso|ps1|sh|vbs|docm|xlsm)$", re.I)

# Words that make an event unsafe to publish, by category. Matched on whole words, case-insensitively, in every text field.
DANGER = {
    "drugs": r"cocaine|coke|mdma|molly|ecstasy|ketamine|ket|lsd|acid trip|shrooms|magic mushrooms|psilocybin|weed|cannabis|marijuana|edibles|"
             r"pills|nitrous|nos|balloons|poppers|spice|xanax|drugs?|420",
    "weapons": r"weapons?|knife|knives|firearms?|guns? (?:range|club|night)|machetes?|pepper spray|tasers?|airsoft|paintball",
    "hazing": r"initiations?|initiated|hazing|ragging|forfeits?|punishment drinks?|fines night",
    "drinking": r"drinking games?|pint challenge|boat race|chunder(ing)?|spirit races?|downing contest|shot challenge|shotgun(ning)?|"
                r"bottomless|free bar all night|unlimited drinks?|all you can drink|pub crawl|bar crawl|sesh(ing)?|piss(ed)? up|get(ting)? (smashed|wasted|hammered|plastered)|"
                r"drink(ing)? society|drinking club|blackout",
    "sexual": r"strip(per|ping|tease)?|lap ?dance|escorts?|nude|naked|nudity|porn|sex party|kink|fetish|onlyfans",
    "gambling": r"betting|bookies|real[- ]money (poker|casino)|cash prizes? poker|gamble for money",
    "harm": r"self[- ]harm|suicide challenge|fight club|bare[- ]knuckle|cage fight",
    "extremism": r"extremis[mt]|terroris[mt]|jihad|nazi|white power|hate group",
    "crime": r"illegal|trespass(ing)?|break[- ]in|vandalism|shoplift(ing)?|fake ids?|underage drinking",
}
DANGER_RE = {k: re.compile(r"\b(?:" + v + r")\b", re.I) for k, v in DANGER.items()}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b|\+44\s?\(?0?\)?\s?[12]\d{2,3}\s?\d{3}\s?\d{3,4}\b|\b0[12]\d{2,3}\s?\d{3}\s?\d{3,4}\b")
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
MARKUP = re.compile(r"<\s*/?\s*[a-z!]|javascript:|data:text|on\w+\s*=", re.I)
OFFSITE = re.compile(r"\b(nightclubs?|night clubs?|pubs?|inn|tavern|hotels?|wetherspoons?|airbnb|house party|private (?:house|flat|home)|"
                     r"club (?:on|in) |london|cinema|bowling|karaoke bar|restaurants?)\b", re.I)
# A named space inside a college: halls, bars, rooms, chapels, courts, gardens, theatres, sports grounds the college owns.
COLLEGE_SPACE = re.compile(r"\b(hall|halls|\w*bar|buttery|cr|small cr|suite|kitchen|cellars?|jcr|mcr|scr|hcr|common room|combination room|chapel|court|quad|garden|gardens|lawn|"
                           r"library|auditorium|theatre|lecture|room|rooms|lodge|caf[eé]|refectory|ballroom|marquee|crypt|studio|music|"
                           r"pavilion|pav|sports ground|boathouse|playroom|terrace|hub|centre|building|wing|old court|new court|college)\b", re.I)
TEXT_FIELDS = ("title", "details", "venue", "host", "price", "guests", "dress", "society")
MAX_LEN = {"title": 160, "details": 320, "venue": 160, "host": 160, "price": 120, "guests": 200, "dress": 120, "society": 80}


def _host(u):
    return (urlparse(u).hostname or "").lower()


class Scanner:
    def __init__(self, city, registry, data_sources):
        self.city = city
        self.uni = city.get("university_domain", "")
        self.colleges = list(city["colleges"])
        self.venues = [v.lower() for v in city.get("university_venues", [])]
        self.societies = registry.get("societies", [])
        self.reg = registry["sources"] + self.societies
        self.reg_by_url = {s["url"]: s for s in self.reg}
        self.vetted = {_host(s["url"]) for s in self.reg if s["kind"] not in ("Instagram", "Facebook")}
        self.src = {s["slug"]: s for s in data_sources} if isinstance(data_sources, list) else {}
        self.ball_hosts = {_host(s["url"]) for s in self.src.values() if s.get("kind") == "Ball site" and self._linked_ok(s)}

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
        # Organiser: the cited source is a vetted page of this college, a registered society for society events, or a ball site for a ball.
        text = " ".join(str(b.get(f) or "") for f in ("title", "host", "details")).lower()
        if kind == "society":
            if not reg or reg not in self.societies or reg["society"] != b.get("society"):
                if not (s.get("kind") == "Instagram" and reg):
                    out.append(("organiser", "a society event must cite its own registered society page"))
        elif kind == "ball" and s.get("kind") == "Ball site":
            if not self._linked_ok(s):
                out.append(("organiser", "ball site without an official page linking to it"))
        else:
            if not reg:
                out.append(("organiser", "the source is not in the registry"))
            elif reg.get("kind") == "Student press":
                out.append(("organiser", "the student press reports events; it does not run them, so it cannot be the only source"))
            elif reg.get("college") not in (b.get("college"), "All") and reg.get("college", "").lower() not in text:
                out.append(("organiser", f"cited to a {reg.get('college')} page but listed at {b.get('college')} without naming {reg.get('college')}"))
            elif reg.get("college") == "All" and reg.get("kind") != "SU listings":
                out.append(("organiser", "a university-wide source must be the students' union listing"))
        # Place.
        venue = (b.get("venue") or "").strip()
        if kind == "society":
            if not venue:
                out.append(("place", "a society event must name its venue"))
            elif not (any(v in venue.lower() for v in self.venues) or any(c.lower() in venue.lower() for c in self.colleges)):
                out.append(("place", f"venue {venue!r} is not a college or an approved university venue"))
        else:
            if b.get("college") not in self.colleges:
                out.append(("place", "a college event must name its college"))
            if not venue and kind not in ("formal", "ball"):
                out.append(("place", "the source must say where in the college it is held"))
            elif venue and not (COLLEGE_SPACE.search(venue) or any(c.lower() in venue.lower() for c in self.colleges)
                                or any(v in venue.lower() for v in self.venues)):
                out.append(("place", f"venue {venue!r} is not recognisably a college or university space"))
        if OFFSITE.search(venue):
            out.append(("place", f"venue {venue!r} looks off-site"))
        # Content.
        for f in TEXT_FIELDS:
            v = str(b.get(f) or "")
            for cat, rx in DANGER_RE.items():
                m = rx.search(v)
                if m:
                    out.append(("danger", f"{cat}: {f} says {m.group(0)!r}"))
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
    sc = Scanner(city, registry, data.get("sources", []))
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
