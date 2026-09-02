from pydantic import SecretStr

from app.config import Settings
from app.security import generate_pat, hash_pat


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
