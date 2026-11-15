#!/usr/bin/env python3
"""TrueGift Gift Finder — MCP server (production).

One read-only MCP server submittable, unchanged in shape, to:
  - ChatGPT (as a plugin with an MCP connection, platform.openai.com/plugins)
  - Claude (Connectors Directory, claude.ai/directory/manage)
  - Perplexity / Grok / Gemini (custom MCP connector by URL)
  - the official MCP Registry + Glama/Smithery (agent-to-agent discovery)

Tools (all read-only, no auth, no user data collected):
  - find_gift_ideas   : match gift picks + guides to recipient/occasion/interests/budget
  - list_gift_guides  : browse the TrueGift guide catalog by occasion/recipient
  - get_gift_guide    : one guide's picks and summary

Data is LIVE: the catalog comes from truegift.ai's sitemap and each guide's
picks from the guide page's static JSON-LD, cached with a TTL (see
gift_data.py). The bundled snapshot is only an offline fallback.

Run:
  .venv/bin/python server.py            # stdio (local dev / MCP Inspector)
  .venv/bin/python server.py --http     # Streamable HTTP on $HOST:$PORT (default 127.0.0.1:8377), path /mcp
  uvicorn server:app --host 0.0.0.0 --port $PORT   # ASGI (PaaS)

Env:
  HOST, PORT                     HTTP bind (default 127.0.0.1 / 8377)
  OPENAI_APPS_CHALLENGE_TOKEN    served at /.well-known/openai-apps-challenge
                                 (ChatGPT domain verification; 404 when unset)
  TRUGIFT_DATA_TTL_SECONDS       guide-data cache TTL (default 21600 = 6h)
"""
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from gift_data import GuideStore

STORE = GuideStore()

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            openWorldHint=False, idempotentHint=True)

mcp = FastMCP("TrueGift Gift Finder",
              instructions="Gift recommendations from TrueGift.ai's published gift guides. "
                           "Use find_gift_ideas when someone describes a person or occasion; "
                           "every pick links back to its TrueGift guide.")


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "truegift-gift-finder",
                         "guides": len(STORE.catalog()), "data_source": STORE.source})


@mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"])
async def openai_apps_challenge(_: Request) -> PlainTextResponse:
    token = os.environ.get("OPENAI_APPS_CHALLENGE_TOKEN", "").strip()
    if not token:
        return PlainTextResponse("challenge token not configured", status_code=404)
    return PlainTextResponse(token)


class Pick(BaseModel):
    name: str
    why_it_fits: Optional[str] = None
    budget_ceiling_usd: Optional[int] = None
    guide_title: Optional[str] = None
    guide_url: Optional[str] = None


class GuideBrief(BaseModel):
    title: str
    url: str
    slug: str
    occasions: list[str]
    recipients: list[str]
    budget_ceiling_usd: Optional[int] = None
    pick_count: int
    summary: Optional[str] = None


class FindGiftIdeasResult(BaseModel):
    picks: list[Pick]
    guides: list[GuideBrief]
    note: str


class ListGuidesResult(BaseModel):
    count: int
    guides: list[GuideBrief]


class GuideDetail(GuideBrief):
    picks: list[Pick]
    picks_note: Optional[str] = None
    error: Optional[str] = None


def _guide_brief(g: dict) -> GuideBrief:
    return GuideBrief(title=g["title"], url=g["url"], slug=g["slug"],
                      occasions=g["occasions"], recipients=g["recipients"],
                      budget_ceiling_usd=g["budget_ceiling_usd"],
                      pick_count=len(g.get("picks") or []),
                      summary=g.get("summary"))


