"""Inspect a running MCP server without calling application data tools."""

import argparse
import asyncio
import json
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def inspect(url: str) -> None:
    async with httpx.AsyncClient(
        headers={"Accept": "application/json, text/event-stream"},
        timeout=httpx.Timeout(30, read=60),
    ) as client, streamable_http_client(url, http_client=client) as streams:
        read_stream, write_stream, _session_id = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()

    selected: dict[str, Any] = {}
    for tool in tools.tools:
        if tool.name in {"create_receipt_draft_from_file", "open_expense_tracker"}:
            file_schema = tool.inputSchema.get("$defs", {}).get("OpenAIFileInput", {})
            selected[tool.name] = {
                "annotations": tool.annotations.model_dump() if tool.annotations else None,
                "meta": tool.meta,
                "file_properties": sorted(file_schema.get("properties", {})),
                "file_required": file_schema.get("required", []),
            }
    print(
        json.dumps(
            {
                "tool_count": len(tools.tools),
                "tool_names": sorted(tool.name for tool in tools.tools),
                "resource_count": len(resources.resources),
                "resources": sorted(str(resource.uri) for resource in resources.resources),
                "selected": selected,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8000/mcp")
    args = parser.parse_args()
    asyncio.run(inspect(args.url))


if __name__ == "__main__":
    main()
