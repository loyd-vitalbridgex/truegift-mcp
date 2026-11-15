#!/usr/bin/env python3
"""Live guide data for the TrueGift Gift Finder MCP server.

Data strategy (production):
- Catalog: fetched from https://truegift.ai/sitemap.xml — every /gifts/* and
  /guides/* URL becomes a guide entry; occasion/recipient/budget tags are
  derived from the slug (same rules as build_data.py).
- Details: each guide page embeds a static JSON-LD @graph
  (<script data-gift-static>) with an Article (headline + description) and an
  ItemList of picks. Details are fetched lazily per guide and cached.
- Overlay: the bundled snapshot (data/guides.json) carries curated
  why-it-fits text and budget ceilings for the flagship guides; when a live
  pick's name matches a snapshot pick, the curated fields are reused.
- Fallback: if the live site is unreachable, the bundled snapshot is served
  as-is so the server never starts empty.

Refresh: catalog and per-guide details are cached in memory with a TTL
(env TRUGIFT_DATA_TTL_SECONDS, default 6h). An expired entry is refetched on
next use; a failed refetch keeps the stale copy.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

SITE = "https://truegift.ai"
SITEMAP_URL = f"{SITE}/sitemap.xml"
SNAPSHOT_PATH = Path(__file__).parent / "data" / "guides.json"
TTL_SECONDS = int(os.environ.get("TRUGIFT_DATA_TTL_SECONDS", "21600"))
FETCH_TIMEOUT = float(os.environ.get("TRUGIFT_FETCH_TIMEOUT_SECONDS", "10"))

OCCASIONS = ["christmas", "hanukkah", "birthday", "anniversary", "valentines", "mothers-day",
             "secret-santa", "white-elephant", "stocking", "housewarming", "black-friday"]
RECIPIENTS = ["mom", "dad", "grandma", "grandpa", "grandparents", "husband", "wife", "girlfriend",
              "boyfriend", "coworker", "teacher", "nurse", "teen", "kids", "her", "him", "boss",
              "host", "mother-in-law", "gardener", "runner", "book-lover", "dog-lover", "parents"]


def tags_for(slug: str) -> dict:
    occ = [o for o in OCCASIONS if o in slug]
    rec = [r for r in RECIPIENTS if r in slug]
    m = re.search(r"under-(\d+)", slug)
    return {"occasions": occ, "recipients": rec,
            "budget_ceiling_usd": int(m.group(1)) if m else None}


def title_for(slug: str) -> str:
    return slug.replace("-", " ").title()


def parse_sitemap(xml_text: str) -> list[dict]:
    """Extract guide entries from sitemap XML."""
    out = []
    for url in re.findall(r"<loc>(https://truegift\.ai/(?:gifts|guides)/[a-z0-9-]+)</loc>", xml_text):
        section, slug = url.rsplit("/", 2)[-2:]
        out.append({"slug": slug, "title": title_for(slug), "url": url, **tags_for(slug),
                    "summary": None, "picks": None})
    return out


_LD_RE = re.compile(r'<script[^>]*data-gift-static[^>]*>(.*?)</script>', re.S)


def parse_guide_page(html: str) -> dict:
    """Extract {title, summary, picks:[{name}]} from a guide page's static JSON-LD."""
    m = _LD_RE.search(html)
    if not m:
        return {}
    try:
        graph = json.loads(m.group(1)).get("@graph", [])
    except (json.JSONDecodeError, AttributeError):
        return {}
    out: dict = {}
    for node in graph:
        if node.get("@type") == "Article":
            headline = node.get("headline", "")
            out["title"] = re.sub(r"\s*\(\d{4}\).*$", "", headline).strip() or None
            out["summary"] = node.get("description") or None
        elif node.get("@type") == "ItemList":
            picks = []
            for el in node.get("itemListElement", []):
                name = el.get("name")
                if name:
                    picks.append({"name": name})
            out["picks"] = picks
    return out


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


