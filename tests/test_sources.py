"""sources.json is the registry of verified places the routine is allowed to read."""
import json, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
REG = ROOT / "docs" / "sources.json"
KINDS = {"JCR site", "JCR events", "MCR site", "MCR events", "Ents site", "Termcard", "Instagram", "Facebook", "College events", "SU listings", "Student press"}
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
