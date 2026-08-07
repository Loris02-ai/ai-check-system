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

    conn.commit()

    conn.close()


init_db()


app = FastAPI(
    title="查岗系统"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


class ReportBody(BaseModel):

    app_name: str

    event: str


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


@app.get("/ping")
async def ping():

    return "pong"


@app.get("/activity/summary")
async def summary():

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
        ORDER BY id DESC
        LIMIT 5
        """
    )

    recent = cur.fetchall()

    conn.close()


    rows = get_all_activity_rows()

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
