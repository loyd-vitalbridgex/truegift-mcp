// TrueGift Gift Finder — MCP server (Supabase Edge Function, Deno).
//
// Deployed copy lives in the TrueGift Lovable project at
// supabase/functions/gift-finder-mcp/index.ts (verify_jwt = false).
// Public endpoint: https://netpnmoapwzktvqjnrlo.supabase.co/functions/v1/gift-finder-mcp
//
// Stateless Streamable HTTP MCP (JSON responses), read-only tools only:
//   find_gift_ideas, list_gift_guides, get_gift_guide
// Data is LIVE: catalog from truegift.ai/sitemap.xml, per-guide picks from
// each guide page's static JSON-LD (@graph Article + ItemList), cached in
// memory with a 6h TTL. The GitHub-hosted snapshot is the offline fallback
// and the source of curated why-it-fits/budget overlays for flagship picks.
// No auth, no user data, no secrets. OPENAI_APPS_CHALLENGE_TOKEN (function
// secret) is served at the /.well-known/openai-apps-challenge subpath.

const SITE = "https://truegift.ai";
const SNAPSHOT_URL =
  "https://raw.githubusercontent.com/loyd-vitalbridgex/truegift-mcp/main/data/guides.json";
const TTL_MS = 6 * 3600 * 1000;
const FETCH_TIMEOUT_MS = 10000;

const OCCASIONS = ["christmas", "hanukkah", "birthday", "anniversary", "valentines",
  "mothers-day", "secret-santa", "white-elephant", "stocking", "housewarming", "black-friday"];
const RECIPIENTS = ["mom", "dad", "grandma", "grandpa", "grandparents", "husband", "wife",
  "girlfriend", "boyfriend", "coworker", "teacher", "nurse", "teen", "kids", "her", "him",
  "boss", "host", "mother-in-law", "gardener", "runner", "book-lover", "dog-lover", "parents"];

interface Pick { name: string; why?: string; budget_ceiling_usd?: number }
interface Guide {
  slug: string; title: string; url: string;
  occasions: string[]; recipients: string[]; budget_ceiling_usd: number | null;
  summary: string | null; picks: Pick[] | null;
}

function tagsFor(slug: string) {
  const m = slug.match(/under-(\d+)/);
  return {
    occasions: OCCASIONS.filter((o) => slug.includes(o)),
    recipients: RECIPIENTS.filter((r) => slug.includes(r)),
    budget_ceiling_usd: m ? parseInt(m[1], 10) : null,
  };
}
const titleFor = (slug: string) =>
  slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

async function fetchText(url: string): Promise<string> {
  const r = await fetch(url, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: { "User-Agent": "TrueGiftMCP/1.0 (+https://truegift.ai)" },
  });
  if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
  return await r.text();
}

// ---------- data layer ----------
let catalogCache: { at: number; guides: Guide[]; source: string } | null = null;
const detailsAt = new Map<string, number>();
let snapshotPromise: Promise<any | null> | null = null;

function loadSnapshot(): Promise<any | null> {
  if (!snapshotPromise) {
    snapshotPromise = fetchText(SNAPSHOT_URL).then((t) => JSON.parse(t)).catch(() => null);
  }
  return snapshotPromise;
}

function snapshotGuides(snap: any): Guide[] {
  return (snap?.guides ?? []).map((g: any) => ({
    slug: g.slug, title: g.title, url: g.url,
    occasions: g.occasions ?? [], recipients: g.recipients ?? [],
    budget_ceiling_usd: g.budget_ceiling_usd ?? null,
    summary: g.summary ?? null, picks: g.picks ?? [],
  }));
}

