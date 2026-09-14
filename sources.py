from __future__ import annotations

import calendar
import hashlib
import html
import re
import secrets
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from calendar_exporter import CalendarEvent


CLASS_TIMETABLE_API_URL = (
    "https://classtimetable-coes-wmweb.must.edu.mo/"
    "x-class-timetable-api/lessons/student-exam-webs"
)
CLASS_TIMETABLE_REFERER = (
    "https://classtimetable-coes-wmweb.must.edu.mo/my-class-timetable-student"
)
OA_SCHEDULE_API_URL = (
    "https://oa-schedule-new-wmweb.must.edu.mo/"
    "x-schedule-api/events/events/by-date"
)
OA_SCHEDULE_SERVICE_TYPES_API_URL = (
    "https://oa-schedule-new-wmweb.must.edu.mo/"
    "x-schedule-api/datas/tags"
)
OA_SCHEDULE_REFERER = "https://oa-schedule-new-wmweb.must.edu.mo/"
OA_SCHEDULE_API_SALT = "wm_oa_schedule_new"
OA_SCHEDULE_SERVICE_CODE = "S-WM-SCHEDULE-NEW"
OA_ALL_DAY_EVENT_TYPES = {"LEAVE_CALENDER"}
# Conservative default; set OA_ALLOWED_EVENT_TYPES to replace this list.
DEFAULT_OA_ALLOWED_EVENT_TYPES = frozenset(
    {"PERSONAL", "EXAM", "MEETING", "LEAVE_CALENDER"}
)
MACAU_TIMEZONE = ZoneInfo("Asia/Macau")
REQUEST_TIMEOUT_SECONDS = 30

_BR_TAG_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


class SourceDataError(RuntimeError):
    pass


