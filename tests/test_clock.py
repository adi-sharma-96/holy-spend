from collections.abc import Callable
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.clock import local_today
from app.config import Settings


def _mock_now(fixed_utc: datetime) -> Callable[[ZoneInfo], datetime]:
    def fake_now(tz: ZoneInfo) -> datetime:
        return fixed_utc.astimezone(tz)

    return fake_now


def test_local_today_resolves_behind_utc_for_a_western_timezone() -> None:
    # 2:00 AM UTC on Aug 1 is still 10:00 PM Jul 31 in US Eastern time.
    fixed_utc = datetime(2026, 8, 1, 2, 0, tzinfo=ZoneInfo("UTC"))
    settings = Settings(local_timezone="America/New_York")

    with patch("app.clock.datetime") as mock_datetime:
        mock_datetime.now.side_effect = _mock_now(fixed_utc)
        result = local_today(settings)

    assert result == date(2026, 7, 31)


def test_local_today_can_resolve_ahead_of_utc_for_an_eastern_timezone() -> None:
    # 11:00 PM UTC on Jul 31 is already Aug 1 in a UTC+14 zone.
    fixed_utc = datetime(2026, 7, 31, 23, 0, tzinfo=ZoneInfo("UTC"))
    settings = Settings(local_timezone="Pacific/Kiritimati")

    with patch("app.clock.datetime") as mock_datetime:
        mock_datetime.now.side_effect = _mock_now(fixed_utc)
        result = local_today(settings)

    assert result == date(2026, 8, 1)


def test_invalid_local_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(local_timezone="Not/AZone")
