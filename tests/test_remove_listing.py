"""scripts/remove_listing.py removes exactly one matching entry and keeps source counts right; no match changes nothing."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestRemoveListing(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir(); (self.tmp / "docs").mkdir()
        shutil.copy(ROOT / "scripts" / "remove_listing.py", self.tmp / "scripts")
        self.data = {"generated": "x", "run": {}, "sources": [{"slug": "s", "name": "S", "kind": "JCR site", "url": "https://example.org/", "ok": True, "found": 2}],
                     "bops": [{"kind": "bop", "title": "A", "starts_at": "2026-11-05T21:00:00+00:00", "source": "s"},
                              {"kind": "bop", "title": "B", "starts_at": "2026-11-06T21:00:00+00:00", "source": "s"}]}
        (self.tmp / "docs" / "events.json").write_text(json.dumps(self.data, indent=1))

    def run_it(self, start, title):
        return subprocess.run([sys.executable, str(self.tmp / "scripts" / "remove_listing.py"), "--start", start, "--title", title, "--reason", "test"], capture_output=True, text=True)

    def test_removes_one(self):
        self.assertEqual(self.run_it("2026-11-05T21:00", "A").returncode, 0)
        d = json.loads((self.tmp / "docs" / "events.json").read_text())
        self.assertEqual([b["title"] for b in d["bops"]], ["B"])
        self.assertEqual(d["sources"][0]["found"], 1)

    def test_no_match_changes_nothing(self):
        before = (self.tmp / "docs" / "events.json").read_text()
        self.assertEqual(self.run_it("2026-11-05T21:00", "Nope").returncode, 2)
        self.assertEqual((self.tmp / "docs" / "events.json").read_text(), before)


if __name__ == "__main__":
    unittest.main()
