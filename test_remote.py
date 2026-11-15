#!/usr/bin/env python3
"""Remote MCP test: run a real MCP client session against a deployed
Streamable HTTP endpoint (initialize + tools/list + real tool calls).

Usage: .venv/bin/python test_remote.py <MCP_ENDPOINT_URL>
Example: .venv/bin/python test_remote.py https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp
"""
import asyncio
import json
import os
import sys

# This sandbox exports a no_proxy list httpx cannot parse (bracketed IPv6);
# trim it before any httpx-based client is constructed. Harmless elsewhere.
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402


def payload(result) -> dict:
    if result.structuredContent:
        return result.structuredContent
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool result had neither structuredContent nor JSON text content")


async def main(url: str) -> int:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"initialize OK: server={init.serverInfo.name} v{init.serverInfo.version}, "
                  f"protocol={init.protocolVersion}")
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert names == ["find_gift_ideas", "list_gift_guides", "get_gift_guide"], names
            for t in tools.tools:
                assert t.annotations and t.annotations.readOnlyHint \
                    and not t.annotations.destructiveHint, (t.name, t.annotations)
            print("tools/list OK:", names, "(all read-only, non-destructive)")

            r = await session.call_tool("find_gift_ideas",
                                        {"recipient": "mom", "occasion": "christmas",
                                         "max_budget_usd": 50})
            assert not r.isError, r
            data = payload(r)
            assert data["guides"] and data["picks"], data
            print(f"find_gift_ideas(mom/christmas/$50): {len(data['picks'])} picks, "
                  f"{len(data['guides'])} guides; first pick: {data['picks'][0]['name']}")

            r = await session.call_tool("get_gift_guide", {"slug": "christmas-gifts-for-her"})
            data = payload(r)
            assert len(data["picks"]) == 7, data
            print(f"get_gift_guide(christmas-gifts-for-her): {len(data['picks'])} picks")

            r = await session.call_tool("list_gift_guides", {"occasion": "hanukkah"})
            data = payload(r)
            assert data["count"] >= 4, data
            print(f"list_gift_guides(hanukkah): {data['count']} guides")

            r = await session.call_tool("get_gift_guide", {"slug": "no-such-guide"})
            data = payload(r)
            assert data.get("error"), data
            print("get_gift_guide(unknown slug): graceful error OK")
    print("ALL REMOTE TESTS PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
