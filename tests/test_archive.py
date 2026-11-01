"""Archived months hold past entries of their own month, once each, with the same fields as live listings."""
import datetime as dt, json, pathlib, unittest
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
ALLOWED = {"kind", "special", "title", "starts_at", "ends_at", "college", "venue", "host", "price", "guests", "dress", "url", "details", "source"}


class TestArchive(unittest.TestCase):
    def test_month_files(self):
        for f in sorted((ROOT / "docs" / "archive").glob("*.json")):
            entries = json.loads(f.read_text())
            self.assertIsInstance(entries, list, f.name)
            keys = set()
            for e in entries:
                self.assertTrue({"title", "starts_at"} <= set(e) and set(e) <= ALLOWED, f"{f.name}: {e.get('title')} has unexpected fields")
                d = dt.datetime.fromisoformat(e["starts_at"].replace("Z", "+00:00")).astimezone(LONDON).date()
                self.assertEqual(d.strftime("%Y-%m"), f.stem, f"{f.name}: {e['title']} is from another month")
                k = (e.get("kind", "bop"), e.get("college"), e["starts_at"], e["title"].strip().lower())
                self.assertNotIn(k, keys, f"{f.name}: {e['title']} archived twice")
                keys.add(k)
            self.assertEqual([e["starts_at"] for e in entries], sorted(e["starts_at"] for e in entries), f"{f.name} is not sorted")


if __name__ == "__main__":
    unittest.main()
