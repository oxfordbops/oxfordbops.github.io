"""Safety: the committed listings pass scripts/safety_scan.py, and the scanner itself catches known unsafe examples
without flagging known safe ones. See the scanner's docstring for the rules."""
import json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import safety_scan  # noqa: E402

CITY, REG, DATA = safety_scan.load()
COLLEGE = list(CITY["colleges"])[0]
UNI = CITY.get("university_domain", "example.ac.uk")
COLLEGE_SRC = next(s for s in REG["sources"] if s["college"] == COLLEGE and s["kind"] not in ("Instagram", "Facebook"))


def scanner_with(extra_sources=()):
    srcs = [{"slug": "c", "name": "c", "kind": COLLEGE_SRC["kind"], "url": COLLEGE_SRC["url"], "ok": True, "found": 0}] + list(extra_sources)
    return safety_scan.Scanner(CITY, REG, srcs)


def entry(**kw):
    e = {"kind": "bop", "title": "Halloween Bop", "starts_at": "2026-11-06T21:00:00+00:00", "college": COLLEGE, "venue": "College Bar",
         "url": COLLEGE_SRC["url"], "source": "c"}
    e.update(kw)
    return e


class TestCommittedData(unittest.TestCase):
    def test_every_listing_passes_the_scan(self):
        sc = safety_scan.Scanner(CITY, REG, DATA.get("sources", []))
        bad = {b["title"]: sc.check(b) for b in DATA["bops"] if sc.check(b)}
        self.assertEqual(bad, {}, "run python3 scripts/safety_scan.py --fix and report what it removed")

    def test_registry_links_are_clean(self):
        sc = scanner_with()
        for s in REG["sources"] + REG.get("societies", []):
            self.assertIsNone(sc.link_problem(s["url"]), s["url"])


class TestScanner(unittest.TestCase):
    def rules(self, **kw):
        return {r for r, _ in scanner_with().check(entry(**kw))}

    def test_safe_bop_passes(self):
        self.assertEqual(scanner_with().check(entry()), [])

    def test_regular_formal_needs_no_venue(self):
        self.assertEqual(scanner_with().check(entry(kind="formal", special=False, title="Formal Hall", venue=None)), [])

    def test_links(self):
        for u in ["http://" + UNI + "/x", "https://bit.ly/abc", "https://fixr.co/event/1", "https://ra.co/events/1", "https://docs.google.com/forms/d/x",
                  "https://1.2.3.4/x", "https://xn--cmbridge-9za.ac.uk/", "https://evil.example.com/", "https://" + UNI + "/x.exe", "https://user:pw@" + UNI + "/"]:
            self.assertIn("link", self.rules(url=u), u)
        self.assertNotIn("link", self.rules(url="https://www." + UNI + "/events"))

    def test_places(self):
        for v in ["The Jolly Farmers", "Revolution nightclub", "Slug and Lettuce pub", "a private house", "London Bridge", ""]:
            self.assertIn("place", self.rules(venue=v), v)
        for v in ["JCR", "Old Hall", "Fellows' Garden", "QBar", f"Langford Room, {COLLEGE}"]:
            self.assertNotIn("place", self.rules(venue=v), v)
        self.assertIn("place", self.rules(college=None))

    def test_danger(self):
        for t in ["MDMA night", "Initiation drinks", "Pub crawl", "Drinking games social", "Bottomless brunch", "Strip poker", "Knife skills",
                  "Fight club", "Fake IDs welcome", "Boat race and chunder"]:
            self.assertIn("danger", self.rules(title=t), t)
        for t in ["Halloween Bop", "Diwali Formal", "Film night: Blade Runner", "Jazz night", "Wine and cheese", "Pub quiz in the JCR"]:
            self.assertNotIn("danger", self.rules(title=t), t)

    def test_personal_and_tampering(self):
        self.assertIn("personal", self.rules(details="Email jane.doe@gmail.com to book"))
        self.assertIn("personal", self.rules(details="Call 07700 900123"))
        self.assertIn("tampering", self.rules(title="Bop<script>alert(1)</script>"))
        self.assertIn("tampering", self.rules(title="Bop‮gnp.exe"))
        self.assertIn("tampering", self.rules(details="x" * 400))

    def test_organiser(self):
        other = next(s for s in REG["sources"] if s["college"] not in (COLLEGE, "All") and s["kind"] not in ("Instagram", "Facebook"))
        sc = scanner_with([{"slug": "o", "name": "o", "kind": other["kind"], "url": other["url"], "ok": True, "found": 0}])
        self.assertIn("organiser", {r for r, _ in sc.check(entry(source="o", url=other["url"]))}, "another college's page, not naming it")
        self.assertIn("organiser", {r for r, _ in sc.check(entry(source="o", url=other["url"], title="Formal swap with " + other["college"] + " MCR"))}),
        self.assertNotIn("organiser", {r for r, _ in sc.check(entry(source="o", url=other["url"], title="Formal exchange (" + other["college"] + " MCR away leg)"))})
        self.assertIn("organiser", {r for r, _ in scanner_with().check(entry(source="missing"))})


if __name__ == "__main__":
    unittest.main()
