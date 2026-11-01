"""sources.json is the registry of verified places the routine is allowed to read."""
import json, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
REG = ROOT / "docs" / "sources.json"
KINDS = {"JCR site", "JCR events", "MCR site", "MCR events", "Ents site", "Termcard", "Instagram", "Facebook", "College events", "SU listings", "Student press", "Formal hall"}
SOCIETY_KINDS = {"Society events", "Society calendar", "Society termcard", "Ticketing page", "Instagram"}
THE_31 = list(json.loads((ROOT / "city.json").read_text())["colleges"])  # every college of the city, from city.json


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = json.loads(REG.read_text())

    def test_all_31_colleges(self):
        self.assertEqual(self.reg["colleges"], THE_31)

    def test_every_source_is_well_formed(self):
        urls = set()
        for s in self.reg["sources"]:
            with self.subTest(s.get("name")):
                self.assertTrue({"college", "name", "kind", "url"} <= set(s))
                self.assertIn(s["college"], THE_31 + ["All"])
                self.assertIn(s["kind"], KINDS)
                self.assertTrue(s["url"].startswith("https://"), s["url"])
                self.assertNotIn(s["url"], urls, "duplicate url")
                urls.add(s["url"])

    def test_societies_are_well_formed(self):
        """Societies: a short name, a verified page of a known kind, a popularity rank (1 = most popular) and the evidence for it."""
        socs = self.reg.get("societies", [])
        urls = {s["url"] for s in self.reg["sources"]}
        ranks = []
        for s in socs:
            with self.subTest(s.get("society")):
                self.assertTrue({"society", "name", "kind", "url", "rank", "popularity"} <= set(s))
                self.assertIn(s["kind"], SOCIETY_KINDS)
                self.assertTrue(s["url"].startswith("https://"), s["url"])
                self.assertNotIn(s["url"], urls, "duplicate url")
                urls.add(s["url"])
                self.assertIsInstance(s["rank"], int)
                self.assertGreater(len(s["popularity"]), 20, "say why it ranks where it does")
                ranks.append((s["society"], s["rank"]))
        by_soc = {}
        for name, r in ranks:
            by_soc.setdefault(name, set()).add(r)
        self.assertTrue(all(len(v) == 1 for v in by_soc.values()), "one rank per society")
        firsts = sorted(min(v) for v in by_soc.values())
        self.assertEqual(firsts, sorted(set(firsts)), "no two societies share a rank")

    def test_formal_hall_schedule_fields(self):
        """formal_time is the page's own start time (HH:MM); day_notes name only the registry's formal days."""
        for s in self.reg["sources"]:
            if "formal_time" in s:
                ft = s["formal_time"]
                times = ft.values() if isinstance(ft, dict) else [ft]
                for t in times:
                    self.assertRegex(t, r"^(1[6-9]|2[0-1]):[0-5][0-9]$", s["url"])
                self.assertTrue(s.get("formal_days"), f"{s['url']}: formal_time without formal_days")
                if isinstance(ft, dict):
                    self.assertTrue(set(ft) <= set(s["formal_days"]), f"{s['url']}: a time for a day without formal hall")
            if "day_notes" in s:
                self.assertTrue(set(s["day_notes"]) <= set(s.get("formal_days") or []), f"{s['url']}: a day note for a day without formal hall")

    def test_every_college_has_a_source(self):
        have = {s["college"] for s in self.reg["sources"]}
        self.assertEqual([c for c in THE_31 if c not in have], [])

    def test_every_college_has_a_readable_source(self):
        # Instagram and Facebook cannot be fetched, so each college needs at least one web page too.
        readable = {s["college"] for s in self.reg["sources"] if s["kind"] not in ("Instagram", "Facebook")}
        self.assertEqual([c for c in THE_31 if c not in readable], [])

    def test_university_wide_sources_present(self):
        kinds = {s["kind"] for s in self.reg["sources"] if s["college"] == "All"}
        self.assertIn("SU listings", kinds)
        self.assertIn("Student press", kinds)


if __name__ == "__main__":
    unittest.main()
