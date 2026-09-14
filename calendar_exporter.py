from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from icalendar import Alarm, Calendar, Event


CALENDAR_PRODID = "MUST Calendar"
CALENDAR_UID_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "urn:must-calendar:calendar-event",
)


@dataclass(frozen=True)
class CalendarEvent:
    source: str
    source_id: str
    summary: str
    start: date | datetime
    end: date | datetime
    location: str = ""
    description: str = ""
    course_code: str = ""

    def __post_init__(self) -> None:
        start_is_datetime = isinstance(self.start, datetime)
        end_is_datetime = isinstance(self.end, datetime)
        if start_is_datetime != end_is_datetime:
            raise ValueError("Event start and end must use the same value type")
        if start_is_datetime:
            if self.start.tzinfo is None or self.end.tzinfo is None:
                raise ValueError("Timed events must include timezone information")
        if self.end < self.start:
            raise ValueError("Event end must not be earlier than event start")
        if not self.source or not self.source_id:
            raise ValueError("Event source identity must not be empty")
        if not self.summary.strip():
            raise ValueError("Event summary must not be empty")

    @property
    def identity(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def is_all_day(self) -> bool:
        return not isinstance(self.start, datetime)


class UnifiedCalendarExporter:
    def __init__(self, student_id: str, output_dir: Path | str = "output"):
        self.student_id = student_id
        self.output_dir = Path(output_dir)

    @property
    def output_path(self) -> Path:
        return self.output_dir / f"{self.student_id}.ics"

    def build(
        self,
        events: Iterable[CalendarEvent],
        trigger_minutes: int = 30,
        generated_at: datetime | None = None,
        calendar_name: str = CALENDAR_PRODID,
    ) -> Calendar:
        if trigger_minutes < 0:
            raise ValueError("Reminder minutes must not be negative")

        generated_at = generated_at or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            raise ValueError(
                "Calendar generation time must include timezone information"
            )
        generated_at = generated_at.astimezone(timezone.utc)

        unique_events: dict[str, CalendarEvent] = {}
        for calendar_event in events:
            existing = unique_events.get(calendar_event.identity)
            if existing is not None and existing != calendar_event:
                raise ValueError(
                    "Conflicting calendar events share identity "
                    f"{calendar_event.identity}"
                )
            unique_events[calendar_event.identity] = calendar_event

        calendar = Calendar()
        calendar.add("version", "2.0")
        calendar.add("prodid", CALENDAR_PRODID)
        calendar.add("x-wr-calname", calendar_name)

        for calendar_event in sorted(unique_events.values(), key=_event_sort_key):
            component = Event()
            event_uid = uuid5(CALENDAR_UID_NAMESPACE, calendar_event.identity)
            component.add("uid", f"urn:uuid:{event_uid}")
            component.add("summary", calendar_event.summary)
            component.add("dtstamp", generated_at)

            if calendar_event.is_all_day:
                component.add("dtstart", calendar_event.start)
                component.add("dtend", calendar_event.end)
            else:
                component.add("dtstart", calendar_event.start.astimezone(timezone.utc))
                component.add("dtend", calendar_event.end.astimezone(timezone.utc))

            if calendar_event.location:
                component.add("location", calendar_event.location)
            if calendar_event.description:
                component.add("description", calendar_event.description)

            if not calendar_event.is_all_day:
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", calendar_event.summary)
                alarm.add("trigger", timedelta(minutes=-trigger_minutes))
                component.add_component(alarm)

            calendar.add_component(component)

        return calendar

    def export(
        self,
        events: Iterable[CalendarEvent],
        trigger_minutes: int = 30,
        generated_at: datetime | None = None,
        output_path: Path | None = None,
        calendar_name: str = CALENDAR_PRODID,
    ) -> Path:
        calendar = self.build(events, trigger_minutes, generated_at, calendar_name)
        path = output_path or self.output_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(calendar.to_ical())
        return path


def _event_sort_key(calendar_event: CalendarEvent) -> tuple[datetime, str]:
    if calendar_event.is_all_day:
        start = datetime.combine(
            calendar_event.start,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    else:
        start = calendar_event.start.astimezone(timezone.utc)
    return start, calendar_event.identity
