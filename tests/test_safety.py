"""Safety rules for everything the site publishes: where links go, where events are, and what listings may say.

1. Links: https only, on the university's own domain or on a page vetted in the registry (sources.json), a Google Calendar,
   an Instagram post cited to a registered Instagram account, or a ball's own site that an official page links to.
   Never a link shortener, a form, a raw IP address or a file download.
2. Places: every event is at a college of the city, or (society events) at a university building or affiliated venue
   listed in city.json, or names no venue. Off-site commercial venues are never listed.
3. Content: nothing about drugs, weapons, initiations or hazing, drinking games or challenges, and no personal data
   (email addresses, phone numbers).
"""
import ipaddress, json, pathlib, re, unittest
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
CITY = json.loads((ROOT / "city.json").read_text())
REG = json.loads((ROOT / "docs" / "sources.json").read_text())
DATA = json.loads((ROOT / "docs" / "events.json").read_text())
UNI = CITY.get("university_domain", "")
VENUES = [v.lower() for v in CITY.get("university_venues", [])]
COLLEGES = list(CITY["colleges"])
REGISTRY = REG["sources"] + REG.get("societies", [])
VETTED = {urlparse(s["url"]).hostname for s in REGISTRY if s["kind"] not in ("Instagram", "Facebook")}

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly", "is.gd", "rebrand.ly", "linktr.ee", "lnkd.in", "cutt.ly", "shorturl.at", "forms.gle"}
FORMS = re.compile(r"docs\.google\.com/forms|forms\.office\.com|forms\.microsoft\.com|typeform\.com|jotform\.com|surveymonkey\.com", re.I)
DOWNLOADS = re.compile(r"\.(exe|zip|rar|7z|dmg|apk|msi|bat|cmd|scr|js|jar|iso)(\?|$)", re.I)
DANGEROUS = re.compile(r"\b(cocaine|coke|mdma|ecstasy|ketamine|ket|lsd|acid trip|shrooms|magic mushrooms|weed|cannabis|edibles|pills|nitrous|balloons|"
                       r"drugs?|weapons?|knife|knives|guns?|initiations?|hazing|drinking games?|pint challenge|chunder|spirit races?|downing contest|"
                       r"strip(per|ping)?|escort)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b|\+44\s?1\d{3}\s?\d{6}")
OFFSITE = re.compile(r"\b(nightclub|night club|pub|arms|inn|tavern|hotel|wetherspoons?|airbnb|house party|private (house|flat)|london)\b", re.I)


def host(u):
    return (urlparse(u).hostname or "").lower()


def on_uni(h):
    return bool(UNI) and (h == UNI or h.endswith("." + UNI))


def link_problem(u):
    p = urlparse(u)
    h = (p.hostname or "").lower()
    if p.scheme != "https":
        return "not https"
    try:
        ipaddress.ip_address(h)
        return "raw IP address"
    except ValueError:
        pass
    if h in SHORTENERS:
        return "link shortener"
    if FORMS.search(u):
        return "a form"
    if DOWNLOADS.search(p.path):
        return "a file download"
    return None


class TestLinks(unittest.TestCase):
    def test_registry_links(self):
        for s in REGISTRY:
            self.assertIsNone(link_problem(s["url"]), f"registry: {s['url']}: {link_problem(s['url'])}")

    def test_listing_links(self):
        src = {s["slug"]: s for s in DATA["sources"]} if isinstance(DATA["sources"], list) else {}
        ball_hosts = {}
        for s in src.values():
            if s.get("kind") == "Ball site":
                lf = s.get("linked_from", "")
                self.assertTrue(on_uni(host(lf)) or host(lf) in VETTED, f"{s['url']}: a ball site needs linked_from, an official page that links to it")
                ball_hosts[host(s["url"])] = s["slug"]
        for b in DATA["bops"]:
            u = b.get("url", "")
            with self.subTest(b["title"]):
                self.assertIsNone(link_problem(u), f"{b['title']}: {u}: {link_problem(u)}")
                h = host(u)
                s = src.get(b.get("source"), {})
                ok = (on_uni(h) or h in VETTED or h == "calendar.google.com"
                      or (h.endswith("instagram.com") and s.get("kind") == "Instagram")
                      or (h in ball_hosts and b.get("kind") == "ball"))
                self.assertTrue(ok, f"{b['title']}: {h} is neither the university's domain nor a vetted source")


class TestPlaces(unittest.TestCase):
    def test_every_event_is_at_a_university_place(self):
        for b in DATA["bops"]:
            venue = (b.get("venue") or "").lower()
            with self.subTest(b["title"]):
                if b.get("college") in COLLEGES:
                    pass
                elif b.get("kind") == "society":
                    self.assertTrue(not venue or any(v in venue for v in VENUES) or any(c.lower() in venue for c in COLLEGES),
                                    f"{b['title']}: venue {b.get('venue')!r} is not a college or an approved university venue (city.json university_venues)")
                else:
                    self.fail(f"{b['title']}: every college event names its college")
                self.assertIsNone(OFFSITE.search(venue), f"{b['title']}: venue {b.get('venue')!r} looks off-site")


class TestContent(unittest.TestCase):
    FIELDS = ("title", "details", "venue", "host", "price", "guests", "dress")

    def test_nothing_dangerous(self):
        for b in DATA["bops"]:
            for f in self.FIELDS:
                m = DANGEROUS.search(b.get(f) or "")
                self.assertIsNone(m, f"{b['title']}: {f} mentions {m.group(0) if m else ''!r}")

    def test_no_personal_data(self):
        for b in DATA["bops"]:
            for f in self.FIELDS:
                v = b.get(f) or ""
                self.assertIsNone(EMAIL.search(v), f"{b['title']}: {f} has an email address")
                self.assertIsNone(PHONE.search(v), f"{b['title']}: {f} has a phone number")


if __name__ == "__main__":
    unittest.main()
