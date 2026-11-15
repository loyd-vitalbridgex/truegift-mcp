# TrueGift Gift Finder MCP — production status

**Status: LIVE** (deployed and verified 2026-11-15). Nothing has been submitted
to any directory or registry yet — submissions are a separate step.

## Public endpoint

- **MCP (Streamable HTTP, stateless, POST JSON-RPC):**
  `https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp`
- **Health:** `https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp/health`
  → `{"status":"ok","service":"truegift-gift-finder","guides":91,"data_source":"live"}`
- **OpenAI apps challenge (subpath):** `.../gift-finder-mcp/.well-known/openai-apps-challenge`
  → currently 404 "challenge token not configured" (see "Blocked on Howard" below).

Verified 2026-11-15 with a real MCP client from outside the host
(`test_remote.py`): initialize (protocol 2025-03-26) + tools/list (3 tools,
all read-only annotations) + `find_gift_ideas` (10 picks, 5 guides),
`get_gift_guide` (7 picks), `list_gift_guides` (4 Hanukkah guides),
unknown-slug error path — **ALL REMOTE TESTS PASSED**.

## Hosting route

Supabase Edge Function (Deno) in the TrueGift project's own Supabase backend
(project ref `netpnmoapwzktvqjnrlo`, the same backend truegift.ai already
runs on, via Lovable Cloud). Free tier, no new account, no spend. The
function is public by design: `verify_jwt = false` in the project's
`supabase/config.toml`; it is read-only, takes no auth, and collects no user
data. The deployed file is byte-identical to
`edge-function/gift-finder-mcp/index.ts` in this repo (verified by read-back
after the Lovable build; Lovable commit `a652524b` "Added Gift Finder MCP
edge func" — the only project change; truegift.ai itself untouched, still 200).

A portable Python implementation of the same server (`server.py` +
`gift_data.py`, FastMCP) lives in this repo for local dev and as a fallback
host target (Dockerfile / Procfile / uvicorn ASGI included). The two
implementations mirror each other; the edge function is the production one.

## How deploys / updates happen

1. Edit `edge-function/gift-finder-mcp/index.ts` here (source of truth).
   Optionally run it locally first: `deno run --allow-net --allow-env
   edge-function/gift-finder-mcp/index.ts` (PORT env, default 8000) and
   `.venv/bin/python test_remote.py http://127.0.0.1:8000/`.
2. In the TrueGift Lovable project (id `463b39eb-edd8-4033-a82d-d9a708c77241`),
   replace `supabase/functions/gift-finder-mcp/index.ts` with the new content
   verbatim (Lovable edit), then publish/deploy the project.
3. Re-verify: `.venv/bin/python test_remote.py
   https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp`.
   (In this sandbox, remote fetches from Deno/Python may need the system CA /
   trimmed `no_proxy`; the test scripts already handle the Python side.)

Python server updates are just code changes in this repo (no live host runs
it today).

## How guide data refreshes

Live, self-refreshing — no snapshot dependency in production:

- **Catalog:** the function fetches `https://truegift.ai/sitemap.xml`,
  builds the guide list from every `/gifts/*` and `/guides/*` URL, and
  derives occasion/recipient/budget tags from each slug. Cached in memory,
  6h TTL, refetched on first request after expiry.
- **Picks/summaries:** fetched lazily per guide from the guide page's static
  JSON-LD (`<script data-gift-static>` @graph: Article headline/description +
  ItemList picks), cached per guide with the same TTL. `find_gift_ideas`
  fetches details for its top-8 ranked guides in parallel.
- **Curated overlay:** why-it-fits text and budget ceilings for flagship
  picks are merged in from the snapshot in this repo
  (`data/guides.json`, served via raw.githubusercontent.com) when a live
  pick's name matches.
- **Fallback:** if truegift.ai is unreachable, the function serves the repo
  snapshot so it never starts empty; `/health` reports
  `data_source: "snapshot"` in that case (`"live"` normally). New guides
  published on truegift.ai appear automatically within one TTL (≤6h) of
  their sitemap entry.

## Environment variables

| Var | Where | Purpose |
|---|---|---|
| `OPENAI_APPS_CHALLENGE_TOKEN` | Supabase function secret (edge) / env (Python) | Token served at the `/.well-known/openai-apps-challenge` route for ChatGPT domain verification. **Not set yet** — set at ChatGPT submission time with the token OpenAI issues. Route returns 404 until then. |
| `TRUGIFT_DATA_TTL_SECONDS` | Python server only | Guide-data cache TTL (default 21600). |
| `TRUGIFT_FETCH_TIMEOUT_SECONDS` | Python server only | Per-fetch timeout (default 10). |
| `HOST` / `PORT` | Python server only | HTTP bind (defaults 127.0.0.1 / 8377; edge function uses PORT, default 8000). |

No credentials are used by either implementation; none are in the repo.

## Code & repo

- GitHub (public, no secrets): https://github.com/loyd-vitalbridgex/truegift-mcp
- Local tests: `.venv/bin/python test_data.py` (data layer, offline),
  `test_client.py` (stdio MCP), `test_http.py` (local HTTP + challenge +
  health), `test_remote.py <url>` (any deployed endpoint).

## Blocked on Howard (exact steps)

Nothing blocks the live endpoint. Two submission-time items need Howard —
both belong to the separate submission step, not to this deployment:

1. **ChatGPT domain verification token.** When the ChatGPT plugin submission
   is started (platform.openai.com/plugins, under Howard's verified OpenAI
   developer identity), OpenAI issues a challenge token. It must be set as
   the `OPENAI_APPS_CHALLENGE_TOKEN` secret on the Supabase function
   (Supabase dashboard → project `netpnmoapwzktvqjnrlo` → Edge Functions →
   Secrets — a dashboard action under Howard's Supabase/Lovable identity),
   OR the token file can be hosted at `https://truegift.ai/.well-known/
   openai-apps-challenge` as a static file in the Lovable app instead.
   Note: OpenAI verifies the token on the MCP server's host; because the MCP
   host is `*.supabase.co`, the submission flow may require pointing the
   plugin at a truegift.ai URL — resolving that choice is part of the
   submission step. The route is implemented and tested on both
   implementations either way.
2. **Registry namespace verification** (`ai.truegift/gift-finder` in
   `server.json`, still a draft): publishing to the official MCP Registry
   needs DNS or HTTP verification on `truegift.ai` itself (a DNS TXT record
   at the domain registrar, or a verification file added to the Lovable
   app). DNS changes are Howard's call.

## Not done (by design — separate steps)

- No submission to ChatGPT, Claude Connectors Directory, or any registry.
- No Google Connected Apps waitlist join.
- PeptideX / LotFlex / Protect65 MCP servers remain spec-only, per plan.
