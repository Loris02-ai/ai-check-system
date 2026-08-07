import json
import os

from datetime import datetime, timezone, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
from urllib.request import Request, urlopen


# =========================
# 配置
# =========================

ORIGIN_API = os.environ.get(
    "ORIGIN_API",
    ""
).rstrip("/")

AUTH_TOKEN = os.environ.get(
    "AUTH_TOKEN",
    ""
).strip()

BARK_API_KEY = os.environ.get(
    "BARK_API_KEY",
    ""
).strip()


# 南宁 / 中国标准时间
LOCAL_TZ = ZoneInfo(
    "Asia/Shanghai"
)


# 22:30 后算熬夜
CURFEW_START = time(
    22,
    30
)

# 暂定早上 06:00 结束宵禁
CURFEW_END = time(
    6,
    0
)


# Railway 每 15 分钟检查一次
# 所以如果刚刚结束使用，
# 20 分钟以内仍视为宵禁期间使用过手机
RECENT_ACTIVITY_MINUTES = 20


# =========================
# HTTP
# =========================

def get_latest_activity():

    url = (
        f"{ORIGIN_API}/activity/latest"
    )

    req = Request(
        url,
        headers={
            "Authorization":
                f"Bearer {AUTH_TOKEN}",
            "User-Agent":
                "Robin-Curfew/1.0"
        }
    )

    with urlopen(
        req,
        timeout=15
    ) as response:

        text = response.read().decode(
            "utf-8"
        )

        return json.loads(
            text
        )


def send_bark(
    title,
    content
):

    safe_key = quote(
        BARK_API_KEY,
        safe=""
    )

    safe_title = quote(
        title,
        safe=""
    )

    safe_content = quote(
        content,
        safe=""
    )

    url = (
        "https://api.day.app/"
        f"{safe_key}/"
        f"{safe_title}/"
        f"{safe_content}"
    )

    req = Request(
        url,
        headers={
            "User-Agent":
                "Robin-Curfew/1.0"
        }
    )

    with urlopen(
        req,
        timeout=15
    ) as response:

        return response.getcode()


# =========================
# 时间判断
# =========================

def is_curfew_time(
    now_local
):

    current = now_local.time()

    return (
        current >= CURFEW_START
        or
        current < CURFEW_END
    )


def get_curfew_start_datetime(
    now_local
):

    if (
        now_local.time()
        >= CURFEW_START
    ):

        curfew_date = (
            now_local.date()
        )

    else:

        curfew_date = (
            now_local.date()
            -
            timedelta(days=1)
        )


    return datetime.combine(
        curfew_date,
        CURFEW_START,
        tzinfo=LOCAL_TZ
    )


def parse_server_time(
    value
):

    if not value:

        return None


    dt = datetime.fromisoformat(
        value
    )


    # ai-check-system 保存的是 UTC
    # 但字符串本身没有 +00:00
    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )


    return dt.astimezone(
        LOCAL_TZ
    )


# =========================
# 主程序
# =========================

def main():

    now_local = datetime.now(
        LOCAL_TZ
    )


    print(
        "Robin Curfew Check:",
        now_local.isoformat()
    )


    # 不在 22:30 - 06:00
    # 什么都不做，直接退出
    if not is_curfew_time(
        now_local
    ):

        print(
            "Not curfew time."
        )

        return


    if not ORIGIN_API:

        print(
            "Missing ORIGIN_API"
        )

        return


    if not AUTH_TOKEN:

        print(
            "Missing AUTH_TOKEN"
        )

        return


    if not BARK_API_KEY:

        print(
            "Missing BARK_API_KEY"
        )

        return


    try:

        activity = (
            get_latest_activity()
        )

    except Exception as e:

        print(
            "Activity check failed:",
            e
        )

        return


    is_active = bool(
        activity.get(
            "is_active"
        )
    )

    active_app = (
        activity.get(
            "active_app"
        )
    )

    last_app = (
        activity.get(
            "last_app"
        )
    )

    last_activity_at = (
        parse_server_time(
            activity.get(
                "last_activity_at"
            )
        )
    )


    curfew_started_at = (
        get_curfew_start_datetime(
            now_local
        )
    )


    recent_cutoff = (
        now_local
        -
        timedelta(
            minutes=
                RECENT_ACTIVITY_MINUTES
        )
    )


    used_recently = False


    if last_activity_at:

        used_recently = (
            last_activity_at
            >= curfew_started_at
            and
            last_activity_at
            >= recent_cutoff
        )


    # 当前仍在用
    # 或最近 20 分钟内用过
    # 才发提醒
    if not (
        is_active
        or
        used_recently
    ):

        print(
            "No recent curfew activity."
        )

        return


    app_name = (
        active_app
        or
        last_app
        or
        "手机"
    )


    current_time_text = (
        now_local.strftime(
            "%H:%M"
        )
    )


    if is_active:

        content = (
            f"现在已经 {current_time_text} 了，"
            f"检测到你还在使用 {app_name}。"
            "22:30 后已经进入休息时间。"
        )

    else:

        content = (
            f"现在已经 {current_time_text} 了，"
            f"检测到你刚刚还使用了 {app_name}。"
            "22:30 后已经进入休息时间。"
        )


    try:

        status = send_bark(
            "Robin · 宵禁提醒",
            content
        )


        print(
            "Bark status:",
            status
        )


    except Exception as e:

        print(
            "Bark failed:",
            e
        )


if __name__ == "__main__":

    main()
