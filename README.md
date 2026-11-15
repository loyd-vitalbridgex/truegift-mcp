# TrueGift Gift Finder — MCP server prototype

Built 2026-11-13. A working, read-only MCP server over TrueGift's real, already-published
gift-guide data. It is the concrete first build for the AI-native distribution plan
(`../../distribution-ai-native-plan-2026-11-13.md`): one server, submittable in shape to
ChatGPT (plugin + MCP connection), Claude (Connectors Directory), Perplexity/Grok/Gemini
(custom connector by URL), and the MCP registries (agent-to-agent discovery).

## Tools

| Tool | What it does |
|---|---|
| `find_gift_ideas` | Given recipient / occasion / interests / budget, returns concrete picks (name + why it fits) and the best-matching guides |
| `list_gift_guides` | Browses the guide catalog, filterable by occasion and recipient |
| `get_gift_guide` | One guide's summary + full pick list |

All tools: `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false`, no auth,
no user data collected, outputs carry no internal IDs — the exact shape OpenAI's and
Anthropic's reviewers check for.

## Data

`data/guides.json` — snapshot dated 2026-11-13: 91 guides from the live
https://truegift.ai/sitemap.xml, with full pick-level data (names + why-it-fits) for the
three flagship holiday guides (christmas-gift-ideas: 9 picks, christmas-gifts-for-her: 7,
hanukkah-gifts-for-kids: 8). Rebuild with `.venv/bin/python build_data.py`.

## Run / test

```bash
.venv/bin/python server.py            # stdio
.venv/bin/python server.py --http     # Streamable HTTP at http://127.0.0.1:8377/mcp
.venv/bin/python test_client.py       # stdio client smoke test — ALL TESTS PASSED 2026-11-13
```

Verified 2026-11-13: stdio initialize + tools/list + all three tool calls with structured
output; Streamable HTTP initialize + session + tools/list over raw JSON-RPC.

## What production needs (in order)

1. **Hosting**: a public HTTPS endpoint on a domain we control. Cheapest fit with the
   existing stack: a `/mcp` route in the Lovable app deployment, or this same FastMCP
   server on any small host. The URL cannot change through OpenAI's update flow — pick
   the permanent one (`https://truegift.ai/mcp` is the intended target in `server.json`).
2. **Live data**: replace the snapshot with the Lovable app's stored guide graphs
   (the app's JSON-LD @graph store) so picks, prices context and new guides stay current.
3. **Domain verification**: serve OpenAI's challenge token at
   `https://truegift.ai/.well-known/openai-apps-challenge` when submitting to ChatGPT.
4. **Listing assets**: privacy policy + terms already live at truegift.ai/privacy and
   /terms; needs a support page, icon, 5 positive + 3 negative test cases, a video
   walkthrough, and a verified OpenAI developer identity (org verification).
5. **Submit**: ChatGPT plugin ZIP via platform.openai.com/plugins → Claude connector via
   claude.ai/directory/manage → official MCP Registry via `mcp-publisher` (cascades to
   Glama/Smithery/PulseMCP). Nothing has been submitted — see the plan file.