async function getCatalog(): Promise<{ guides: Guide[]; source: string }> {
  if (catalogCache && Date.now() - catalogCache.at <= TTL_MS) return catalogCache;
  try {
    const xml = await fetchText(`${SITE}/sitemap.xml`);
    const guides: Guide[] = [];
    for (const m of xml.matchAll(/<loc>(https:\/\/truegift\.ai\/(?:gifts|guides)\/([a-z0-9-]+))<\/loc>/g)) {
      const slug = m[2];
      const prev = catalogCache?.guides.find((g) => g.slug === slug);
      guides.push(prev ?? { slug, title: titleFor(slug), url: m[1], ...tagsFor(slug),
                            summary: null, picks: null });
    }
    if (guides.length) {
      catalogCache = { at: Date.now(), guides, source: "live" };
      return catalogCache;
    }
    throw new Error("empty sitemap parse");
  } catch {
    if (catalogCache) return catalogCache;
    const snap = await loadSnapshot();
    catalogCache = { at: Date.now(), guides: snapshotGuides(snap), source: "snapshot" };
    return catalogCache;
  }
}

async function ensureDetails(g: Guide): Promise<void> {
  const last = detailsAt.get(g.slug) ?? 0;
  if (g.picks !== null && Date.now() - last <= TTL_MS) return;
  try {
    const html = await fetchText(g.url);
    const m = html.match(/<script[^>]*data-gift-static[^>]*>([\s\S]*?)<\/script>/);
    if (!m) throw new Error("no static data");
    const graph = JSON.parse(m[1])["@graph"] ?? [];
    for (const node of graph) {
      if (node["@type"] === "Article") {
        const headline = (node.headline ?? "").replace(/\s*\(\d{4}\).*$/, "").trim();
        if (headline) g.title = headline;
        if (node.description) g.summary = node.description;
      } else if (node["@type"] === "ItemList") {
        g.picks = (node.itemListElement ?? [])
          .filter((el: any) => el.name)
          .map((el: any) => ({ name: el.name }));
      }
    }
    if (g.picks === null) g.picks = [];
    await applyOverlay(g);
    detailsAt.set(g.slug, Date.now());
  } catch {
    if (g.picks === null) {
      const snap = await loadSnapshot();
      const sg = snapshotGuides(snap).find((x) => x.slug === g.slug);
      g.picks = sg?.picks ?? [];
      if (sg?.summary) g.summary = sg.summary;
    }
  }
}

async function applyOverlay(g: Guide): Promise<void> {
  if (!g.picks?.length) return;
  const snap = await loadSnapshot();
  if (!snap) return;
  const overlay = new Map<string, any>();
  for (const sg of snap.guides ?? []) {
    for (const p of sg.picks ?? []) overlay.set(norm(p.name), p);
  }
  for (const p of g.picks) {
    let hit = overlay.get(norm(p.name));
    if (!hit) {
      for (const [key, sp] of overlay) {
        if (key.startsWith(norm(p.name).slice(0, 24)) || norm(p.name).startsWith(key.slice(0, 24))) {
          hit = sp; break;
        }
      }
    }
    if (hit) {
      if (hit.why && !p.why) p.why = hit.why;
      if (hit.budget_ceiling_usd != null && p.budget_ceiling_usd == null) {
        p.budget_ceiling_usd = hit.budget_ceiling_usd;
      }
    }
  }
}

// ---------- tool logic (mirrors server.py) ----------
const brief = (g: Guide) => ({
  title: g.title, url: g.url, slug: g.slug, occasions: g.occasions,
  recipients: g.recipients, budget_ceiling_usd: g.budget_ceiling_usd,
  pick_count: g.picks?.length ?? 0, summary: g.summary,
});
const pickOut = (p: Pick, g?: Guide) => ({
  name: p.name, why_it_fits: p.why ?? null,
  budget_ceiling_usd: p.budget_ceiling_usd ?? null,
  guide_title: g?.title ?? null, guide_url: g?.url ?? null,
});
const NOTE = "Prices change often; each guide links to today's price. " +
  "TrueGift may earn a commission on purchases, at no extra cost to the buyer.";

