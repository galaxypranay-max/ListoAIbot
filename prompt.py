"""
prompt.py — BGMI Describe Bot
System prompt + section formatters for 3-button listing.
"""

import json
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# JSON Schema
# ─────────────────────────────────────────────────────────────

_SCHEMA = {
    "title": "Most premium title: GLACIER <GUN> ACCOUNT | AURORA <GUN> ACCOUNT | MYTHIC ACCOUNT | PREMIUM MULTI-SKIN ACCOUNT | PREMIUM ACCOUNT | BGMI ACCOUNT",
    "mythic_fashion": "integer (e.g. 45) OR null",
    "outfits": ["Exact outfit / character skin name"],
    "gun_skins": [
        {
            "name": "Exact skin name (e.g. Glacier, Aurora, Nautical Expert)",
            "gun":  "Gun type (e.g. M416, AKM, SLR, DP-28, UMP45, Kar98K)",
            "level": "integer upgrade level OR null",
            "is_final_form": "true if gun shows Final Form badge, else false"
        }
    ],
    "stats": {
        "level":                  "integer OR null",
        "elite_collector_level":  "integer OR null",
        "season_rating":          "number OR null",
        "season_rank_percent":    "number OR null (e.g. 5 = top 5%)",
        "achievement_points":     "integer OR null",
        "total_popularity":       "string OR null (e.g. '2.17 Million')",
        "weekly_room_cards":      "integer OR null",
        "daily_room_cards":       "integer OR null",
        "starforge_stones":       "integer OR null",
        "xsuit_golden_store":     "integer OR null",
        "engine_core":            "integer OR null",
        "gun_slots_unlocked":     "true / false / null"
    },
    "helmets": {
        "total_count":   "integer OR null",
        "special_skins": ["Specific premium or mythic helmet skin name"]
    },
    "bags": {
        "total_count":   "integer OR null",
        "special_skins": ["Specific premium or mythic bag skin name"]
    },
    "vehicles": [
        "Exact vehicle skin name OR count summary e.g. 'Total Motorcycle Skins 11+'"
    ]
}

# ─────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a BGMI (Battlegrounds Mobile India) account analyzer.
Analyze ALL provided screenshots as ONE single account.

Return ONLY a valid JSON object matching this schema exactly:
{json.dumps(_SCHEMA, indent=2)}

━━━━━ STRICT RULES ━━━━━

ITEM NAMES
• Use EXACT names as shown in the game UI
• NEVER write vague text like "multiple skins", "8+ outfits", "various weapons"
• Every visible item gets its own entry with its real name

GUN SKINS
• Set is_final_form: true only if the gun shows a "Final Form" badge in the screenshot
• Capture every visible gun skin — check upgrade/weapon/inventory screens carefully

VEHICLE SKINS
• List specific named skins individually
• For categories with many skins, add a count entry e.g. "Total Buggy Skins 9+"
• Keep both: named ones AND count summaries if both are visible

HELMETS & BAGS
• total_count = total number shown on screen (e.g. 45)
• special_skins = only the premium/mythic/rare/named ones (list each individually)

STATS
• Extract every numeric stat visible across ALL screenshots
• gun_slots_unlocked = true only if screenshot explicitly shows all slots unlocked
• Collect room cards, starforge stones, popularity etc. wherever visible

NULL / EMPTY
• null for any field not visible in any screenshot
• [] for any array section with no visible items
• NEVER omit a key — always include all keys

OUTPUT FORMAT
• Return ONLY raw JSON — no markdown, no backticks, no explanation
• First character must be {{ and last must be }}"""

# ─────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────

def parse_ai_response(raw: str) -> dict:
    """Parse AI's JSON response into a dict. Returns dict with '_raw' key on failure."""
    clean = raw.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        if len(parts) >= 2:
            clean = parts[1].strip()
            if clean.lower().startswith("json"):
                clean = clean[4:].strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e} — storing raw text")
        return {"_raw": clean}

# ─────────────────────────────────────────────────────────────
# Section Formatters
# ─────────────────────────────────────────────────────────────

def _gun_line(g: dict) -> str:
    """Format one gun skin entry."""
    name  = str(g.get("name") or "").strip()
    gun   = str(g.get("gun")  or "").strip()
    level = g.get("level")
    final = g.get("is_final_form", False)

    entry = f"{name} {gun}".strip()
    if level:
        entry += f" Lv- {level}"
    if final:
        entry += " (Final Form)"
    return f"🔫 {entry}"


