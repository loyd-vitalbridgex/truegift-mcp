#!/usr/bin/env python3
"""Tests for the live data layer (gift_data.py) — no network: parsers run on
saved fixtures of the real site, and GuideStore runs on a stub fetcher.
Run: .venv/bin/python test_data.py"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from gift_data import GuideStore, parse_guide_page, parse_sitemap, tags_for  # noqa: E402

FIX = HERE / "tests" / "fixtures"


def main() -> int:
    sitemap = (FIX / "sitemap.xml").read_text()
    guides = parse_sitemap(sitemap)
    assert len(guides) == 91, len(guides)
    by_slug = {g["slug"]: g for g in guides}
    her = by_slug["christmas-gifts-for-her"]
    assert her["url"] == "https://truegift.ai/gifts/christmas-gifts-for-her"
    assert "christmas" in her["occasions"] and "her" in her["recipients"]
    assert by_slug["christmas-gifts-for-dad-under-50"]["budget_ceiling_usd"] == 50
    print("parse_sitemap: 91 guides, tags + budget OK")

    detail = parse_guide_page((FIX / "guide-christmas-gifts-for-her.html").read_text())
    assert detail["title"] == "Christmas Gifts for Her", detail.get("title")
    assert len(detail["picks"]) == 7
    assert detail["picks"][1]["name"].startswith("Yankee Candle")
    assert "winter evenings" in (detail["summary"] or "")
    assert parse_guide_page("<html>no data here</html>") == {}
    print("parse_guide_page: title, summary, 7 picks OK")

    t = tags_for("secret-santa-gifts-under-25-for-coworkers")
    assert "secret-santa" in t["occasions"] and "coworker" in t["recipients"]
    assert t["budget_ceiling_usd"] == 25
    print("tags_for OK")

    # Store with a stub fetcher: live catalog + lazy details + overlay merge.
    pages = {her["url"]: (FIX / "guide-christmas-gifts-for-her.html").read_text()}

    def stub_fetch(url: str) -> str:
        if url.endswith("sitemap.xml"):
            return sitemap
        if url in pages:
            return pages[url]
        raise RuntimeError(f"no stub for {url}")

    store = GuideStore(fetcher=stub_fetch)
    cat = store.catalog()
    assert store.source == "live" and len(cat) == 91
    g = store.get("christmas-gifts-for-her")
    store.ensure_details(g)
    assert len(g["picks"]) == 7
    yankee = [p for p in g["picks"] if p["name"].startswith("Yankee")][0]
    assert yankee.get("why"), "snapshot overlay should supply why-it-fits"
    assert yankee.get("budget_ceiling_usd") == 25, yankee
    print("GuideStore live fetch + snapshot overlay OK")

    # Store with a dead fetcher: snapshot fallback, never empty.
    def dead_fetch(url: str) -> str:
        raise RuntimeError("offline")

    store2 = GuideStore(fetcher=dead_fetch)
    cat2 = store2.catalog()
    assert len(cat2) == 91 and store2.source == "snapshot"
    g2 = store2.get("christmas-gifts-for-her")
    store2.ensure_details(g2)
    assert len(g2["picks"]) == 7  # snapshot picks survive offline
    print("GuideStore offline snapshot fallback OK")

    print("ALL DATA TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
