"""events.json is what the routine writes and the page reads. These tests are the contract between them."""
import json, pathlib, re, unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVENTS = ROOT / "docs" / "events.json"
SOURCES = ROOT / "docs" / "sources.json"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|\+01:00|Z)$")
ALLOWED = {"title", "starts_at", "ends_at", "college", "venue", "host", "price", "guests", "dress", "url", "details", "source"}


def load():
    return json.loads(EVENTS.read_text())


def colleges():
    return set(json.loads(SOURCES.read_text())["colleges"])


class TestShape(unittest.TestCase):
    def test_top_level(self):
        d = load()
        self.assertEqual(set(d) >= {"generated", "sources", "bops"}, True)
        self.assertTrue(ISO.match(d["generated"]), d["generated"])
        self.assertIsInstance(d["bops"], list)
        self.assertTrue(isinstance(d["sources"], (int, list)))

    def test_sources_entries(self):
        d = load()
        if isinstance(d["sources"], int):
            return
        slugs = set()
        for s in d["sources"]:
            self.assertTrue({"slug", "name", "url"} <= set(s), s)
            self.assertNotIn(s["slug"], slugs, "duplicate source slug")
            slugs.add(s["slug"])
            self.assertTrue(s["url"].startswith("https://"), s["url"])
            self.assertIn(s.get("ok", True), (True, False))
            self.assertGreaterEqual(int(s.get("found", 0)), 0)

    def test_every_bop_is_well_formed(self):
        d = load()
        known = colleges()
        slugs = {s["slug"] for s in d["sources"]} if isinstance(d["sources"], list) else None
        for b in d["bops"]:
            with self.subTest(b.get("title")):
                self.assertFalse(set(b) - ALLOWED, f"unknown fields {set(b) - ALLOWED}")
                self.assertTrue(2 <= len(b["title"]) <= 120)
                self.assertNotEqual(b["title"], b["title"].upper(), "shouting capitals")
                self.assertTrue(ISO.match(b["starts_at"]), b["starts_at"])
                if b.get("ends_at"):
                    self.assertTrue(ISO.match(b["ends_at"]))
                    self.assertGreater(datetime.fromisoformat(b["ends_at"]), datetime.fromisoformat(b["starts_at"]))
                if b.get("college") is not None:
                    self.assertIn(b["college"], known)
                self.assertTrue(b.get("college") or b.get("venue"), "a bop needs a college or a venue")
                self.assertTrue(b.get("url", "").startswith("https://"), "every bop links to its announcement")
                self.assertLessEqual(len(b.get("details", "")), 300)
                self.assertTrue(b.get("source"), "every bop names its source")
                if slugs is not None:
                    self.assertIn(b["source"], slugs, "source slug not in the sources list")

    def test_sorted_and_unique(self):
        bops = load()["bops"]
        starts = [b["starts_at"] for b in bops]
        self.assertEqual(starts, sorted(starts, key=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))))
        keys = [(b.get("college"), b["starts_at"][:10]) for b in bops]
        self.assertEqual(len(keys), len(set(keys)), "two bops for the same college on the same day")

    def test_uk_offset_matches_the_date(self):
        # BST runs from the last Sunday of March to the last Sunday of October.
        for b in load()["bops"]:
            dt = datetime.fromisoformat(b["starts_at"].replace("Z", "+00:00"))
            month = dt.month
            off = dt.utcoffset().total_seconds() / 3600
            if 4 <= month <= 9:
                self.assertEqual(off, 1, f"{b['title']}: summer date with winter offset")
            if month in (11, 12, 1, 2):
                self.assertEqual(off, 0, f"{b['title']}: winter date with summer offset")

    def test_window_is_sane(self):
        # The routine writes the next 14 days; allow a day of slack either side for runs near midnight.
        d = load()
        gen = datetime.fromisoformat(d["generated"].replace("Z", "+00:00"))
        for b in d["bops"]:
            dt = datetime.fromisoformat(b["starts_at"].replace("Z", "+00:00"))
            days = (dt - gen).total_seconds() / 86400
            self.assertTrue(-1 <= days <= 15, f"{b['title']} is {days:.1f} days from the run")


if __name__ == "__main__":
    unittest.main()