async function findGiftIdeas(a: any) {
  const rec = (a.recipient ?? "").trim().toLowerCase();
  const occ = (a.occasion ?? "").trim().toLowerCase().replace(/ /g, "-");
  const words = (a.interests ?? "").toLowerCase().replace(/,/g, " ").split(/\s+/)
    .filter((w: string) => w.length > 2);
  const budget = Number(a.max_budget_usd ?? 0) || 0;
  const score = (g: Guide) => {
    let s = 0;
    if (rec && g.recipients.includes(rec)) s += 3;
    if (occ && g.occasions.includes(occ)) s += 3;
    if (words.length && words.some((w: string) => g.slug.includes(w))) s += 2;
    if (budget && g.budget_ceiling_usd !== null) {
      s += g.budget_ceiling_usd <= budget ? 1 : -4;
    }
    return s;
  };
  const { guides } = await getCatalog();
  const ranked = guides.filter((g) => score(g) > 0)
    .sort((x, y) => score(y) - score(x));
  await Promise.all(ranked.slice(0, 8).map((g) => ensureDetails(g)));
  const picks: any[] = [];
  for (const g of ranked) {
    for (const p of g.picks ?? []) {
      if (budget && p.budget_ceiling_usd != null && p.budget_ceiling_usd > budget) continue;
      picks.push(pickOut(p, g));
    }
    if (picks.length >= 10) break;
  }
  return { picks: picks.slice(0, 10), guides: ranked.slice(0, 5).map(brief), note: NOTE };
}

async function listGiftGuides(a: any) {
  const occ = (a.occasion ?? "").trim().toLowerCase().replace(/ /g, "-");
  const rec = (a.recipient ?? "").trim().toLowerCase();
  const { guides } = await getCatalog();
  const out = guides.filter((g) =>
    (!occ || g.occasions.includes(occ)) && (!rec || g.recipients.includes(rec)));
  return { count: out.length, guides: out.slice(0, 25).map(brief) };
}

async function getGiftGuide(a: any) {
  const slug = (a.slug ?? "").trim().toLowerCase();
  const { guides } = await getCatalog();
  const g = guides.find((x) => x.slug === slug);
  if (!g) {
    return { title: "", url: "", slug, occasions: [], recipients: [],
      budget_ceiling_usd: null, pick_count: 0, summary: null, picks: [],
      picks_note: null,
      error: `No guide with slug '${slug}'. Use list_gift_guides to browse.` };
  }
  await ensureDetails(g);
  const picks = (g.picks ?? []).map((p) => pickOut(p));
  return { ...brief(g), picks,
    picks_note: picks.length ? null : "Pick-level data for this guide is on the guide page itself.",
    error: null };
}

// ---------- MCP surface ----------
const READ_ONLY = { readOnlyHint: true, destructiveHint: false,
  openWorldHint: false, idempotentHint: true };
const TOOLS = [
  {
    name: "find_gift_ideas",
    title: "Find gift ideas for a person or occasion",
    description: "Find gift ideas for a specific person and occasion. Searches TrueGift's " +
      "published gift guides and returns concrete product picks (with the reason each fits) " +
      "plus the best-matching guides. Examples: recipient=\"mom\", occasion=\"christmas\", " +
      "max_budget_usd=50; recipient=\"coworker\", occasion=\"secret-santa\", interests=\"coffee\".",
    inputSchema: { type: "object", properties: {
      recipient: { type: "string", default: "", description: "Who the gift is for (mom, dad, coworker, teen, wife...)." },
      occasion: { type: "string", default: "", description: "christmas, hanukkah, birthday, anniversary, secret-santa..." },
      interests: { type: "string", default: "", description: "Free-text interests (coffee, cooking, gardening, books...)." },
      max_budget_usd: { type: "integer", default: 0, description: "Budget ceiling in USD; 0 means no limit." },
    } },
    annotations: READ_ONLY,
  },
  {
    name: "list_gift_guides",
    title: "List TrueGift gift guides",
    description: "List TrueGift gift guides, optionally filtered by occasion or recipient.",
    inputSchema: { type: "object", properties: {
      occasion: { type: "string", default: "", description: "christmas, hanukkah, birthday, anniversary, secret-santa..." },
      recipient: { type: "string", default: "", description: "mom, dad, grandma, coworker, teacher, teen..." },
    } },
    annotations: READ_ONLY,
  },
  {
    name: "get_gift_guide",
    title: "Get one TrueGift gift guide with its picks",
    description: "Get one TrueGift gift guide by slug, including its gift picks when available.",
    inputSchema: { type: "object", properties: {
      slug: { type: "string", description: "The guide slug, e.g. \"christmas-gifts-for-her\" (from list_gift_guides)." },
    }, required: ["slug"] },
    annotations: READ_ONLY,
  },
];
const TOOL_FNS: Record<string, (a: any) => Promise<any>> = {
  find_gift_ideas: findGiftIdeas, list_gift_guides: listGiftGuides, get_gift_guide: getGiftGuide,
};
const SUPPORTED_PROTOCOLS = ["2024-11-05", "2025-03-26", "2025-06-18"];
const INSTRUCTIONS = "Gift recommendations from TrueGift.ai's published gift guides. " +
  "Use find_gift_ideas when someone describes a person or occasion; " +
  "every pick links back to its TrueGift guide.";

