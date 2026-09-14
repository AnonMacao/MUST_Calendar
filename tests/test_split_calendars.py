from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from icalendar import Calendar

from calendar_exporter import CalendarEvent
from main import course_filename, export_calendars, group_course_events
from sources import ClassTimetableSource, MACAU_TIMEZONE, OAScheduleSource


def lesson_event(code: str, name: str, lesson_id: str) -> CalendarEvent:
    return CalendarEvent(
        source="class-timetable",
        source_id=lesson_id,
        summary=name,
        start=datetime(2026, 9, 14, 9, tzinfo=MACAU_TIMEZONE),
        end=datetime(2026, 9, 14, 10, tzinfo=MACAU_TIMEZONE),
        course_code=code,
    )


def calendar_events(path: Path) -> list:
    return list(Calendar.from_ical(path.read_bytes()).walk("VEVENT"))


class SplitCalendarTests(TestCase):
    def test_groups_courses_and_removes_only_stale_course_ics(self) -> None:
        econ1 = lesson_event("ECON2001", "Microeconomics", "a")
        econ2 = lesson_event("ECON2001", "Microeconomics", "b")
        math = lesson_event("MATH2002", "Mathematics", "c")
        with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            output = Path(temporary) / "output"
            courses = output / "courses"
            courses.mkdir(parents=True)
            (courses / "OLD.ics").write_text("old")
            (courses / "notes.txt").write_text("keep")
            export_calendars([econ1, econ2, math], [], 30, output)
            self.assertEqual(
                {path.name for path in courses.iterdir()},
                {"ECON2001.ics", "MATH2002.ics", "notes.txt"},
            )
            econ_file = Calendar.from_ical((courses / "ECON2001.ics").read_bytes())
            self.assertEqual(str(econ_file["X-WR-CALNAME"]), "Microeconomics")
            self.assertEqual(
                {str(event["SUMMARY"]) for event in calendar_events(courses / "ECON2001.ics")},
                {"Microeconomics"},
            )
            self.assertEqual(len(calendar_events(courses / "ECON2001.ics")), 2)
            first_uids = [str(event["UID"]) for event in calendar_events(courses / "ECON2001.ics")]
            export_calendars([econ1, econ2, math, econ1], [], 30, output)
            second_uids = [str(event["UID"]) for event in calendar_events(courses / "ECON2001.ics")]
            self.assertEqual(first_uids, second_uids)
            export_calendars([math], [], 30, output)
            self.assertFalse((courses / "ECON2001.ics").exists())
            self.assertTrue((courses / "notes.txt").exists())
            self.assertEqual(calendar_events(output / "oa.ics"), [])

    def test_safe_course_filenames_and_missing_code(self) -> None:
        self.assertEqual(course_filename(lesson_event("econ2001", "Econ", "1")), "ECON2001.ics")
        self.assertNotIn("/", course_filename(lesson_event("ECON/2001", "Econ", "2")))
        self.assertTrue(course_filename(lesson_event("", "微觀經濟學", "3")).endswith(".ics"))
        self.assertEqual(len(group_course_events([lesson_event("", "微觀經濟學", "3")])), 1)

    def test_class_source_fetches_once_per_term_and_preserves_code(self) -> None:
        response = Mock()
        response.json.return_value = {"model": {"lesson": [
            {"id": 1, "lessonDate": "2026-09-14", "lessonStartTime": "09:00",
             "lessonEndTime": "10:00", "courseCode": "ECON2001", "courseEnName": "Econ"},
            {"id": 2, "lessonDate": "2026-09-15", "lessonStartTime": "09:00",
             "lessonEndTime": "10:00", "courseCode": "MATH2002"},
        ]}}
        session = Mock()
        session.get.return_value = response
        events = ClassTimetableSource("cookie", locale="en_US", session=session).fetch(
            ("2609",), date(2026, 9, 1), date(2026, 9, 30)
        )
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual({event.course_code for event in events}, {"ECON2001", "MATH2002"})
        self.assertEqual(events[1].summary, "MATH2002")
        self.assertEqual(len(group_course_events(events)), 2)

    def test_oa_whitelist_ignore_and_participation(self) -> None:
        source = OAScheduleSource("cookie", allowed_event_types=("PERSONAL",))
        raw = {
            "id": 1, "eventType": "PERSONAL", "title": "Mine",
            "tempStartTime": "2026-09-14T09:00:00+08:00",
            "tempEndTime": "2026-09-14T10:00:00+08:00",
        }
        self.assertIsNotNone(source._normalise_event(raw))
        for changed in (
            {"eventType": "CLASS_TIMETABLE"},
            {"eventType": "SCHOOL_PUBLIC"},
            {"eventType": ""},
            {"isIgnore": True},
            {"isJoin": False, "isManage": False},
        ):
            self.assertIsNone(source._normalise_event({**raw, **changed}))
