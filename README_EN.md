# MUST Calendar

[English](README_EN.md) | [简体中文](README.md)

Export the Macau University of Science and Technology student timetable and WeMust OA schedule as separate ICS subscriptions for iOS, Android, HarmonyOS, macOS, and Windows calendars.

The program signs in to MUST CAS once and then reads:

- Student timetable: course names, rooms, teachers, and lesson times
- WeMust OA schedule: activities, meetings, holidays, and other personal events

Each course is exported to `output/courses/<courseCode>.ics`, with a readable calendar name. Filtered OA events are exported to `output/oa.ics`. An empty OA calendar is still written so its subscription URL remains stable.

## Local setup

1. Clone the repository.
2. Create `.env` in the project directory:

    ```dotenv
    TERM_CODES=2609,2702
    USERNAME=Your student ID
    PASSWORD=Your WeMust password
    ALERT=30
    LOCALE=en_US
    OA_ALLOWED_EVENT_TYPES=EXAM,MEETING,PERSONAL
    CHROMEDRIVER_PATH=.venv/bin/chromedriver
    ```

3. Install a ChromeDriver whose major version matches Chrome: [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/#stable). Omit `CHROMEDRIVER_PATH` if ChromeDriver is already in `PATH`.
4. Create a virtual environment and run the exporter:

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python ./main.py
    ```

`TERM_CODES` accepts comma-separated four-digit term codes. The complete timetable is fetched once per term, then grouped locally. OA events run from the first day of the earliest configured term month through one year after the current date. `OA_ALLOWED_EVENT_TYPES` is an optional comma-separated `eventType` whitelist; when unset, the default is `PERSONAL`, `EXAM`, `MEETING`, and `LEAVE_CALENDER`. Ignored and `CLASS_TIMETABLE` events are always excluded. If the API supplies both `isJoin` and `isManage`, events with neither flag set are excluded. Stale `.ics` files in `output/courses` are removed after a successful fetch.

## GitHub Actions deployment

1. Fork the repository and enable Actions.
2. Add these repository secrets under `Settings` → `Security` → `Secrets and variables` → `Actions`:
   - `USERNAME`: student ID
   - `PASSWORD`: WeMust password
3. Set `TERM_CODES`, `ALERT`, and `LOCALE` in [.github/workflows/python-app.yml](.github/workflows/python-app.yml). Optionally set `OA_ALLOWED_EVENT_TYPES` as an Actions repository variable.
4. Run `Update TimeTable Everyday` once and verify `output/courses/*.ics` and `output/oa.ics` are created.

Subscription URL:

```text
https://raw.githubusercontent.com/yourGitHubAccount/MUST_Calendar/main/output/courses/ECON2001.ics
```
## TODO

- [x] Multiple terms
- [x] Multiple languages
- [x] WeMust OA schedule integration
- [ ] Exam calendar

PRs and Issues are welcome!