async function handleRpc(msg: any): Promise<any | null> {
  const { id, method, params } = msg ?? {};
  const isNotification = id === undefined || id === null;
  const result = (value: any) => ({ jsonrpc: "2.0", id, result: value });
  const error = (code: number, message: string) =>
    ({ jsonrpc: "2.0", id, error: { code, message } });
  try {
    switch (method) {
      case "initialize": {
        const want = params?.protocolVersion;
        return result({
          protocolVersion: SUPPORTED_PROTOCOLS.includes(want) ? want : "2025-03-26",
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "TrueGift Gift Finder", version: "1.0.0" },
          instructions: INSTRUCTIONS,
        });
      }
      case "ping":
        return isNotification ? null : result({});
      case "tools/list":
        return result({ tools: TOOLS });
      case "tools/call": {
        const fn = TOOL_FNS[params?.name];
        if (!fn) return error(-32602, `Unknown tool: ${params?.name}`);
        const data = await fn(params?.arguments ?? {});
        return result({
          content: [{ type: "text", text: JSON.stringify(data) }],
          structuredContent: data,
          isError: false,
        });
      }
      default:
        return isNotification ? null : error(-32601, `Method not found: ${method}`);
    }
  } catch (e) {
    return isNotification ? null : error(-32603, `Internal error: ${(e as Error).message}`);
  }
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, mcp-session-id, mcp-protocol-version",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};
const json = (body: any, status = 200) =>
  new Response(JSON.stringify(body), {
    status, headers: { ...CORS, "Content-Type": "application/json" },
  });

const port = Number(Deno.env.get("PORT") ?? "8000");
Deno.serve({ port }, async (req: Request) => {
  const path = new URL(req.url).pathname;
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

  if (req.method === "GET" && path.endsWith("/health")) {
    const { guides, source } = await getCatalog();
    return json({ status: "ok", service: "truegift-gift-finder",
                  guides: guides.length, data_source: source });
  }
  if (req.method === "GET" && path.endsWith("/.well-known/openai-apps-challenge")) {
    const token = (Deno.env.get("OPENAI_APPS_CHALLENGE_TOKEN") ?? "").trim();
    if (!token) return new Response("challenge token not configured", { status: 404, headers: CORS });
    return new Response(token, { headers: { ...CORS, "Content-Type": "text/plain" } });
  }
  if (req.method === "GET") {
    return json({ jsonrpc: "2.0", error: { code: -32000,
      message: "GET not supported on this stateless MCP endpoint; POST JSON-RPC instead." } }, 405);
  }
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400);
  }
  if (Array.isArray(body)) {
    const out = (await Promise.all(body.map(handleRpc))).filter((x) => x !== null);
    return out.length ? json(out) : new Response(null, { status: 202, headers: CORS });
  }
  const res = await handleRpc(body);
  return res === null ? new Response(null, { status: 202, headers: CORS }) : json(res);
});
