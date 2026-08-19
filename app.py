import sqlite3
import os

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BASE_DIR = Path(__file__).parent

DB_PATH = BASE_DIR / "records.db"

AUTH_TOKEN = os.environ.get(
    "AUTH_TOKEN",
    "换成你的密码"
)


# 中国标准时间 UTC+8
CHINA_OFFSET = timedelta(
    hours=8
)


# =========================
# 数据库
# =========================

def init_db():

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            event TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS curfew_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            paused_until TEXT
        )
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO curfew_settings (
            id,
            paused_until
        )
        VALUES (
            1,
            NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.commit()

    conn.close()


init_db()


# =========================
# FastAPI
# =========================

app = FastAPI(
    title="查岗系统"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================
# 请求模型
# =========================

class ReportBody(BaseModel):

    app_name: str

    event: str


class CurfewPauseBody(BaseModel):

    minutes: int = 60


class ReminderBody(BaseModel):

    title: str

    content: str

    source: str = "curfew"


# =========================
# 权限
# =========================

def check_auth(req: Request):

    auth = req.headers.get(
        "Authorization",
        ""
    )

    if auth != f"Bearer {AUTH_TOKEN}":

        raise HTTPException(
            401,
            "Unauthorized"
        )


# =========================
# 活动记录工具
# =========================

def get_all_activity_rows():

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT app_name, event, timestamp
        FROM records
        ORDER BY id ASC
        """
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def get_activity_rows_before(
    end_utc
):

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT app_name, event, timestamp
        FROM records
        WHERE timestamp < ?
        ORDER BY id ASC
        """,
        (
            end_utc.isoformat(),
        )
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def get_activity_rows_between(
    start_utc,
    end_utc
):

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT app_name, event, timestamp
        FROM records
        WHERE timestamp >= ?
        AND timestamp < ?
        ORDER BY id ASC
        """,
        (
            start_utc.isoformat(),
            end_utc.isoformat(),
        )
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def get_china_today_utc_range():

    now_utc = datetime.utcnow()

    now_local = (
        now_utc
        +
        CHINA_OFFSET
    )

    start_local = datetime.combine(
        now_local.date(),
        datetime.min.time()
    )

    end_local = (
        start_local
        +
        timedelta(days=1)
    )

    start_utc = (
        start_local
        -
        CHINA_OFFSET
    )

    end_utc = (
        end_local
        -
        CHINA_OFFSET
    )

    return (
        start_utc,
        end_utc
    )


def analyze_activity(rows):

    sessions = {}

    active_app = None

    active_start = None

    ignore_close_until = None

    last_activity_at = None

    last_event = None

    last_app_name = None


    for row in rows:

        app_name, event, ts = row

        app_name = (
            app_name or ""
        ).strip()

        current_time = datetime.fromisoformat(
            ts
        )


        last_activity_at = current_time

        last_event = event

        if app_name:

            last_app_name = app_name


        if event == "open":

            if (
                active_app is not None
                and app_name == active_app
            ):

                continue


            if (
                active_app is not None
                and active_start is not None
            ):

                gap = int(
                    (
                        current_time
                        -
                        active_start
                    ).total_seconds()
                )

                if gap >= 0:

                    sessions[active_app] = (
                        sessions.get(
                            active_app,
                            0
                        )
                        +
                        gap
                    )


                ignore_close_until = (
                    current_time
                    +
                    timedelta(seconds=5)
                )

            else:

                ignore_close_until = None


            if app_name:

                active_app = app_name

                active_start = current_time

            else:

                active_app = None

                active_start = None


        elif event == "close":

            if (
                active_app is None
                or active_start is None
            ):

                continue


            if (
                ignore_close_until is not None
                and current_time
                <= ignore_close_until
            ):

                ignore_close_until = None

                continue


            gap = int(
                (
                    current_time
                    -
                    active_start
                ).total_seconds()
            )


            if gap >= 0:

                sessions[active_app] = (
                    sessions.get(
                        active_app,
                        0
                    )
                    +
                    gap
                )


            active_app = None

            active_start = None

            ignore_close_until = None


    return {

        "sessions":
            sessions,

        "active_app":
            active_app,

        "active_start":
            active_start,

        "last_activity_at":
            last_activity_at,

        "last_event":
            last_event,

        "last_app_name":
            last_app_name

    }


# =========================
# 宵禁状态工具
# =========================

def get_curfew_pause_until():

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT paused_until
        FROM curfew_settings
        WHERE id = 1
        """
    )

    row = cur.fetchone()

    conn.close()


    if not row:

        return None


    value = row[0]


    if not value:

        return None


    try:

        return datetime.fromisoformat(
            value
        )

    except Exception:

        return None


def set_curfew_pause_until(
    pause_until
):

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    conn.execute(
        """
        UPDATE curfew_settings
        SET paused_until = ?
        WHERE id = 1
        """,
        (
            pause_until.isoformat()
            if pause_until
            else None,
        )
    )

    conn.commit()

    conn.close()


def get_curfew_status_data():

    now_utc = datetime.utcnow()

    paused_until = (
        get_curfew_pause_until()
    )


    is_paused = bool(
        paused_until
        and
        paused_until > now_utc
    )


    if (
        paused_until
        and
        paused_until <= now_utc
    ):

        set_curfew_pause_until(
            None
        )

        paused_until = None


    paused_until_local = None


    if paused_until:

        paused_until_local = (
            paused_until
            +
            CHINA_OFFSET
        )


    return {

        "is_paused":
            is_paused,

        "paused_until_utc":
            (
                paused_until.isoformat()
                if paused_until
                else None
            ),

        "paused_until_local":
            (
                paused_until_local.isoformat()
                if paused_until_local
                else None
            ),

        "server_time_utc":
            now_utc.isoformat()

    }


# =========================
# 提醒工具
# =========================

def save_reminder(
    title,
    content,
    source="curfew"
):

    now = datetime.utcnow().isoformat()

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO reminders (
            title,
            content,
            source,
            created_at,
            delivered
        )
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            title,
            content,
            source,
            now
        )
    )

    reminder_id = cur.lastrowid

    conn.commit()

    conn.close()

    return reminder_id


