"""Full npm audit with one owner-approved, expiring build-only exception."""

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ADVISORY = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
EXPIRES = datetime(2026, 12, 1, tzinfo=UTC)
# Exact reviewed copies. Any new version/path requires reassessment.
COPIES = {
    "fdir": "6.5.0",
    "picomatch": "4.0.7",
    "tinyglobby": "0.2.17",
    "vite": "7.3.7",
    "vite-plugin-singlefile": "2.3.4",
    "vitest": "5.0.5",
}


def check_report(report: dict[str, Any], lock: dict[str, Any], now: datetime) -> list[str]:
    if report.get("auditReportVersion") != 2 or report.get("error"):
        raise ValueError("Unsupported or failed audit report")
    vulnerabilities = report["vulnerabilities"]
    if not isinstance(vulnerabilities, dict):
        raise ValueError("Malformed vulnerabilities")
    if report["metadata"]["vulnerabilities"]["total"] != len(vulnerabilities):
        raise ValueError("Inconsistent vulnerability count")
    if not vulnerabilities:
        return []
    if now >= EXPIRES:
        raise ValueError("Picomatch exception expired on 2026-12-01 UTC")

    def review(name: str, visiting: frozenset[str]) -> None:
        if name in visiting or name not in COPIES:
            raise ValueError(f"Unreviewed or cyclic advisory dependency: {name}")
        entry = vulnerabilities[name]
        expected_path = f"node_modules/{name}"
        if entry["name"] != name or entry["nodes"] != [expected_path]:
            raise ValueError(f"Unreviewed package copies: {name}")
        installed = lock["packages"][expected_path]
        if installed.get("dev") is not True or installed["version"] != COPIES[name]:
            raise ValueError(f"Exception requires exact development-only version: {name}")
        if not entry["via"]:
            raise ValueError(f"Missing advisory evidence: {name}")
        for via in entry["via"]:
            if isinstance(via, str):
                review(via, visiting | {name})
            elif not (
                name == "picomatch" and via.get("url") == ADVISORY
                and via.get("name") == "picomatch" and via.get("dependency") == "picomatch"
                and via.get("severity") == "high" and via.get("range") == "<=4.0.7"
            ):
                raise ValueError(f"Unexcepted advisory: {name}")

    for name in vulnerabilities:
        review(name, frozenset())
    return sorted(vulnerabilities)


def main() -> int:
    try:
        npm = shutil.which("npm")
        if not npm:
            raise ValueError("npm unavailable")
        result = subprocess.run(
            [npm, "audit", "--json"], cwd=ROOT / "widget", capture_output=True,
            text=True, encoding="utf-8", timeout=120, check=False,
        )
        # Preserve the complete report, including accepted findings, in CI logs.
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode not in (0, 1):
            raise ValueError(f"npm audit failed with exit {result.returncode}")
        report = json.loads(result.stdout)
        lock = json.loads((ROOT / "widget/package-lock.json").read_text(encoding="utf-8"))
        accepted = check_report(report, lock, datetime.now(UTC))
        if not accepted and result.returncode != 0:
            raise ValueError("npm failed without a supported advisory report")
        if accepted:
            print(f"WARNING: owner-approved BUILD-ONLY exception for {ADVISORY}")
            print(f"Expires {EXPIRES.isoformat()}; affected packages: {', '.join(accepted)}")
            print("The vulnerability remains unresolved. This is not a clean audit.")
        else:
            print("Full dependency audit clean; remove the unused exception.")
        return 0
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"Dependency audit blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