@mcp.tool(annotations=READ_ONLY, title="Find gift ideas for a person or occasion")
def find_gift_ideas(recipient: str = "", occasion: str = "",
                    interests: str = "", max_budget_usd: int = 0) -> FindGiftIdeasResult:
    """Find gift ideas for a specific person and occasion.

    Searches TrueGift's published gift guides and returns concrete product
    picks (with the reason each fits) plus the best-matching guides.
    Examples: recipient="mom", occasion="christmas", max_budget_usd=50;
    recipient="coworker", occasion="secret-santa", interests="coffee".

    Args:
        recipient: Who the gift is for (mom, dad, coworker, teen, wife...).
        occasion: christmas, hanukkah, birthday, anniversary, secret-santa...
        interests: Free-text interests (coffee, cooking, gardening, books...).
        max_budget_usd: Budget ceiling in USD; 0 means no limit.
    """
    rec = recipient.strip().lower()
    occ = occasion.strip().lower().replace(" ", "-")
    words = [w for w in interests.lower().replace(",", " ").split() if len(w) > 2]

    def guide_score(g: dict) -> int:
        s = 0
        if rec and rec in g["recipients"]:
            s += 3
        if occ and occ in g["occasions"]:
            s += 3
        if words and any(w in g["slug"] for w in words):
            s += 2
        if max_budget_usd and g["budget_ceiling_usd"] is not None:
            s += 1 if g["budget_ceiling_usd"] <= max_budget_usd else -4
        return s

    guides = STORE.catalog()
    ranked = sorted((g for g in guides if guide_score(g) > 0),
                    key=guide_score, reverse=True)
    STORE.ensure_details_many(ranked[:8])

    picks = []
    for g in ranked:
        for p in g.get("picks") or []:
            if max_budget_usd and p.get("budget_ceiling_usd") is not None \
                    and p["budget_ceiling_usd"] > max_budget_usd:
                continue
            picks.append(Pick(name=p["name"], why_it_fits=p.get("why"),
                              budget_ceiling_usd=p.get("budget_ceiling_usd"),
                              guide_title=g["title"], guide_url=g["url"]))
        if len(picks) >= 10:
            break

    return FindGiftIdeasResult(
        picks=picks[:10],
        guides=[_guide_brief(g) for g in ranked[:5]],
        note="Prices change often; each guide links to today's price. "
             "TrueGift may earn a commission on purchases, at no extra cost to the buyer.")


@mcp.tool(annotations=READ_ONLY, title="List TrueGift gift guides")
def list_gift_guides(occasion: str = "", recipient: str = "") -> ListGuidesResult:
    """List TrueGift gift guides, optionally filtered by occasion or recipient.

    Args:
        occasion: christmas, hanukkah, birthday, anniversary, secret-santa...
        recipient: mom, dad, grandma, coworker, teacher, teen...
    """
    occ = occasion.strip().lower().replace(" ", "-")
    rec = recipient.strip().lower()
    out = [g for g in STORE.catalog()
           if (not occ or occ in g["occasions"]) and (not rec or rec in g["recipients"])]
    return ListGuidesResult(count=len(out),
                             guides=[_guide_brief(g) for g in out[:25]])


@mcp.tool(annotations=READ_ONLY, title="Get one TrueGift gift guide with its picks")
def get_gift_guide(slug: str) -> GuideDetail:
    """Get one TrueGift gift guide by slug, including its gift picks when available.

    Args:
        slug: The guide slug, e.g. "christmas-gifts-for-her" (from list_gift_guides).
    """
    g = STORE.get(slug.strip().lower())
    if not g:
        return GuideDetail(title="", url="", slug=slug, occasions=[], recipients=[],
                           pick_count=0, picks=[],
                           error=f"No guide with slug '{slug}'. Use list_gift_guides to browse.")
    STORE.ensure_details(g)
    picks = [Pick(name=p["name"], why_it_fits=p.get("why"),
                  budget_ceiling_usd=p.get("budget_ceiling_usd")) for p in g.get("picks") or []]
    return GuideDetail(**_guide_brief(g).model_dump(), picks=picks,
                       picks_note=None if picks else
                       "Pick-level data for this guide is on the guide page itself.")


# ASGI app for PaaS hosting (uvicorn server:app). Importing this module does
# not start anything; stdio remains the default when run as a script.
app = mcp.streamable_http_app()

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = os.environ.get("HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("PORT", "8377"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
