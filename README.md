# MUST_Calendar 

[English](README_EN.md) | [简体中文](README.md)

将澳门科技大学的学生课表与 WeMust OA 日程导出为独立的 ICS 订阅，支持 iOS、Android、HarmonyOS、macOS 和 Windows 系统日历。

程序只登录一次 MUST 统一认证，然后分别读取：

- 学生课表：课程名称、教室、教师与上课时间
- WeMust OA 日程：活动、会议、假期及其他个人日程

每门课程按 `courseCode` 导出到 `output/courses/<courseCode>.ics`，OA 日程单独导出到 `output/oa.ics`。课程名称显示在日历标题中；OA 中的 `CLASS_TIMETABLE`、已忽略和非白名单事项会被过滤。空 OA 日程也会生成有效的空日历，以保持订阅地址不变。

## 本地运行

1. Clone 仓库。
2. 在项目目录新建 `.env`：

    ```dotenv
    TERM_CODES=2609,2702
    USERNAME=你的学号
    PASSWORD=你的 WeMust 密码
    ALERT=30
    LOCALE=zh_MO
    OA_ALLOWED_EVENT_TYPES=EXAM,MEETING,PERSONAL
    CHROMEDRIVER_PATH=.venv/bin/chromedriver
    ```

3. 安装与本机 Chrome 主版本一致的 ChromeDriver：[Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/#stable)。如果 ChromeDriver 已在 `PATH` 中，可以省略 `CHROMEDRIVER_PATH`。
4. 建立虚拟环境并运行：

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python ./main.py
    ```

`TERM_CODES` 支持多个四位学期代码，以逗号分隔；每个学期读取一次完整课表，再在本地按课程分组。OA 日程从最早学期代码对应月份的 1 日开始，到当前日期后一年为止。`OA_ALLOWED_EVENT_TYPES` 是可选的逗号分隔 `eventType` 白名单；未设置时默认保留 `PERSONAL`、`EXAM`、`MEETING`、`LEAVE_CALENDER`。API 同时提供 `isJoin` 和 `isManage` 时，还会排除两者均为假的公共可见事项。退课后 `output/courses` 中不再对应当前课表的 `.ics` 会自动删除。

## GitHub Actions 部署

1. Fork仓库
2. 在 `Settings` → `Security` → `Secrets and variables` → `Actions` 中添加：
   - `USERNAME`：学号
   - `PASSWORD`：WeMust 密码
3. 在 [.github/workflows/python-app.yml](.github/workflows/python-app.yml) 中设置 `TERM_CODES`、`ALERT` 和 `LOCALE`。可选：在 Actions 的 repository variables 中设置 `OA_ALLOWED_EVENT_TYPES`。
4. 手动运行一次 `Update TimeTable Everyday`，确认 `output/courses/*.ics` 和 `output/oa.ics` 已生成。

### 使用方法（以IOS为例）

1. 打开日历
2. 日历-添加日历-添加订阅日历
3. 输入某门课程的订阅地址，例如 `https://raw.githubusercontent.com/你的GitHub账号/MUST_Calendar/main/output/courses/ECON2001.ics`。OA 地址为 `https://raw.githubusercontent.com/你的GitHub账号/MUST_Calendar/main/output/oa.ics`。

日历会在每天凌晨更新，可在```.github/workflows/python-app.yml```中修改。

## TODO

- [x] 多学期(2025.5.9)
- [x] 多语言支持(2025.5.23)
- [x] 合并 WeMust OA 日程(2026.8.31)
- [ ] 考试日历

欢迎PR和Issues！
