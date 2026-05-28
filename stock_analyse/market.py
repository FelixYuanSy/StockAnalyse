from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .models import MarketPhase


CHINA_TZ = ZoneInfo("Asia/Shanghai")


def china_market_phase(now: datetime | None = None) -> MarketPhase:
    current = now.astimezone(CHINA_TZ) if now else datetime.now(CHINA_TZ)
    if current.weekday() >= 5:
        return "休市"

    current_time = current.time()
    morning_open = time(9, 30)
    morning_close = time(11, 30)
    afternoon_open = time(13, 0)
    afternoon_close = time(15, 0)

    if morning_open <= current_time <= morning_close:
        return "盘中"
    if afternoon_open <= current_time <= afternoon_close:
        return "盘中"
    if current_time > afternoon_close:
        return "盘后"
    return "休市"