class GuideStore:
    """Thread-safe guide catalog with live refresh + snapshot fallback."""

    def __init__(self, fetcher=None, snapshot_path: Path = SNAPSHOT_PATH):
        # fetcher: callable(url) -> text. Injectable for tests.
        self._fetch = fetcher or self._http_fetch
        self._lock = threading.Lock()
        self._snapshot = json.loads(snapshot_path.read_text())["guides"]
        self._overlay = {}
        for g in self._snapshot:
            for p in g.get("picks", []):
                self._overlay[_norm(p["name"])] = p
        self._guides: list[dict] = []
        self._by_slug: dict[str, dict] = {}
        self._catalog_at = 0.0
        self._details_at: dict[str, float] = {}
        self.source = "snapshot"  # 'live' once a sitemap fetch succeeds
        self._load_snapshot()

    @staticmethod
    def _http_fetch(url: str) -> str:
        headers = {"User-Agent": "TrueGiftMCP/1.0 (+https://truegift.ai)"}
        try:
            with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True,
                              headers=headers) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.text
        except httpx.InvalidURL:
            # Some sandboxes export a no_proxy list httpx cannot parse
            # (bracketed IPv6 entries). Retry with an explicit proxy URL.
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True,
                              headers=headers, proxy=proxy) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.text

    def _load_snapshot(self) -> None:
        self._guides = [dict(g, picks=list(g.get("picks", []))) for g in self._snapshot]
        self._by_slug = {g["slug"]: g for g in self._guides}

    # -- catalog ---------------------------------------------------------
    def _refresh_catalog(self) -> None:
        try:
            guides = parse_sitemap(self._fetch(SITEMAP_URL))
        except Exception:
            guides = []
        if not guides:
            return  # keep whatever we have (snapshot or stale live)
        with self._lock:
            old = self._by_slug
            for g in guides:
                prev = old.get(g["slug"])
                if prev and prev.get("picks"):
                    g["picks"] = prev["picks"]
                    if prev.get("summary"):
                        g["summary"] = prev["summary"]
                    if prev.get("title"):
                        g["title"] = prev["title"]
            self._guides = guides
            self._by_slug = {g["slug"]: g for g in guides}
            self._catalog_at = time.time()
            self.source = "live"

    def catalog(self) -> list[dict]:
        if time.time() - self._catalog_at > TTL_SECONDS:
            self._refresh_catalog()
        with self._lock:
            return list(self._guides)

    def get(self, slug: str) -> dict | None:
        self.catalog()
        with self._lock:
            return self._by_slug.get(slug)

    # -- per-guide details -------------------------------------------------
    def _apply_overlay(self, picks: list[dict]) -> list[dict]:
        out = []
        for p in picks:
            merged = dict(p)
            hit = self._overlay.get(_norm(p["name"]))
            if hit is None:  # tolerate small name drift (e.g. ", 22oz" suffix)
                for key, snap in self._overlay.items():
                    if key.startswith(_norm(p["name"])[:24]) or _norm(p["name"]).startswith(key[:24]):
                        hit = snap
                        break
            if hit:
                merged.setdefault("why", hit.get("why"))
                if hit.get("budget_ceiling_usd") is not None:
                    merged.setdefault("budget_ceiling_usd", hit["budget_ceiling_usd"])
            out.append(merged)
        return out

    def ensure_details(self, guide: dict) -> dict:
        """Fetch (or refresh) a guide's picks/summary from its live page."""
        slug = guide["slug"]
        last = self._details_at.get(slug, 0.0)
        if guide.get("picks") is not None and time.time() - last <= TTL_SECONDS:
            return guide
        try:
            detail = parse_guide_page(self._fetch(guide["url"]))
        except Exception:
            detail = {}
        if detail:
            with self._lock:
                if detail.get("picks") is not None:
                    guide["picks"] = self._apply_overlay(detail["picks"])
                if detail.get("summary"):
                    guide["summary"] = detail["summary"]
                if detail.get("title"):
                    guide["title"] = detail["title"]
                self._details_at[slug] = time.time()
        elif guide.get("picks") is None:
            guide["picks"] = []
        return guide

    def ensure_details_many(self, guides: list[dict]) -> None:
        stale = [g for g in guides
                 if g.get("picks") is None or time.time() - self._details_at.get(g["slug"], 0.0) > TTL_SECONDS]
        if not stale:
            return
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(self.ensure_details, stale))
