#!/usr/bin/env python3
"""Smoke test: connect to server.py over stdio as a real MCP client,
list tools, and call find_gift_ideas + get_gift_guide. Run: .venv/bin/python test_client.py"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent


async def main() -> int:
    params = StdioServerParameters(command=str(HERE / ".venv" / "bin" / "python"),
                                   args=[str(HERE / "server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            assert names == ["find_gift_ideas", "list_gift_guides", "get_gift_guide"], names

            for t in tools.tools:
                a = t.annotations
                assert a and a.readOnlyHint and not a.destructiveHint, (t.name, a)
            print("annotations: all read-only, non-destructive — OK")

            r = await session.call_tool("find_gift_ideas",
                                        {"recipient": "mom", "occasion": "christmas",
                                         "max_budget_usd": 50})
            data = r.structuredContent
            print(f"find_gift_ideas(mom/christmas/$50): {len(data['picks'])} picks, "
                  f"{len(data['guides'])} guides; first pick: {data['picks'][0]['name'] if data['picks'] else None}")
            assert data["guides"], "expected matching guides"

            r = await session.call_tool("get_gift_guide", {"slug": "christmas-gifts-for-her"})
            data = r.structuredContent
            print(f"get_gift_guide(christmas-gifts-for-her): {len(data['picks'])} picks")
            assert len(data["picks"]) == 7

            r = await session.call_tool("list_gift_guides", {"occasion": "hanukkah"})
            data = r.structuredContent
            print(f"list_gift_guides(hanukkah): {data['count']} guides")
            assert data["count"] >= 4

            r = await session.call_tool("list_gift_guides", {"recipient": "coworker", "occasion": "secret-santa"})
            data = r.structuredContent
            print(f"list_gift_guides(coworker + secret-santa): {data['count']} guides")
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
