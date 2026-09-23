"""
prompt.py — BGMI Describe Bot
System prompt for OpenRouter + listing formatter.
AI returns JSON → Python formats it into a clean listing.
"""

import json
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# JSON schema sent to the AI
# ─────────────────────────────────────────────────────────────

_SCHEMA = {
    "title": (
        "Choose the most premium title that fits: "
        "GLACIER <GUN> ACCOUNT | AURORA <GUN> ACCOUNT | "
        "MYTHIC ACCOUNT | PREMIUM MULTI-SKIN ACCOUNT | "
        "PREMIUM ACCOUNT | BGMI ACCOUNT"
    ),
    "mythic_fashion": "integer (e.g. 45) OR null if not visible",
    "outfits": [
        "Exact outfit / character skin name as shown in-game"
    ],
    "gun_skins": [
        {
            "name": "Exact skin name (e.g. Glacier, Aurora, Dragonfly, Mythic)",
            "gun":  "Gun type (e.g. M416, AKM, UMP45, AWM, M762, SLR, DP-28)",
            "level": "integer upgrade level OR null"
        }
    ],
    "stats": {
        "level":                 "integer OR null",
        "elite_collector_level": "integer OR null",
        "season_rating":         "number OR null",
        "season_rank_percent":   "number OR null  (e.g. 5 means top 5%)",
        "achievement_points":    "integer OR null"
    },
    "helmets_bags": [
        "Exact helmet or bag skin name as shown in-game"
    ],
    "vehicles": [
        "Exact vehicle skin name as shown in-game"
    ]
}

# ─────────────────────────────────────────────────────────────
# System prompt sent to the vision model
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a BGMI (Battlegrounds Mobile India) account analyzer.
Analyze ALL provided screenshots as ONE single account.

Return ONLY a valid JSON object that exactly matches this schema:
{json.dumps(_SCHEMA, indent=2)}

━━━━━ STRICT RULES ━━━━━

ITEM NAMES
• Use EXACT names as shown in the game UI
• Examples: "Glacier M416", "Arctic Set", "BRDM Snow Leopard", "Mythic Character"
• NEVER write vague text like "multiple skins", "8+ outfits", "various weapons"
• Every visible item must appear as its own entry with its real name

NULL / EMPTY
• Use null for any stat field that is not visible in any screenshot
• Use [] (empty array) for any section with no visible items in any screenshot
• NEVER omit a key from the JSON — always include all keys

SCANNING
• Check EVERY corner of EVERY screenshot carefully
• BGMI uses stylized decorative fonts — read carefully, try multiple interpretations if unsure
• Only include items you can clearly see — never guess or hallucinate
• When multiple screenshots show different screens of the same account, combine all items

TITLE SELECTION (pick the most premium that applies)
• Glacier or Aurora skin clearly visible → "GLACIER <GUN> ACCOUNT" or "AURORA <GUN> ACCOUNT"
• Mythic outfit clearly visible          → "MYTHIC ACCOUNT"
• 5+ premium cosmetic skins              → "PREMIUM MULTI-SKIN ACCOUNT"
• 2–4 premium cosmetic skins             → "PREMIUM ACCOUNT"
• Otherwise                              → "BGMI ACCOUNT"

OUTPUT FORMAT
• Return ONLY the raw JSON object
• NO markdown, NO backticks, NO explanation, NO extra text
• The very first character must be {{ and the last must be }}
"""

# ─────────────────────────────────────────────────────────────
# Formatter: JSON → listing string
# ─────────────────────────────────────────────────────────────

def format_listing(raw: str) -> str:
    """
    Parse the AI's JSON response and format it into a BGMI listing.
    Falls back to returning the raw text if JSON parsing fails.
    """
    clean = raw.strip()

    # Strip markdown code fences the model might add despite instructions
    if clean.startswith("```"):
        parts = clean.split("```")
        if len(parts) >= 2:
            clean = parts[1].strip()
            if clean.lower().startswith("json"):
                clean = clean[4:].strip()

    try:
        data = json.loads(clean)
        return _build_listing(data)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e} — returning raw AI output")
        return clean   # graceful fallback: still useful to the user


def _build_listing(data: dict) -> str:
    """Convert parsed JSON dict into a formatted listing string."""
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────
    title = str(data.get("title", "BGMI ACCOUNT")).upper()
    lines += ["#G0", f"[ {title} ]", ""]

    # ── Mythic Fashion ────────────────────────────────────────
    mf = data.get("mythic_fashion")
    if mf is not None:
        lines += [f"➖ {mf}/300 Mythic Fashion", ""]

    # ── Outfits ───────────────────────────────────────────────
    outfits = [o for o in (data.get("outfits") or []) if isinstance(o, str) and o.strip()]
    if outfits:
        for o in outfits:
            lines.append(f"🎽 {o.strip()}")
        lines.append("")

    # ── Gun Skins ─────────────────────────────────────────────
    guns = [g for g in (data.get("gun_skins") or []) if isinstance(g, dict)]
    if guns:
        lines.append("Upgradable Weapons:")
        for g in guns:
            name = str(g.get("name") or "").strip()
            gun  = str(g.get("gun")  or "").strip()
            lvl  = f" (Lv. {g['level']})" if g.get("level") else ""
            entry = f"{name} {gun}".strip()
            if entry:
                lines.append(f"🔫 {entry}{lvl}")
        lines.append("")

    # ── Stats ─────────────────────────────────────────────────
    stats      = data.get("stats") or {}
    stat_lines : list[str] = []

    if stats.get("level"):
        stat_lines.append(f"⛔️ Account Level {stats['level']}+")
    if stats.get("elite_collector_level"):
        stat_lines.append(f"⛔️ Elite Collector Level {stats['elite_collector_level']}+")
    if stats.get("season_rating"):
        stat_lines.append(f"⛔️ Season Rating: {stats['season_rating']}+")
    if stats.get("season_rank_percent"):
        stat_lines.append(f"⛔️ Season Rank: Top {stats['season_rank_percent']}%+")
    if stats.get("achievement_points"):
        stat_lines.append(f"⛔️ Achievement Points: {stats['achievement_points']}+")

    if stat_lines:
        lines += stat_lines + [""]

    # ── Helmets / Bags ────────────────────────────────────────
    hb = [x for x in (data.get("helmets_bags") or []) if isinstance(x, str) and x.strip()]
    if hb:
        for item in hb:
            lines.append(f"🎒 {item.strip()}")
        lines.append("")

    # ── Vehicles ─────────────────────────────────────────────
    vehicles = [v for v in (data.get("vehicles") or []) if isinstance(v, str) and v.strip()]
    if vehicles:
        for v in vehicles:
            lines.append(f"🚘 {v.strip()}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────
    lines += [
        "✍️ Price: ",
        "✍️ Login: ",
        "✍️ Dm To Buy: ",
    ]

    return "\n".join(lines)
