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


@app.post("/report")
async def report(
    body: ReportBody,
    req: Request
):

    auth = req.headers.get(
        "Authorization",
        ""
    )

    if auth != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(
            401,
            "Unauthorized"
        )

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

    # 最近真正“打开”的 App
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

    # 所有原始记录，用来计算使用时长
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

    # 用来处理：
    # 从 App A 直接切换到 App B 时，
    # open(B) 有可能比 close(A) 更早到服务器
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

            # 同一个 App 重复 open，忽略
            if (
                active_app is not None
                and app_name == active_app
            ):
                continue

            # 已经有一个 App 在使用，
            # 现在又打开另一个 App：
            # 直接把前一个 App 结束在这里
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

                # 接下来几秒内如果又收到 close，
                # 很可能是刚才那个旧 App 的延迟关闭事件
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

            # 如果刚从 A 切到 B，
            # close(A) 可能晚于 open(B) 才到服务器。
            # 这种紧接着出现的 close 不关闭 B。
            if (
                ignore_close_until is not None
                and current_time
                <=
                ignore_close_until
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
