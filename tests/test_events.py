"""events.json is what the routine writes and the page reads. These tests are the contract between them."""
import json, pathlib, re, unittest
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

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
                if len(b["title"]) > 4:
                    self.assertNotEqual(b["title"], b["title"].upper(), "shouting capitals")
                self.assertTrue(ISO.match(b["starts_at"]), b["starts_at"])
                if b.get("ends_at"):
                    self.assertTrue(ISO.match(b["ends_at"]))
                    self.assertGreater(datetime.fromisoformat(b["ends_at"]), datetime.fromisoformat(b["starts_at"]))
                if b.get("college") is not None:
                    self.assertIn(b["college"], known)
                self.assertTrue(b.get("college") or b.get("venue"), "a bop needs a college or a venue")
                link = urlparse(b.get("url", ""))
                self.assertTrue(link.scheme == "https" and link.hostname, "every bop links to its announcement")
                if link.hostname and link.hostname.endswith("instagram.com"):
                    # The post when it is known; otherwise the account, so the reader can find the announcement.
                    self.assertRegex(link.path, r"^/[A-Za-z0-9_.]+/", "an Instagram link needs an account or a post path")
                self.assertLessEqual(len(b.get("details", "")), 300)
                self.assertTrue(b.get("source"), "every bop names its source")
                if slugs is not None:
                    self.assertIn(b["source"], slugs, "source slug not in the sources list")

    def test_sorted_and_unique(self):
        bops = load()["bops"]
        starts = [b["starts_at"] for b in bops]
        self.assertEqual(starts, sorted(starts, key=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))))
        # Two entries are the same bop when college, day and title coincide; a JCR bop and an MCR party on one night are distinct.
        keys = [(b.get("college"), b["starts_at"][:10], b["title"].strip().lower()) for b in bops]
        self.assertEqual(len(keys), len(set(keys)), "the same bop is listed twice")
        same_day = {}
        for b in bops:
            same_day.setdefault((b.get("college"), b["starts_at"][:10]), []).append(b)
        for k, group in same_day.items():
            if len(group) > 1:
                hosts = {(g.get("host") or g["title"]).lower() for g in group}
                self.assertEqual(len(hosts), len(group), f"{k}: several bops on one day must have different hosts or titles")

    def test_every_registered_source_was_tried(self):
        # The routine must record every readable registered source, so a run that skipped colleges fails here.
        d = load()
        if not d["bops"] and not d["sources"]:
            self.skipTest("fresh city, no run yet")
        reg = json.loads(SOURCES.read_text())
        readable = {s["url"] for s in reg["sources"] if s["kind"] not in ("Instagram", "Facebook")}
        tried = {s["url"] for s in d["sources"]} if isinstance(d["sources"], list) else set()
        missing = sorted(readable - tried)
        self.assertEqual(missing, [], f"{len(missing)} registered sources were not recorded this run")

    def test_uk_offset_matches_the_date(self):
        # Every start and end carries the offset Europe/London had at that instant, including the transition weekends.
        for b in load()["bops"]:
            for field in ("starts_at", "ends_at"):
                if not b.get(field):
                    continue
                dt = datetime.fromisoformat(b[field].replace("Z", "+00:00"))
                expected = dt.astimezone(LONDON).utcoffset()
                self.assertEqual(dt.utcoffset(), expected, f"{b['title']} {field}: offset {dt.utcoffset()} but London had {expected}")

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
