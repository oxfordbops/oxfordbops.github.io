"""events.json is what the routine writes and the page reads. These tests are the contract between them."""
import json, pathlib, re, unittest
from datetime import date, datetime, timedelta, timezone
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
        self.assertEqual(set(d) >= {"generated", "run", "sources", "bops"}, True, "generated, run, sources and bops are required")
        self.assertTrue(ISO.match(d["generated"]), d["generated"])
        self.assertIsInstance(d["bops"], list)
        self.assertIsInstance(d["sources"], list)

    def test_run_record_is_fresh_and_consistent(self):
        # The run block is the "last checked" stamp the page shows. It must be rewritten on every run,
        # so each field is checked against the rest of the file rather than trusted.
        d = load()
        run = d["run"]
        self.assertEqual(set(run), {"checked_at", "window_from", "window_to", "sources_checked", "sources_ok"}, "run has exactly these five fields")
        self.assertTrue(ISO.match(run["checked_at"]), run["checked_at"])
        checked = datetime.fromisoformat(run["checked_at"].replace("Z", "+00:00"))
        generated = datetime.fromisoformat(d["generated"].replace("Z", "+00:00"))
        self.assertEqual(checked, generated, "checked_at must equal generated")
        self.assertEqual(checked.utcoffset().total_seconds(), 0, "checked_at is written in UTC")
        self.assertLess((checked - datetime.now(timezone.utc)).total_seconds(), 3600, "checked_at is in the future")
        self.assertEqual(run["window_from"], checked.astimezone(LONDON).date().isoformat(), "window_from is the run's date in UK time")
        start = date.fromisoformat(run["window_from"])
        self.assertEqual(run["window_to"], (start + timedelta(days=14)).isoformat(), "window_to is 14 days after window_from")
        self.assertEqual(run["sources_checked"], len(d["sources"]), "sources_checked must equal the number of source entries")
        self.assertEqual(run["sources_ok"], sum(1 for s in d["sources"] if s.get("ok") is True), "sources_ok must equal the number of readable sources")
        for b in d["bops"]:
            day = datetime.fromisoformat(b["starts_at"].replace("Z", "+00:00")).astimezone(LONDON).date()
            self.assertTrue(start <= day <= start + timedelta(days=14), f"{b['title']} on {day} is outside the run's window")

    def test_sources_entries(self):
        d = load()
        if isinstance(d["sources"], int):
            return
        slugs = set()
        reg = {r["url"]: r for r in json.loads(SOURCES.read_text())["sources"]}
        for s in d["sources"]:
            self.assertTrue({"slug", "name", "kind", "url", "ok", "found"} <= set(s), f"source entry missing fields: {s}")
            self.assertNotIn(s["slug"], slugs, "duplicate source slug")
            slugs.add(s["slug"])
            self.assertTrue(s["url"].startswith("https://"), s["url"])
            self.assertIn(s["ok"], (True, False))
            self.assertIsInstance(s["found"], int)
            self.assertGreaterEqual(s["found"], 0)
            self.assertIn(s["url"], reg, f"{s['url']} is not in the registry")
            self.assertEqual(s["kind"], reg[s["url"]]["kind"], f"{s['url']}: kind differs from the registry")
            if s["kind"] in ("Instagram", "Facebook"):
                self.assertFalse(s["ok"], f"{s['url']}: a social account cannot be marked readable")
        counted = {}
        for b in d["bops"]:
            counted[b["source"]] = counted.get(b["source"], 0) + 1
        for s in d["sources"]:
            self.assertEqual(s["found"], counted.get(s["slug"], 0), f"{s['slug']}: found={s['found']} but {counted.get(s['slug'], 0)} bops cite it")

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
                if link.hostname in ("instagram.com", "www.instagram.com"):
                    is_post = re.search(r"/(p|reel|reels)/[A-Za-z0-9_-]+", link.path) is not None
                    if not is_post:
                        # An account page is allowed only for an entry a person added from that account.
                        src = next((s for s in d["sources"] if s["slug"] == b["source"]), {}) if isinstance(d["sources"], list) else {}
                        self.assertEqual(src.get("kind"), "Instagram", f"{b['title']}: an account-only Instagram link needs an Instagram source")
                        self.assertRegex(link.path, r"^/[A-Za-z0-9_.]+/?$", "an Instagram account link")
                self.assertLessEqual(len(b.get("details", "")), 300)
                self.assertTrue(b.get("source"), "every bop names its source")
                if slugs is not None:
                    self.assertIn(b["source"], slugs, "source slug not in the sources list")

    def test_sorted_and_unique(self):
        bops = load()["bops"]
        starts = [b["starts_at"] for b in bops]
        self.assertEqual(starts, sorted(starts, key=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))))
        # Two entries are the same bop when college, day and title coincide; a JCR bop and an MCR party on one night are distinct.
        keys = [(b.get("college"), b["starts_at"][:10], b["title"].strip().lower(), (b.get("host") or "").strip().lower()) for b in bops]
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
        # Every registered source, social ones included (recorded as not readable), so the run record's counts mean something.
        registered = {s["url"] for s in reg["sources"]}
        tried = {s["url"] for s in d["sources"]} if isinstance(d["sources"], list) else set()
        missing = sorted(registered - tried)
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



if __name__ == "__main__":
    unittest.main()
