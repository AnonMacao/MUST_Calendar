from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from calendar_exporter import CalendarEvent, UnifiedCalendarExporter
from login import Login
from sources import ClassTimetableSource, OAScheduleSource


CLASS_TIMETABLE_SITE_URL = (
    "https://classtimetable-coes-wmweb.must.edu.mo/my-class-timetable-student"
)
OA_SCHEDULE_SITE_URL = "https://oa-schedule-new-wmweb.must.edu.mo/"
SUPPORTED_LOCALES = {"zh_MO", "en_US"}
CALENDAR_RANGE_DAYS = 365


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    term_codes: tuple[str, ...]
    username: str
    password: str
    alert_minutes: int
    locale: str
    oa_allowed_event_types: tuple[str, ...] | None = None

    @classmethod
    def from_environment(cls) -> "Configuration":
        term_codes = parse_term_codes(os.environ.get("TERM_CODES", ""))
        username = os.environ.get("USERNAME", "").strip()
        password = os.environ.get("PASSWORD", "")
        locale = os.environ.get("LOCALE", "zh_MO").strip() or "zh_MO"
        # Optional comma-separated eventType whitelist, e.g. EXAM,MEETING,PERSONAL.
        allowed_types_value = os.environ.get("OA_ALLOWED_EVENT_TYPES", "").strip()
        allowed_types = (
            tuple(
                part.strip().upper()
                for part in allowed_types_value.split(",")
                if part.strip()
            )
            if allowed_types_value
            else None
        )

        if not username or not password:
            raise ConfigurationError("USERNAME and PASSWORD are required")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
            raise ConfigurationError("USERNAME cannot be used as a calendar filename")
        if locale not in SUPPORTED_LOCALES:
            raise ConfigurationError("LOCALE must be zh_MO or en_US")

        try:
            alert_minutes = int(os.environ.get("ALERT", "30"))
        except ValueError as error:
            raise ConfigurationError("ALERT must be an integer") from error
        if alert_minutes < 0:
            raise ConfigurationError("ALERT must not be negative")

        return cls(
            term_codes=term_codes,
            username=username,
            password=password,
            alert_minutes=alert_minutes,
            locale=locale,
            oa_allowed_event_types=allowed_types,
        )


def parse_term_codes(value: str) -> tuple[str, ...]:
    term_codes = tuple(part.strip() for part in value.split(",") if part.strip())
    if not term_codes:
        raise ConfigurationError("TERM_CODES must contain at least one term code")
    for term_code in term_codes:
        if len(term_code) != 4 or not term_code.isdigit():
            raise ConfigurationError(f"Invalid term code: {term_code}")
        month = int(term_code[2:])
        if not 1 <= month <= 12:
            raise ConfigurationError(f"Invalid term code: {term_code}")
    if len(set(term_codes)) != len(term_codes):
        raise ConfigurationError("TERM_CODES must not contain duplicate term codes")
    return term_codes


def earliest_term_start(term_codes: tuple[str, ...]) -> date:
    return min(
        date(2000 + int(term_code[:2]), int(term_code[2:]), 1)
        for term_code in term_codes
    )


def course_filename(event: CalendarEvent) -> str:
    code = event.course_code.strip().upper()
    if code:
        stem = re.sub(r"[^A-Z0-9_-]+", "-", code).strip("-_")
        if stem != code:
            stem = f"{stem or 'COURSE'}-{hashlib.sha256(code.encode()).hexdigest()[:10]}"
    else:
        name = event.summary.strip()
        slug = re.sub(r"[^A-Z0-9_-]+", "-", name.upper()).strip("-_")[:48]
        stem = f"{slug or 'COURSE'}-{hashlib.sha256(name.encode()).hexdigest()[:10]}"
    if len(stem) > 80:
        stem = f"{stem[:68].rstrip('-_')}-{hashlib.sha256(code.encode()).hexdigest()[:10]}"
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"COM[1-9]|LPT[1-9]", stem
    ):
        stem = f"COURSE-{stem}"
    return f"{stem}.ics"


def group_course_events(
    events: list[CalendarEvent],
) -> dict[str, list[CalendarEvent]]:
    groups: dict[str, list[CalendarEvent]] = {}
    identities: dict[str, str] = {}
    for event in events:
        filename = course_filename(event)
        identity = event.course_code.strip().upper() or event.summary.strip()
        if filename in identities and identities[filename] != identity:
            raise ValueError(f"Course filename collision: {filename}")
        identities[filename] = identity
        groups.setdefault(filename, []).append(event)
    return groups


def export_calendars(
    class_events: list[CalendarEvent],
    oa_events: list[CalendarEvent],
    alert_minutes: int,
    output_dir: Path = Path("output"),
) -> Path:
    exporter = UnifiedCalendarExporter("oa", output_dir=output_dir)
    groups = group_course_events(class_events)
    courses_dir = output_dir / "courses"
    courses_dir.mkdir(parents=True, exist_ok=True)
    # Only remove .ics files managed inside output/courses after a successful fetch.
    for old_file in courses_dir.glob("*.ics"):
        if old_file.name not in groups:
            old_file.unlink()
    for filename, events in groups.items():
        exporter.export(
            events,
            trigger_minutes=alert_minutes,
            output_path=courses_dir / filename,
            calendar_name=events[0].summary,
        )
    # Keep an empty OA calendar so its subscription URL remains stable.
    exporter.export(
        oa_events,
        trigger_minutes=alert_minutes,
        output_path=output_dir / "oa.ics",
        calendar_name="WeMust OA",
    )
    return output_dir


def run(configuration: Configuration) -> Path:
    login = Login(configuration.username, configuration.password)
    try:
        class_cookie = login.get_site_cookie(
            CLASS_TIMETABLE_SITE_URL,
            "wm.class-timetable.sid",
        )
        oa_cookie = login.get_site_cookie(
            OA_SCHEDULE_SITE_URL,
            "wm.schedule.sid",
        )
    finally:
        login.close()

    today = date.today()
    class_start_date = today - timedelta(days=CALENDAR_RANGE_DAYS)
    end_date = today + timedelta(days=CALENDAR_RANGE_DAYS)

    class_events = ClassTimetableSource(
        class_cookie,
        locale=configuration.locale,
    ).fetch(configuration.term_codes, class_start_date, end_date)
    print(f"Success: {len(class_events)} class timetable events found")

    oa_events = OAScheduleSource(
        oa_cookie,
        locale=configuration.locale,
        allowed_event_types=configuration.oa_allowed_event_types,
    ).fetch(earliest_term_start(configuration.term_codes), end_date)
    print(f"Success: {len(oa_events)} OA schedule events found")

    output_path = export_calendars(
        class_events,
        oa_events,
        configuration.alert_minutes,
    )
    print(f"Success: calendars created in {output_path}")
    return output_path


def main() -> None:
    load_dotenv()
    run(Configuration.from_environment())


if __name__ == "__main__":
    main()
