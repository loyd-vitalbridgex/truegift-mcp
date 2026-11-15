#!/usr/bin/env python3
"""HTTP tests: boot server.py --http on a local port, then verify
  - GET /health
  - GET /.well-known/openai-apps-challenge (token from env)
  - a real MCP streamable-HTTP session: initialize + tools/list + tool calls
Run: .venv/bin/python test_http.py   (uses live truegift.ai data; the store
falls back to the bundled snapshot if the site is unreachable)"""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

# This sandbox exports a no_proxy list httpx cannot parse (bracketed IPv6);
# trim it before any httpx-based client is constructed. Harmless elsewhere.
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

HERE = Path(__file__).parent
PORT = 8391
BASE = f"http://127.0.0.1:{PORT}"


async def mcp_checks() -> None:
    async with streamablehttp_client(f"{BASE}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert names == ["find_gift_ideas", "list_gift_guides", "get_gift_guide"], names
            for t in tools.tools:
                assert t.annotations and t.annotations.readOnlyHint, t.name
            print("http tools/list + annotations OK:", names)

            r = await session.call_tool("find_gift_ideas",
                                        {"recipient": "mom", "occasion": "christmas",
                                         "max_budget_usd": 50})
            data = r.structuredContent
            assert data["guides"], "expected matching guides"
            print(f"http find_gift_ideas: {len(data['picks'])} picks, {len(data['guides'])} guides")

            r = await session.call_tool("get_gift_guide", {"slug": "christmas-gifts-for-her"})
            assert len(r.structuredContent["picks"]) == 7
            print("http get_gift_guide: 7 picks OK")


def main() -> int:
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(PORT),
           "OPENAI_APPS_CHALLENGE_TOKEN": "test-token-123"}
    log = open(HERE / "tests" / "http-server.log", "w")
    proc = subprocess.Popen([str(HERE / ".venv" / "bin" / "python"), str(HERE / "server.py"), "--http"],
                            env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 30
        while True:
            try:
                r = httpx.get(f"{BASE}/health", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            if time.time() > deadline:
                raise RuntimeError("server did not come up")
            time.sleep(0.3)
        body = r.json()
        assert body["status"] == "ok" and body["guides"] >= 91, body
        print("GET /health OK:", body)

        r = httpx.get(f"{BASE}/.well-known/openai-apps-challenge", timeout=5)
        assert r.status_code == 200 and r.text == "test-token-123", (r.status_code, r.text)
        print("GET /.well-known/openai-apps-challenge OK")

        asyncio.run(mcp_checks())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    print("ALL HTTP TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
