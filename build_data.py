#!/usr/bin/env python3
"""Build data/guides.json for the TrueGift MCP prototype.

Data provenance (snapshot: 2026-11-13):
- Guide catalog: every /gifts/* and /guides/* URL in https://truegift.ai/sitemap.xml
  as fetched 2026-11-13 (~103 guides).
- Pick-level data (names + why-it-fits): extracted from the live pages for the
  three highest-value holiday guides, fetched 2026-11-13:
  christmas-gift-ideas, christmas-gifts-for-her, hanukkah-gifts-for-kids
  (hanukkah pick names cross-checked against the page's JSON-LD ItemList).
- PRODUCTION NOTE: the live version of this server should not use a snapshot.
  The Lovable app already stores guides as JSON-LD @graph documents
  (src/lib/gifts, normalized stored graphs in Supabase) — swap this builder for
  a read of that store, or regenerate this file nightly from the sitemap +
  each page's <script data-gift-static> JSON-LD ItemList (name + /go/ URL).
"""
import json
import re
from pathlib import Path

GIFTS_SLUGS = """gifts-for-a-retired-nurse gifts-under-30-for-a-new-homeowner gifts-for-a-new-grandpa
gifts-for-a-coworker-leaving gifts-for-a-teen-who-loves-cooking secret-santa-gifts-under-25-for-coworkers
christmas-gifts-for-a-dad-who-has-everything gifts-for-a-mother-in-law-under-50 hanukkah-gifts-for-kids
stocking-stuffers-for-teens gifts-for-a-coworker-who-loves-coffee gifts-for-a-gardener
secret-santa-gifts-for-a-boss gifts-for-grandparents-who-have-everything gifts-for-a-teacher-under-25
gifts-for-a-new-dad-for-christmas hostess-gifts-for-a-christmas-party gifts-for-a-dog-lover-under-25
stocking-stuffers-for-teens-under-25 gifts-for-someone-who-works-from-home gifts-for-someone-who-is-always-cold
gifts-for-a-book-lover-under-25 gifts-for-a-runner-under-40 gifts-for-a-new-homeowner-under-30
christmas-gifts-for-coworkers-under-25 christmas-gifts-for-a-husband-who-has-everything
christmas-gifts-for-a-wife-who-has-everything christmas-gifts-for-a-mom-who-has-everything
gifts-for-teen-boys-under-50 secret-santa-gifts-under-20 stocking-stuffers-for-adults-under-10
gifts-for-her-under-50 last-minute-christmas-gifts-for-mom christmas-gifts-for-boyfriend-under-50
gifts-for-grandma gifts-for-grandpa gifts-for-grandparents-under-50 gifts-for-dad-who-has-everything
gifts-for-mom-who-has-everything anniversary-gifts anniversary-gifts-by-year 8-year-anniversary-gift
birthday-gift-for-wife 40th-birthday-ideas christmas-gift-ideas christmas-gifts-for-her
christmas-gifts-for-wife christmas-gifts-for-girlfriend stocking-stuffers white-elephant-gift-ideas
valentines-day-gifts mothers-day-gifts black-friday-gift-ideas camping-gifts-under-100
birthday-gifts-for-mom-under-50 christmas-gifts-for-dad-under-100 christmas-gifts-for-dad-under-50
christmas-gifts-for-grandma-under-25 christmas-gifts-for-grandpa-under-50 christmas-gifts-for-husband-under-50
christmas-gifts-for-mom-under-50 christmas-gifts-for-teen-boy-under-25 christmas-gifts-for-teen-girl-under-25
christmas-gifts-for-wife-under-50 family-board-game-gifts-under-25 gifts-for-coffee-lovers-under-100
gifts-for-dad-who-likes-coffee-under-50 gifts-for-dad-who-likes-grilling-under-50 gifts-for-home-cooks-under-100
gifts-for-outdoorsy-people-under-50 gifts-for-someone-who-loves-cooking-under-50 hanukkah-gifts-for-dad-under-50
hanukkah-gifts-for-mom-under-50 hanukkah-gifts-for-teens-under-25 secret-santa-gifts-under-15
teacher-gifts-under-25 tech-gifts-for-dad-under-100 white-elephant-gifts-under-25""".split()

GUIDES_SLUGS = """gifts-for-coffee-lovers gifts-for-new-dads gifts-for-teachers gifts-for-someone-who-has-everything
housewarming-gifts-under-30 gifts-for-nurses personalized-gifts gifts-for-parents-and-grandparents
cozy-gifts gifts-for-him gifts-under-75 gifts-for-the-host ai-christmas-gift-finder""".split()

OCCASIONS = ["christmas", "hanukkah", "birthday", "anniversary", "valentines", "mothers-day",
             "secret-santa", "white-elephant", "stocking", "housewarming", "black-friday"]
RECIPIENTS = ["mom", "dad", "grandma", "grandpa", "grandparents", "husband", "wife", "girlfriend",
              "boyfriend", "coworker", "teacher", "nurse", "teen", "kids", "her", "him", "boss",
              "host", "mother-in-law", "gardener", "runner", "book-lover", "dog-lover", "parents"]

