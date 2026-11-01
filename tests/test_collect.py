"""Offline tests of the collector's parsing, so a change that drops events fails before it reaches a run."""
import base64, datetime as dt, pathlib, sys, unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import collect  # noqa: E402

L = ZoneInfo("Europe/London")
LO, HI, BALL_HI = dt.date(2026, 11, 1), dt.date(2026, 11, 15), dt.date(2027, 12, 1)


def ics(*events):
    return "BEGIN:VCALENDAR\r\n" + "".join("BEGIN:VEVENT\r\n" + e + "\r\nEND:VEVENT\r\n" for e in events) + "END:VCALENDAR\r\n"


class TestCollect(unittest.TestCase):
    def test_single_events_in_and_out_of_window(self):
        got = collect.ics_events(ics("DTSTART:20261104T193000Z\r\nSUMMARY:Diwali Formal",
                                     "DTSTART:20261201T193000Z\r\nSUMMARY:Too late",
                                     "DTSTART;VALUE=DATE:20261106\r\nSUMMARY:All day bop"), LO, HI, BALL_HI)
        self.assertEqual([e["summary"] for e in got], ["Diwali Formal", "All day bop"])
        self.assertEqual(got[0]["start"], "2026-11-04T19:30+00:00")

    def test_timezone_and_folded_lines(self):
        got = collect.ics_events(ics("DTSTART;TZID=Europe/London:20261105T210000\r\nSUMMARY:Bonfire\r\n  Bop"), LO, HI, BALL_HI)
        self.assertEqual(got[0]["summary"], "Bonfire Bop")
        self.assertEqual(got[0]["start"], "2026-11-05T21:00+00:00")

    def test_weekly_recurrence_is_expanded_not_dumped(self):
        got = collect.ics_events(ics("DTSTART:20141015T190000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=WE\r\nSUMMARY:Yoga",
                                     "DTSTART:20141015T190000Z\r\nRRULE:FREQ=WEEKLY;UNTIL=20150101\r\nSUMMARY:Ended"), LO, HI, BALL_HI)
        self.assertEqual([e["start"][:10] for e in got], ["2026-11-04", "2026-11-11"])
        self.assertTrue(all(e["recurring"] for e in got))

    def test_balls_reach_beyond_the_fortnight(self):
        got = collect.ics_events(ics("DTSTART:20270621T200000Z\r\nSUMMARY:Jesus May Ball"), LO, HI, BALL_HI)
        self.assertEqual(len(got), 1)

    def test_calendar_ids_plain_and_base64(self):
        enc = base64.b64encode(b"abc@group.calendar.google.com").decode().rstrip("=")
        page = (f'<iframe src="https://calendar.google.com/calendar/embed?src=x%40gmail.com&amp;ctz=Europe/London"></iframe>'
                f'<iframe src="https://calendar.google.com/calendar/embed?src={enc}"></iframe>'
                '<a href="https://calendar.google.com/calendar/ical/en.uk%23holiday%40group.v.calendar.google.com/public/basic.ics">').encode()
        self.assertEqual(collect.calendar_ids(page), {"x@gmail.com", "abc@group.calendar.google.com"})

    def test_snippets_need_a_date_in_the_window(self):
        window = {LO + dt.timedelta(days=k) for k in range(15)}
        text = "Halloween Bop on 31 October in the bar. Christmas Bop on 5 November in the JCR. Bops are great fun."
        got = collect.snippets(text, window)
        self.assertEqual(len(got), 1)
        self.assertIn("5 November", got[0])

    def test_schedule_lines_are_kept(self):
        window = {LO + dt.timedelta(days=k) for k in range(15)}
        got = collect.snippets("Formal Hall is held on Tuesdays and Fridays during Full Term.", window)
        self.assertTrue(got and got[0].startswith("SCHEDULE:"))

    def test_calendar_embed_url_itself(self):
        url = b"https://calendar.google.com/calendar/embed?src=events@kcsu.org.uk&ctz=Europe/London"
        self.assertEqual(collect.calendar_ids(url), {"events@kcsu.org.uk"})

    def test_html_to_text_drops_scripts(self):
        self.assertEqual(collect.to_text(b"<p>Bop<script>var x=1</script></p><p>Tonight</p>"), "Bop\nTonight")


if __name__ == "__main__":
    unittest.main()