def consume_pending_reminders():

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            title,
            content,
            source,
            created_at
        FROM reminders
        WHERE delivered = 0
        ORDER BY id ASC
        LIMIT 20
        """
    )

    rows = cur.fetchall()


    ids = [
        row[0]
        for row in rows
    ]


    if ids:

        placeholders = ",".join(
            "?"
            for _ in ids
        )

        cur.execute(
            f"""
            UPDATE reminders
            SET delivered = 1
            WHERE id IN ({placeholders})
            """,
            ids
        )

        conn.commit()


    conn.close()


    reminders = []


    for row in rows:

        (
            reminder_id,
            title,
            content,
            source,
            created_at
        ) = row


        created_utc = datetime.fromisoformat(
            created_at
        )

        created_local = (
            created_utc
            +
            CHINA_OFFSET
        )


        reminders.append(
            {
                "id":
                    reminder_id,

                "title":
                    title,

                "content":
                    content,

                "source":
                    source,

                "created_at_utc":
                    created_at,

                "created_at_local":
                    created_local.isoformat()
            }
        )


    return reminders


# =========================
# 手机上报
# =========================

@app.post("/report")
async def report(
    body: ReportBody,
    req: Request
):

    check_auth(req)

    now = datetime.utcnow().isoformat()

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    conn.execute(
        """
        INSERT INTO records (
            app_name,
            event,
            timestamp
        )
        VALUES (?, ?, ?)
        """,
        (
            body.app_name,
            body.event,
            now
        )
    )

    conn.commit()

    conn.close()

    return {
        "status": "ok"
    }


# =========================
# Ping
# =========================

@app.get("/ping")
async def ping():

    return "pong"


# =========================
# 活动摘要
# =========================

@app.get("/activity/summary")
async def summary():

    (
        start_utc,
        end_utc
    ) = get_china_today_utc_range()


    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT app_name
        FROM records
        WHERE event = 'open'
        AND TRIM(app_name) != ''
        AND timestamp >= ?
        AND timestamp < ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            start_utc.isoformat(),
            end_utc.isoformat(),
        )
    )

    recent = cur.fetchall()

    conn.close()


    rows = get_activity_rows_between(
        start_utc,
        end_utc
    )


    previous_rows = get_activity_rows_before(
        start_utc
    )

    previous_activity = analyze_activity(
        previous_rows
    )


    if (
        previous_activity["active_app"]
        is not None
        and
        previous_activity["active_start"]
        is not None
    ):

        rows.insert(
            0,
            (
                previous_activity["active_app"],
                "open",
                start_utc.isoformat()
            )
        )


    activity = analyze_activity(
        rows
    )


    return {

        "recent_apps": [
            r[0]
            for r in recent
        ],

        "sessions":
            activity["sessions"]

    }


# =========================
# 最新活动
# =========================

@app.get("/activity/latest")
async def latest_activity(
    req: Request
):

    check_auth(req)


    rows = get_all_activity_rows()

    activity = analyze_activity(
        rows
    )


    last_activity_at = activity[
        "last_activity_at"
    ]

    active_start = activity[
        "active_start"
    ]


    return {

        "server_time_utc":
            datetime.utcnow().isoformat(),

        "last_activity_at":
            (
                last_activity_at.isoformat()
                if last_activity_at
                else None
            ),

        "last_event":
            activity["last_event"],

        "last_app":
            activity["last_app_name"],

        "is_active":
            activity["active_app"] is not None,

        "active_app":
            activity["active_app"],

        "active_since":
            (
                active_start.isoformat()
                if active_start
                else None
            )

    }


# =========================
# 宵禁状态
# =========================

@app.get("/curfew/status")
async def curfew_status(
    req: Request
):

    check_auth(req)

    return get_curfew_status_data()


# =========================
# 暂停指定分钟
# =========================

@app.post("/curfew/pause")
async def curfew_pause(
    body: CurfewPauseBody,
    req: Request
):

    check_auth(req)


    minutes = max(
        1,
        min(
            int(body.minutes),
            720
        )
    )


    now_utc = datetime.utcnow()

    pause_until = (
        now_utc
        +
        timedelta(
            minutes=minutes
        )
    )


    set_curfew_pause_until(
        pause_until
    )


    pause_until_local = (
        pause_until
        +
        CHINA_OFFSET
    )


    return {

        "status":
            "paused",

        "minutes":
            minutes,

        "paused_until_utc":
            pause_until.isoformat(),

        "paused_until_local":
            pause_until_local.isoformat()

    }


# =========================
# 今晚不再提醒
# =========================

@app.post("/curfew/allow-tonight")
async def curfew_allow_tonight(
    req: Request
):

    check_auth(req)


    now_utc = datetime.utcnow()

    now_local = (
        now_utc
        +
        CHINA_OFFSET
    )


    if (
        now_local.hour > 6
        or
        (
            now_local.hour == 6
            and
            now_local.minute > 0
        )
    ):

        tomorrow = (
            now_local.date()
            +
            timedelta(days=1)
        )

        pause_until_local = datetime.combine(
            tomorrow,
            datetime.min.time()
        ).replace(
            hour=6
        )

    else:

        pause_until_local = datetime.combine(
            now_local.date(),
            datetime.min.time()
        ).replace(
            hour=6
        )


    pause_until_utc = (
        pause_until_local
        -
        CHINA_OFFSET
    )


    set_curfew_pause_until(
        pause_until_utc
    )


    return {

        "status":
            "allowed_tonight",

        "paused_until_utc":
            pause_until_utc.isoformat(),

        "paused_until_local":
            pause_until_local.isoformat()

    }


# =========================
# 恢复提醒
# =========================

@app.post("/curfew/resume")
async def curfew_resume(
    req: Request
):

    check_auth(req)

    set_curfew_pause_until(
        None
    )

    return {

        "status":
            "resumed",

        "message":
            "Curfew reminders resumed"

    }


# =========================
# 保存一条提醒
# =========================

@app.post("/reminders/push")
async def reminder_push(
    body: ReminderBody,
    req: Request
):

    check_auth(req)


    reminder_id = save_reminder(
        body.title,
        body.content,
        body.source
    )


    return {

        "status":
            "saved",

        "id":
            reminder_id

    }


# =========================
# 读取并消费未读提醒
# =========================

@app.post("/reminders/consume")
async def reminder_consume(
    req: Request
):

    check_auth(req)


    reminders = (
        consume_pending_reminders()
    )


    return {

        "count":
            len(
                reminders
            ),

        "reminders":
            reminders

    }


# =========================
# Railway 启动
# =========================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.environ.get(
            "PORT",
            8000
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