# Pick-level data verified from the live pages on 2026-11-13.
PICKS = {
    "christmas-gift-ideas": [
        {"name": "ZIMASILK 100% Pure Mulberry Silk Pillow Cases for Hair and Skin", "why": "A mulberry silk pillowcase, a small luxury most people never buy for themselves.", "section": "For her"},
        {"name": "Burt's Bees Classics Gift Set", "why": "Six Burt's Bees classics in a tin, already gift-ready.", "section": "For her"},
        {"name": "Whiskey Stones Gift for Men (glasses set with wood box)", "why": "Two glasses and whiskey stones in a wood box, made for gifting.", "section": "For him"},
        {"name": "YETI Rambler 20 oz Stainless Steel Vacuum Insulated Tumbler", "why": "A YETI tumbler for the commute, the job site or the tailgate.", "section": "For him"},
        {"name": "Frameo 10.1\" WiFi Digital Picture Frame", "why": "A Wi-Fi photo frame for the family's pictures, long after the holidays.", "section": "For the family"},
        {"name": "Exploding Kittens The Board Game", "why": "A board game for 2-6 players for the week between Christmas and New Year's.", "section": "For the family"},
        {"name": "Ravensburger Christmas Market 1000 Piece Jigsaw Puzzle", "why": "A 1000-piece Christmas market puzzle to work on together.", "section": "For the family"},
        {"name": "\"Mom, I Want to Hear Your Story\" Guided Journal", "why": "A guided journal that asks mom about her life; the answers are hers.", "section": "Last-minute / unique"},
        {"name": "HotHands Hand Warmers Value Pack (10 pairs)", "why": "Ten pairs of hand warmers for cold days; easy to add to any order.", "section": "Last-minute / unique"},
    ],
    "christmas-gifts-for-her": [
        {"name": "ZIMASILK 100% Pure Mulberry Silk Pillow Cases for Hair and Skin", "why": "A mulberry silk pillowcase, the kind of treat most people skip buying for themselves.", "budget_ceiling_usd": 25},
        {"name": "Yankee Candle Balsam & Cedar Scented Candle, 22oz", "why": "A large balsam and cedar candle for winter evenings.", "budget_ceiling_usd": 25},
        {"name": "Bodum Bistro Double Wall Insulated Mug, Set of 2", "why": "Two double-wall glass mugs for her morning coffee.", "budget_ceiling_usd": 25},
        {"name": "Burt's Bees Classics Gift Set", "why": "Six Burt's Bees classics in a giftable tin.", "budget_ceiling_usd": 50},
        {"name": "LEGO Botanicals Peace Lily 11504", "why": "A LEGO peace lily to build, then display. No watering.", "budget_ceiling_usd": 50},
        {"name": "Owala FreeSip Stainless Steel Water Bottle 24 oz", "why": "An Owala FreeSip bottle for work, the gym and everything between.", "budget_ceiling_usd": 50},
        {"name": "Kendra Scott Elisa Pendant Necklace, 14k Gold-Plated", "why": "A simple gold-plated pendant she can wear every day.", "budget_ceiling_usd": 100},
    ],
    "hanukkah-gifts-for-kids": [
        {"name": "Rite Lite Wooden Dreidel Set"},
        {"name": "\"Latke, the Lucky Dog\" (book)"},
        {"name": "\"Hanukkah Bear\" by Eric Kimmel (book)"},
        {"name": "LEGO Classic Creative Bricks"},
        {"name": "Crayola Inspiration Art Case"},
        {"name": "Melissa & Doug Wooden Puzzle"},
        {"name": "Klutz Friendship Bracelet Kit"},
        {"name": "Magna-Tiles 32-Piece Set"},
    ],
}

SUMMARIES = {
    "christmas-gift-ideas": "9 picks for everyone on the list, sorted by who they're for. Short answer: Burt's Bees Classics Gift Set for a ready-to-give self-care tin, Frameo WiFi Digital Picture Frame for family photos, or Exploding Kittens The Board Game for time together.",
    "christmas-gifts-for-her": "7 ideas across budgets. Short answer: Yankee Candle Balsam & Cedar for winter evenings, LEGO Botanicals Peace Lily for building and displaying, or Burt's Bees Classics Gift Set for a self-care tin.",
    "hanukkah-gifts-for-kids": "8 picks for eight nights: dreidels and gelt-style treats, books, a craft kit, a game, and one bigger present; most picks under $25.",
}


def tags_for(slug: str) -> dict:
    occ = [o for o in OCCASIONS if o in slug]
    rec = [r for r in RECIPIENTS if r in slug]
    m = re.search(r"under-(\d+)", slug)
    return {"occasions": occ, "recipients": rec,
            "budget_ceiling_usd": int(m.group(1)) if m else None}


def title_for(slug: str) -> str:
    return slug.replace("-", " ").title().replace("Santa", "Santa")


def main() -> None:
    guides = []
    for section, slugs in (("gifts", GIFTS_SLUGS), ("guides", GUIDES_SLUGS)):
        for slug in slugs:
            g = {"slug": slug,
                 "title": title_for(slug),
                 "url": f"https://truegift.ai/{section}/{slug}",
                 **tags_for(slug)}
            if slug in PICKS:
                g["picks"] = PICKS[slug]
            if slug in SUMMARIES:
                g["summary"] = SUMMARIES[slug]
            guides.append(g)
    out = Path(__file__).parent / "data" / "guides.json"
    out.write_text(json.dumps({"snapshot_date": "2026-11-13", "source": "https://truegift.ai/sitemap.xml + live guide pages",
                               "guides": guides}, indent=1))
    print(f"wrote {out}: {len(guides)} guides, {sum(len(g.get('picks', [])) for g in guides)} picks")


if __name__ == "__main__":
    main()
