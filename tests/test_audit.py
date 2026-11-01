"""The audit report script accepts a well-formed audit and rejects a malformed one."""
import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import audit_report  # noqa: E402

GOOD = {"checked_at": "2026-11-01T08:30:00Z", "window_from": "2026-11-01", "window_to": "2026-11-15", "sources_checked": 150,
        "missing": [{"kind": "bop", "college": "X", "title": "Bop", "date": "2026-11-07", "time": "21:00", "url": "https://x", "evidence": "e", "confidence": "low"}],
        "mismatched": [], "unverifiable": [], "unreadable_sources": [], "registry": [], "new_sources": [], "term_dates": []}


class TestAudit(unittest.TestCase):
    def test_good_audit_is_valid(self):
        self.assertEqual(audit_report.check(GOOD, audit_report.SCHEMA), [])

    def test_bad_audit_is_rejected(self):
        bad = {**GOOD, "sources_checked": "many", "missing": [{**GOOD["missing"][0], "confidence": "maybe"}]}
        del bad["registry"]
        errs = audit_report.check(bad, audit_report.SCHEMA)
        self.assertEqual(len(errs), 3, errs)

    def test_low_confidence_alone_raises_no_issue(self):
        _, body, act = audit_report.report(GOOD, "Test")
        self.assertFalse(act)
        self.assertIn("Bop", body)


if __name__ == "__main__":
    unittest.main()
