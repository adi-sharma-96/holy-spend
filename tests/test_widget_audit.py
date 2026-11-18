from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from scripts.widget_audit import ADVISORY, COPIES, check_report

NOW = datetime(2026, 11, 17, tzinfo=UTC)


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    report = {
        "auditReportVersion": 2,
        "metadata": {"vulnerabilities": {"total": 2}},
        "vulnerabilities": {
            "picomatch": {"name": "picomatch", "nodes": ["node_modules/picomatch"], "via": [{
                "url": ADVISORY, "name": "picomatch", "dependency": "picomatch",
                "severity": "high", "range": "<=4.0.7",
            }]},
            "vite": {"name": "vite", "nodes": ["node_modules/vite"], "via": ["picomatch"]},
        },
    }
    lock = {"packages": {f"node_modules/{key}": {"version": version, "dev": True}
                         for key, version in COPIES.items()}}
    return report, lock


def test_accepts_only_reviewed_chain_and_keeps_expiry() -> None:
    report, lock = fixture()
    assert check_report(report, lock, NOW) == ["picomatch", "vite"]
    with pytest.raises(ValueError, match="expired"):
        check_report(report, lock, datetime(2026, 12, 1, tzinfo=UTC))


@pytest.mark.parametrize("change", ["advisory", "production", "version", "copy", "cycle", "missing", "error"])
def test_fails_closed(change: str) -> None:
    report, lock = fixture()
    if change == "advisory":
        extra = deepcopy(report["vulnerabilities"]["picomatch"]["via"][0])
        extra["url"] = "https://github.com/advisories/GHSA-another"
        report["vulnerabilities"]["picomatch"]["via"].append(extra)
    elif change == "production":
        lock["packages"]["node_modules/picomatch"].pop("dev")
    elif change == "version":
        lock["packages"]["node_modules/picomatch"]["version"] = "4.0.8"
    elif change == "copy":
        report["vulnerabilities"]["picomatch"]["nodes"].append("node_modules/other/node_modules/picomatch")
    elif change == "cycle":
        report["vulnerabilities"]["picomatch"]["via"] = ["vite"]
    elif change == "missing":
        del report["vulnerabilities"]["picomatch"]
    else:
        report["error"] = {"message": "Registry unavailable"}
    with pytest.raises((ValueError, KeyError)):
        check_report(report, lock, NOW)


def test_clean_audit_passes_after_expiry() -> None:
    report, lock = fixture()
    report["vulnerabilities"] = {}
    report["metadata"]["vulnerabilities"]["total"] = 0
    assert check_report(report, lock, datetime(2026, 12, 2, tzinfo=UTC)) == []
