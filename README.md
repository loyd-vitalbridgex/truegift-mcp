# TrueGift Gift Finder — MCP server

A read-only MCP server over TrueGift's real, published gift-guide data — the
first build of the AI-native distribution plan
(`../../distribution-ai-native-plan-2026-11-13.md`): one server, distributed
to ChatGPT (plugin + MCP connection), Claude (Connectors Directory),
Perplexity/Grok/Gemini (custom connector by URL), and the MCP registries
(agent-to-agent discovery).

**LIVE since 2026-11-15** — see `PRODUCTION-STATUS.md` for the endpoint,
hosting, and update flow. Nothing has been submitted to any directory or
registry yet.

- **Production endpoint:** `https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp`
  (Supabase Edge Function; source: `edge-function/gift-finder-mcp/index.ts`)
- **This repo:** https://github.com/loyd-vitalbridgex/truegift-mcp

## Tools

| Tool | What it does |
|---|---|
| `find_gift_ideas` | Given recipient / occasion / interests / budget, returns concrete picks (name + why it fits) and the best-matching guides |
| `list_gift_guides` | Browses the guide catalog, filterable by occasion and recipient |
| `get_gift_guide` | One guide's summary + full pick list |

All tools: `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false`,
no auth, no user data collected, outputs carry no internal IDs — the exact
shape OpenAI's and Anthropic's reviewers check for.

## Data — live, not a snapshot

The catalog comes from https://truegift.ai/sitemap.xml (every `/gifts/*` and
`/guides/*` URL; tags derived from the slug). Each guide's picks and summary
come from the guide page's static JSON-LD (`<script data-gift-static>`
@graph), fetched lazily and cached with a 6h TTL. Curated why-it-fits text
for flagship picks is merged from `data/guides.json`, which is also the
offline fallback if the site is unreachable. New guides appear automatically
once they are in the sitemap.

## Implementations

- `edge-function/gift-finder-mcp/index.ts` — **production**. Single-file
  Deno, zero imports, stateless Streamable HTTP JSON-RPC. Deployed in the
  TrueGift project's Supabase backend via Lovable (see PRODUCTION-STATUS.md).
- `server.py` + `gift_data.py` — the same server in Python (FastMCP), for
  local development and as a portable fallback host (stdio, `--http`, or
  `uvicorn server:app`; Dockerfile + Procfile included).

## Run / test (Python)

```bash
.venv/bin/python server.py            # stdio
.venv/bin/python server.py --http     # Streamable HTTP at http://127.0.0.1:8377/mcp
.venv/bin/python test_data.py         # data-layer tests (offline, fixtures)
.venv/bin/python test_client.py       # stdio client smoke test
.venv/bin/python test_http.py         # local HTTP: /health, challenge route, MCP session
.venv/bin/python test_remote.py https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp
```

All suites passed 2026-11-15, including the remote run against the
production URL.

## Extra routes (both implementations)

- `GET /health` → `{"status":"ok","guides":91,"data_source":"live"}`
- `GET /.well-known/openai-apps-challenge` → the value of the
  `OPENAI_APPS_CHALLENGE_TOKEN` env var / function secret (404 when unset;
  the token is issued by OpenAI at ChatGPT submission time).

## Registry draft

`server.json` is the official-MCP-Registry draft pointing at the production
URL. **Not published** — publishing (with `ai.truegift` namespace
verification on truegift.ai) is a separate, later step, as are the ChatGPT
and Claude submissions.