def format_guns(data: dict) -> str:
    """Format only the GUNS section."""
    if "_raw" in data:
        return data["_raw"]

    guns = [g for g in (data.get("gun_skins") or []) if isinstance(g, dict)]
    if not guns:
        return "🔫 GUNS\n\nKoi gun skin nahi mila."

    lines = ["🔫 GUNS\n"]
    for g in guns:
        lines.append(_gun_line(g))
    return "\n".join(lines)


def format_vehicles(data: dict) -> str:
    """Format only the VEHICLE section."""
    if "_raw" in data:
        return data["_raw"]

    vehicles = [v for v in (data.get("vehicles") or []) if isinstance(v, str) and v.strip()]
    if not vehicles:
        return "🚘 VEHICLE\n\nKoi vehicle skin nahi mila."

    lines = ["🚘 VEHICLE\n"]
    for v in vehicles:
        lines.append(f"🚘 {v.strip()}")
    return "\n".join(lines)


def format_full_inventory(data: dict) -> str:
    """Format the complete FULL INVENTORY section (everything)."""
    if "_raw" in data:
        return data["_raw"]

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────
    title = str(data.get("title") or "BGMI ACCOUNT").upper()
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
            lines.append(_gun_line(g))
        lines.append("")

    # ── Stats ─────────────────────────────────────────────────
    stats = data.get("stats") or {}
    stat_lines: list[str] = []

    if stats.get("level"):
        stat_lines.append(f"⛔️ Account Level : {stats['level']}+ (Very High)")
    if stats.get("elite_collector_level"):
        stat_lines.append(f"⛔️ EVO Account Level {stats['elite_collector_level']}+ (High)")
    if stats.get("achievement_points"):
        stat_lines.append(f"⛔️ Achievement Point {stats['achievement_points']}")

    # Helmets
    helmets = data.get("helmets") or {}
    if helmets.get("total_count"):
        stat_lines.append(f"⛔️ {helmets['total_count']}+ Total Helmet Skins")
    for h in (helmets.get("special_skins") or []):
        if isinstance(h, str) and h.strip():
            stat_lines.append(f"⛔️ {h.strip()}")

    # Bags
    bags = data.get("bags") or {}
    if bags.get("total_count"):
        stat_lines.append(f"⛔️ {bags['total_count']}+ Total Bagpack Skins")
    for b in (bags.get("special_skins") or []):
        if isinstance(b, str) and b.strip():
            stat_lines.append(f"⛔️ {b.strip()}")

    # Extra stats
    if stats.get("starforge_stones"):
        stat_lines.append(f"⛔️ Starforge Stone Total {stats['starforge_stones']}+")
    if stats.get("weekly_room_cards"):
        stat_lines.append(f"⛔️ Weekly Room Cards {stats['weekly_room_cards']}+")
    if stats.get("daily_room_cards"):
        stat_lines.append(f"⛔️ Daily Room Card {stats['daily_room_cards']}+")
    if stats.get("gun_slots_unlocked"):
        stat_lines.append("⛔️ All Guns Slots Unlocked")
    if stats.get("total_popularity"):
        stat_lines.append(f"⛔️ Total Popularity {stats['total_popularity']}")
    if stats.get("xsuit_golden_store"):
        stat_lines.append(f"⛔️ X-Suit Golden Store {stats['xsuit_golden_store']}x")
    if stats.get("engine_core"):
        stat_lines.append(f"⛔️ Engine Core {stats['engine_core']} Material")
    if stats.get("season_rating"):
        stat_lines.append(f"⛔️ Season Rating: {stats['season_rating']}+")
    if stats.get("season_rank_percent"):
        stat_lines.append(f"⛔️ Season Rank: Top {stats['season_rank_percent']}%+")

    if stat_lines:
        lines += stat_lines + [""]

    # ── Vehicles ─────────────────────────────────────────────
    vehicles = [v for v in (data.get("vehicles") or []) if isinstance(v, str) and v.strip()]
    if vehicles:
        for v in vehicles:
            lines.append(f"🚘 {v.strip()}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────
    lines += ["✍️ Price: ", "✍️ Login: ", "✍️ Dm To Buy: "]

    return "\n".join(lines)
