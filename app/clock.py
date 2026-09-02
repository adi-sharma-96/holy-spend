from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import Settings


def local_today(settings: Settings) -> date:
    """The owner's current calendar day, not the server process's system-clock day."""
    return datetime.now(ZoneInfo(settings.local_timezone)).date()
