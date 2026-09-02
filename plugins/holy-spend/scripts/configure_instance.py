"""Create an ignored, instance-local plugin bundle with a ChatGPT connection ID."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

APP_ID_PATTERN = re.compile(r"^(?:asdk_app|plugin_asdk_app)_[A-Za-z0-9_-]+$")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local Holy Spend plugin bundle without modifying the publishable source."
    )
    parser.add_argument(
        "--app-id",
        required=True,
        help="Technical ID of the registered ChatGPT MCP connection (asdk_app_* or plugin_asdk_app_*).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/plugin/holy-spend"),
        help="Generated plugin directory. Defaults under the repository's ignored build/ folder.",
    )
    args = parser.parse_args()

    if not APP_ID_PATTERN.fullmatch(args.app_id):
        parser.error("--app-id must be an asdk_app_* or plugin_asdk_app_* technical connection ID")

    source = Path(__file__).resolve().parent.parent
    repository_root = source.parent.parent
    allowed_output_root = (repository_root / "build" / "plugin").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(allowed_output_root) or output == allowed_output_root:
        parser.error(f"--output must be a child of {allowed_output_root}")

    # OneDrive may mark generated directories as reparse points that deny
    # directory deletion while still allowing file replacement. Merge the
    # small, fixed plugin source tree in place so regeneration remains
    # repeatable in that environment.
    shutil.copytree(source, output, dirs_exist_ok=True)

    app_manifest = {
        "apps": {
            "holy_spend": {
                "id": args.app_id,
                "category": "Personal Finance",
            }
        }
    }
    (output / ".app.json").write_text(
        json.dumps(app_manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_path = output / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["apps"] = "./.app.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
