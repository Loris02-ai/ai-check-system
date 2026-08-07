import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "records.db"

JST = timedelta(hours=9)

AUTH_TOKEN = os.environ.get(
    "AUTH_TOKEN",
    "换成你的密码"
)


def init_db():
    conn = sqlite3.connect(str(DB_PATH))

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


@app.post("/report")
async def report(
    body: ReportBody,
    req: Request
):

    check_auth(req)

    now = datetime.utcnow().isoformat()

    # 临时调试：Railway Logs 可以直接看到
    # iPhone 实际传来了什么
    print(
        f"REPORT: app_name={body.app_name!r}, "
        f"event={body.event!r}, "
        f"timestamp={now}",
        flush=True
    )

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


@app.get("/activity/debug")
async def debug_records(
    req: Request
):

    check_auth(req)

    conn = sqlite3.connect(
        str(DB_PATH)
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, app_name, event, timestamp
        FROM records
        ORDER BY id DESC
        LIMIT 20
        """
    )

    rows = cur.fetchall()

    conn.close()

    return {
        "records": [
            {
                "id": row[0],
                "app_name": row[1],
                "event": row[2],
                "timestamp": row[3]
            }
            for row in rows
        ]
    }


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

    cur.execute(
        """
        SELECT app_name, event, timestamp
        FROM records
        ORDER BY id ASC
        """
    )

    rows = cur.fetchall()

    conn.close()

    sessions = {}

    active_app = None
    active_start = None

    ignore_close_until = None

    for row in rows:

        app_name, event, ts = row

        app_name = (
            app_name or ""
        ).strip()

        current_time = datetime.fromisoformat(
            ts
        )

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
        "recent_apps": [
            r[0]
            for r in recent
        ],
        "sessions": sessions
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