class ClassTimetableSource:
    def __init__(
        self,
        cookie_value: str,
        locale: str = "zh_MO",
        session: requests.Session | None = None,
    ):
        self.locale = locale
        self.session = session or requests.Session()
        self.headers = _request_headers(
            CLASS_TIMETABLE_REFERER,
            f"wm.class-timetable.sid={cookie_value}",
        )

    def fetch(
        self,
        term_codes: Iterable[str],
        start_date: date,
        end_date: date,
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for term_code in term_codes:
            response = self.session.get(
                CLASS_TIMETABLE_API_URL,
                params={
                    "lang": self.locale,
                    "termCode": term_code,
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                },
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            payload = _response_payload(response, "class timetable")
            model = payload.get("model")
            lessons = model.get("lesson") if isinstance(model, Mapping) else None
            if not isinstance(lessons, list):
                raise SourceDataError("Class timetable response has no lesson list")

            for lesson in lessons:
                if not isinstance(lesson, Mapping):
                    raise SourceDataError("Class timetable contains an invalid lesson")
                event = self._normalise_lesson(term_code, lesson)
                if event is not None:
                    events.append(event)
        return events

    def _normalise_lesson(
        self,
        term_code: str,
        lesson: Mapping[str, Any],
    ) -> CalendarEvent | None:
        if _text(lesson.get("status")).upper() == "CANCEL":
            return None

        lesson_id = lesson.get("id")
        if lesson_id is None:
            raise SourceDataError("Class timetable lesson has no id")

        lesson_date = _required_date(lesson.get("lessonDate"), "lessonDate")
        start = _local_datetime(
            lesson_date,
            lesson.get("lessonStartTime"),
            "lessonStartTime",
        )
        end = _local_datetime(
            lesson_date,
            lesson.get("lessonEndTime"),
            "lessonEndTime",
        )
        if end < start:
            end += timedelta(days=1)

        if self.locale == "en_US":
            summary = _first_text(
                lesson.get("courseEnName"),
                lesson.get("courseName"),
                lesson.get("courseCode"),
            )
            location = _first_text(
                lesson.get("roomEngDesc"),
                lesson.get("roomChnDesc"),
            )
            teacher = _first_text(
                lesson.get("teacherEnName"),
                lesson.get("teacherName"),
            )
            description = f"Teacher: {teacher}" if teacher else ""
        else:
            summary = _first_text(
                lesson.get("courseName"),
                lesson.get("courseEnName"),
                lesson.get("courseCode"),
            )
            location = _first_text(
                lesson.get("roomChnDesc"),
                lesson.get("roomEngDesc"),
            )
            teacher = _first_text(
                lesson.get("teacherName"),
                lesson.get("teacherEnName"),
            )
            description = f"教師姓名: {teacher}" if teacher else ""

        if not summary:
            summary = f"Course {lesson_id}" if self.locale == "en_US" else f"課程 {lesson_id}"

        return CalendarEvent(
            source="class-timetable",
            source_id=f"{term_code}:{lesson_id}",
            summary=summary,
            start=start,
            end=end,
            location=location,
            description=description,
            course_code=_text(lesson.get("courseCode")),
        )


class OAScheduleSource:
    def __init__(
        self,
        cookie_value: str,
        locale: str = "zh_MO",
        session: requests.Session | None = None,
        nonce_factory: Callable[[], str] | None = None,
        allowed_event_types: Iterable[str] | None = None,
    ):
        self.locale = locale
        self.session = session or requests.Session()
        self.nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self.allowed_event_types = (
            frozenset(
                _text(value).upper()
                for value in allowed_event_types
                if _text(value)
            )
            if allowed_event_types is not None
            else DEFAULT_OA_ALLOWED_EVENT_TYPES
        )
        self.headers = _request_headers(
            OA_SCHEDULE_REFERER,
            f"wm.schedule.sid={cookie_value}",
        )

    def fetch(self, start_date: date, end_date: date) -> list[CalendarEvent]:
        service_ids = self._fetch_service_ids()
        events_by_id: dict[str, CalendarEvent] = {}
        for window_start, window_end in iter_date_windows(start_date, end_date):
            params = self._signed_params(window_start, window_end, service_ids)
            response = self.session.get(
                OA_SCHEDULE_API_URL,
                params=params,
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            payload = _response_payload(response, "OA schedule")
            groups = payload.get("model")
            if groups is None:
                groups = []
            if not isinstance(groups, list):
                raise SourceDataError("OA schedule response has no event group list")

            for group in groups:
                if not isinstance(group, Mapping):
                    raise SourceDataError("OA schedule contains an invalid event group")
                raw_events = group.get("events")
                if not isinstance(raw_events, list):
                    raise SourceDataError("OA schedule event group has no event list")

                for raw_event in raw_events:
                    if not isinstance(raw_event, Mapping):
                        raise SourceDataError("OA schedule contains an invalid event")
                    event = self._normalise_event(raw_event)
                    if event is None:
                        continue
                    event_start_date = (
                        event.start.date()
                        if isinstance(event.start, datetime)
                        else event.start
                    )
                    if not start_date <= event_start_date <= end_date:
                        continue
                    existing = events_by_id.get(event.source_id)
                    if existing is not None and existing != event:
                        raise SourceDataError(
                            f"OA schedule event {event.source_id} has conflicting data"
                        )
                    events_by_id[event.source_id] = event

        return list(events_by_id.values())

    def _fetch_service_ids(self) -> tuple[str, ...]:
        params: dict[str, Any] = {
            "key": "SERVICE",
            "lang": self.locale,
            "nonce": self.nonce_factory(),
            "serviceCode": OA_SCHEDULE_SERVICE_CODE,
        }
        params["signature"] = build_signature(params, OA_SCHEDULE_API_SALT)
        response = self.session.get(
            OA_SCHEDULE_SERVICE_TYPES_API_URL,
            params=params,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        payload = _response_payload(response, "OA schedule service types")
        services = payload.get("model")
        if not isinstance(services, list):
            raise SourceDataError("OA schedule response has no service type list")

        service_ids: list[str] = []
        for service in services:
            if not isinstance(service, Mapping):
                raise SourceDataError("OA schedule contains an invalid service type")
            service_id = _text(service.get("code"))
            if not service_id.isdigit():
                raise SourceDataError("OA schedule service type has an invalid code")
            service_ids.append(service_id)

        if not service_ids:
            raise SourceDataError("OA schedule has no available service types")
        if len(set(service_ids)) != len(service_ids):
            raise SourceDataError("OA schedule contains duplicate service types")
        return tuple(service_ids)

    def _signed_params(
        self,
        start_date: date,
        end_date: date,
        service_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "dataSource": 1,
            "startTime": start_date.isoformat(),
            "endTime": end_date.isoformat(),
            "isJoin": 1,
            "isManage": 1,
            "isIgnore": 0,
            "serviceIds": list(service_ids),
            "lang": self.locale,
            "nonce": self.nonce_factory(),
        }
        params["signature"] = build_signature(params, OA_SCHEDULE_API_SALT)
        return params

    def _normalise_event(
        self,
        raw_event: Mapping[str, Any],
    ) -> CalendarEvent | None:
        if not should_include_oa_event(raw_event, self.allowed_event_types):
            return None
        event_type = _text(raw_event.get("eventType")).upper()

        event_id = raw_event.get("id")
        if event_id is None:
            raise SourceDataError("OA schedule event has no id")

        is_all_day = (
            event_type in OA_ALL_DAY_EVENT_TYPES
            or _is_true(raw_event.get("isAllDay"))
        )
        if is_all_day:
            start: date | datetime = _required_date(
                raw_event.get("tempStartTime"),
                "tempStartTime",
            )
            inclusive_end = _required_date(
                raw_event.get("tempEndTime"),
                "tempEndTime",
            )
            if inclusive_end < start:
                raise SourceDataError(
                    f"OA schedule event {event_id} ends before it starts"
                )
            end: date | datetime = inclusive_end + timedelta(days=1)
        else:
            start = _required_local_datetime(
                raw_event.get("tempStartTime"),
                "tempStartTime",
            )
            end = _required_local_datetime(
                raw_event.get("tempEndTime"),
                "tempEndTime",
            )
            if end < start:
                end += timedelta(days=1)

        summary = _text(raw_event.get("title"))
        if not summary:
            summary = "Untitled event" if self.locale == "en_US" else "未命名日程"

        return CalendarEvent(
            source="oa-schedule",
            source_id=str(event_id),
            summary=summary,
            start=start,
            end=end,
            location=_text(raw_event.get("address")),
            description=_plain_text(raw_event.get("remark")),
        )


def should_include_oa_event(
    raw_event: Mapping[str, Any], allowed_event_types: frozenset[str]
) -> bool:
    if _is_true(raw_event.get("isIgnore")):
        return False
    event_type = _text(raw_event.get("eventType")).upper()
    if event_type == "CLASS_TIMETABLE" or event_type not in allowed_event_types:
        return False
    # When the API supplies both participation flags, exclude visible public items.
    if "isJoin" in raw_event and "isManage" in raw_event:
        return _is_true(raw_event["isJoin"]) or _is_true(raw_event["isManage"])
    return True


def build_signature(params: Mapping[str, Any], salt: str) -> str:
    pairs: list[tuple[str, Any]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            value = value[0]
        pairs.append((key, value))

    message = "".join(
        f"{key}={_signature_value(value)}" for key, value in sorted(pairs)
    )
    return hashlib.md5(f"{message}{salt}".encode("utf-8")).hexdigest()


def iter_date_windows(
    start_date: date,
    end_date: date,
) -> Iterable[tuple[date, date]]:
    if end_date < start_date:
        raise ValueError("Date range end must not be earlier than start")

    cursor = start_date
    while cursor <= end_date:
        window_end = min(_add_months(cursor, 3) - timedelta(days=1), end_date)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _request_headers(referer: str, cookie: str) -> dict[str, str]:
    return {
        "Cookie": cookie,
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
    }


def _response_payload(
    response: requests.Response,
    source_name: str,
) -> Mapping[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise SourceDataError(f"Unable to read {source_name} response") from error

    if not isinstance(payload, Mapping):
        raise SourceDataError(f"{source_name} response is not an object")
    if payload.get("success") is False:
        code = _text(payload.get("errorCode")) or "UNKNOWN"
        raise SourceDataError(f"{source_name} request failed with {code}")
    return payload


def _required_date(value: Any, field_name: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise SourceDataError(f"Invalid {field_name}")
    return parsed


def _optional_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _local_datetime(day: date, value: Any, field_name: str) -> datetime:
    text = _text(value)
    try:
        parsed_time = time.fromisoformat(text)
    except ValueError as error:
        raise SourceDataError(f"Invalid {field_name}") from error
    return datetime.combine(day, parsed_time, tzinfo=MACAU_TIMEZONE)


def _required_local_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise SourceDataError(f"Invalid {field_name}") from error

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MACAU_TIMEZONE)
    return parsed.astimezone(MACAU_TIMEZONE)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _signature_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _plain_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    text = _BR_TAG_PATTERN.sub("\n", text)
    text = _HTML_TAG_PATTERN.sub("", text)
    text = html.unescape(text).replace("\r", "")
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return _text(value).lower() in {"1", "true", "yes"}
