from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.security import candidate_pat_hashes, generate_pat, hash_pat


def test_hash_pat_is_deterministic_and_peppered() -> None:
    settings = Settings(pat_pepper=SecretStr("pepper-one"))
    other_settings = Settings(pat_pepper=SecretStr("pepper-two"))

    first = hash_pat("det_example", settings)
    second = hash_pat("det_example", settings)
    third = hash_pat("det_example", other_settings)

    assert first == second
    assert first != third
    assert first != "det_example"


def test_generate_pat_uses_project_prefix() -> None:
    token = generate_pat()

    assert token.startswith("det_")
    assert len(token) > 20


def test_previous_key_retirement_is_checked_at_use_time() -> None:
    now = datetime(2026, 10, 31, tzinfo=UTC)
    settings = Settings(
        pat_pepper=SecretStr("new-pepper"),
        pat_pepper_version="v2",
        pat_previous_pepper=SecretStr("old-pepper"),
        pat_previous_pepper_version="v1",
        pat_previous_pepper_retire_at=now + timedelta(hours=1),
    )
    before = candidate_pat_hashes("det_example", settings, now)
    at_deadline = candidate_pat_hashes("det_example", settings, now + timedelta(hours=1))
    after = candidate_pat_hashes("det_example", settings, now + timedelta(hours=2))
    assert len(before) == 2
    assert before[0] == hash_pat("det_example", settings)
    assert len(at_deadline) == len(after) == 1


def test_incomplete_rotation_config_does_not_expose_pepper() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(pat_previous_pepper=SecretStr("sentinel-pepper"))
    assert "sentinel-pepper" not in str(error.value)
