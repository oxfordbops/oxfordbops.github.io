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
        sc = safety_scan.Scanner(CITY, REG, DATA.get("sources", []), evidence_required=(DATA.get("run") or {}).get("version", 1) >= 2)
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

    def test_place_structure(self):
        self.assertIn("place", self.rules(college=None))

    def test_backstop_catches_only_unambiguous_words(self):
        for t in ["MDMA night", "Initiation drinks", "Drinking games social", "Strip poker", "Fight club", "Fake IDs welcome", "Ketamine"]:
            self.assertIn("danger", self.rules(title=t), t)
        for t in ["Halloween Bop", "Diwali Formal", "Film night: Blade Runner", "Top Gun night", "Boat Race screening", "Pub quiz in the JCR", "Wine and cheese"]:
            self.assertNotIn("danger", self.rules(title=t), t)

    def evidence_rules(self, **kw):
        sc = scanner_with(); sc.evidence_required = True
        return [w for r, w in sc.check(entry(**kw)) if r == "evidence"]

    def test_evidence(self):
        good = {"quote": "Friday 6th November: Halloween Bop, 9pm til late in the College Bar", "where": "in the College Bar"}
        self.assertEqual(self.evidence_rules(evidence=good), [])
        self.assertEqual(self.evidence_rules(evidence={"quote": "DTSTART:20261106T210000Z SUMMARY:Halloween Bop", "where": "LOCATION:College Bar"}), [])
        self.assertTrue(self.evidence_rules(), "no evidence")
        self.assertTrue(self.evidence_rules(evidence={"quote": "Saturday 7th November: Halloween Bop, 9pm", "where": "bar"}), "wrong date")
        self.assertTrue(self.evidence_rules(evidence={"quote": "Friday 6th November: Halloween Bop, 8pm", "where": "bar"}), "wrong time")
        self.assertTrue(self.evidence_rules(evidence={"quote": "Friday 6th November: Halloween Bop, 9pm"}), "no place quote")
        self.assertEqual(self.evidence_rules(details="Time not stated.", evidence={"quote": "Halloween Bop on 6 November", "where": "College Bar"}), [])
        weekly = {"quote": "Formal Hall is held on Tuesdays and Fridays during Full Term."}
        self.assertEqual(self.evidence_rules(kind="formal", special=False, title="Formal Hall", venue=None, details="Time not stated.", evidence=weekly), [])
        self.assertEqual(self.evidence_rules(evidence={"quote": "<script>x</script> 6 November 9pm", "where": "bar"}), ["the quote is too long or contains markup"])

    def test_personal_and_tampering(self):
        self.assertIn("personal", self.rules(details="Email jane.doe@gmail.com to book"))
        self.assertIn("personal", self.rules(details="Call 07700 900123"))
        self.assertIn("tampering", self.rules(title="Bop<script>alert(1)</script>"))
        self.assertIn("tampering", self.rules(title="Bop‮gnp.exe"))
        self.assertIn("tampering", self.rules(details="x" * 400))

    def test_organiser_structure(self):
        self.assertIn("organiser", {r for r, _ in scanner_with().check(entry(source="missing"))})
        press = next((x for x in REG["sources"] if x["kind"] == "Student press"), None)
        if press:
            sc = scanner_with([{"slug": "p", "name": "p", "kind": "Student press", "url": press["url"], "ok": True, "found": 0}])
            self.assertIn("organiser", {r for r, _ in sc.check(entry(source="p", url=press["url"]))})


if __name__ == "__main__":
    unittest.main()
