"""
BGMI Describe Bot — @ListoAIbot
Analyzes BGMI screenshots and generates structured listings.
3 buttons: GUNS | VEHICLE | FULL INVENTORY
Deploy on Railway · Uses OpenRouter vision API
"""

import os
import io
import logging
import base64
import asyncio

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError, Conflict, NetworkError

from prompt import (
    SYSTEM_PROMPT,
    parse_ai_response,
    format_guns,
    format_vehicles,
    format_full_inventory,
)

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment Variables  (set in Railway → Variables)
# ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL   = os.getenv(
    "OPENROUTER_MODEL",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
).strip()
API_BASE_URL       = os.getenv(
    "API_BASE_URL",
    "https://openrouter.ai/api/v1",
).strip().rstrip("/")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing env var: TELEGRAM_BOT_TOKEN")
if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing env var: OPENROUTER_API_KEY")

# ─────────────────────────────────────────────────────────────
# In-memory state
# ─────────────────────────────────────────────────────────────

# Media group batching
_pending_groups:   dict[str, list[str]] = {}   # group_id → [file_id, ...]
_scheduled_groups: set[str]             = set() # group_ids with a scheduled task

# Parsed account data cache — keyed by chat_id
# Stores the latest parsed JSON dict per user so buttons can retrieve it
_user_cache: dict[int, dict] = {}

# ─────────────────────────────────────────────────────────────
# Image helpers
# ─────────────────────────────────────────────────────────────

def _detect_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _prepare_image(raw: bytes) -> tuple[str, str]:
    """Compress + resize image → (base64_string, mime_type)."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA", "L"):
            img = img.convert("RGB")
        if max(img.size) > 1280:
            img.thumbnail((1280, 1280), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()
        return base64.standard_b64encode(compressed).decode(), "image/jpeg"

    except ImportError:
        logger.warning("Pillow not installed — sending original bytes")
    except Exception as e:
        logger.warning(f"Image compression failed: {e}")

    mime = _detect_mime(raw)
    return base64.standard_b64encode(raw).decode(), mime


# ─────────────────────────────────────────────────────────────
# OpenRouter API
# ─────────────────────────────────────────────────────────────

async def _call_openrouter(images: list[tuple[str, str]]) -> str:
    """
    Send images to OpenRouter vision model.
    Returns raw string response from AI.
    Retries up to 3 times with exponential backoff.
    """
    url     = f"{API_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://github.com/listo-ai-bot",
        "X-Title":       "BGMI Describe Bot",
    }

    content: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    for b64, mime in images:
        content.append({
            "type":      "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    payload = {
        "model":      OPENROUTER_MODEL,
        "messages":   [{"role": "user", "content": content}],
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

            resp_data     = resp.json()
            content_value = resp_data["choices"][0]["message"]["content"]

            if content_value is None:
                finish = resp_data["choices"][0].get("finish_reason", "unknown")
                raise ValueError(
                    f"Model '{OPENROUTER_MODEL}' returned empty response "
                    f"(finish_reason={finish}). "
                    "Vision support nahi hai ya rate limit. Model change karo."
                )

            raw = content_value.strip()
            logger.info(
                f"OpenRouter OK | model={OPENROUTER_MODEL} "
                f"| images={len(images)} | chars={len(raw)} | attempt={attempt}"
            )
            return raw

        except httpx.HTTPStatusError as e:
            last_exc = e
            code     = e.response.status_code
            logger.error(f"OpenRouter HTTP {code} (attempt {attempt}): {e.response.text[:300]}")
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            raise

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            logger.error(f"OpenRouter network error (attempt {attempt}): {e}")
            if attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            raise

    raise last_exc


# ─────────────────────────────────────────────────────────────
# Button builder
# ─────────────────────────────────────────────────────────────

def _build_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """3-button inline keyboard for choosing which section to show."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔫 GUNS",          callback_data=f"guns:{chat_id}"),
        InlineKeyboardButton("🚘 VEHICLE",       callback_data=f"vehicle:{chat_id}"),
        InlineKeyboardButton("📦 FULL INVENTORY", callback_data=f"full:{chat_id}"),
    ]])


# ─────────────────────────────────────────────────────────────
# Photo processing
# ─────────────────────────────────────────────────────────────

async def _process_photos(
    file_ids: list[str],
    chat_id:  int,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Download → compress → analyze → cache JSON → send 3 buttons."""

    # ── Download all images ──────────────────────────────────
    images: list[tuple[str, str]] = []
    for idx, fid in enumerate(file_ids, 1):
        try:
            file_obj = await context.bot.get_file(fid)
            raw      = bytes(await file_obj.download_as_bytearray())
            images.append(_prepare_image(raw))
            logger.info(f"Downloaded photo {idx}/{len(file_ids)}")
        except Exception as e:
            logger.error(f"Failed to download photo {idx}: {e}")

    if not images:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Screenshots download nahi hue. Dobara try karo.",
        )
        return

    # ── Call OpenRouter ──────────────────────────────────────
    try:
        raw = await _call_openrouter(images)
    except httpx.HTTPStatusError as e:
        logger.error(f"API HTTP error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="❌ AI API error. Thodi der baad try karo.")
        return
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await context.bot.send_message(chat_id=chat_id, text="❌ Screenshot analyze nahi hua. Dobara try karo.")
        return

    # ── Parse JSON & cache ───────────────────────────────────
    data = parse_ai_response(raw)
    _user_cache[chat_id] = data
    logger.info(f"Cached data for chat_id={chat_id}")

    # ── Send 3 buttons ───────────────────────────────────────
    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ Analysis complete! Kya dekhna hai?",
        reply_markup=_build_keyboard(chat_id),
    )


# ─────────────────────────────────────────────────────────────
# Media-group batcher
# ─────────────────────────────────────────────────────────────

async def _process_group_after_delay(
    media_group_id: str,
    chat_id:        int,
    context:        ContextTypes.DEFAULT_TYPE,
) -> None:
    """Wait 2 s for all group photos, then process together."""
    await asyncio.sleep(2)

    _scheduled_groups.discard(media_group_id)
    file_ids = _pending_groups.pop(media_group_id, [])
    if not file_ids:
        return

    n          = len(file_ids)
    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ {n} screenshot{'s' if n > 1 else ''} analyze ho raha hai... wait karo",
        )
        await _process_photos(file_ids, chat_id, context)
    except Exception as e:
        logger.error(f"Group {media_group_id} error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="❌ Error aaya. Dobara try karo.")
    finally:
        if status_msg:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
            except TelegramError:
                pass


# ─────────────────────────────────────────────────────────────
# Callback handler (button clicks)
# ─────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks: guns / vehicle / full."""
    query = update.callback_query
    await query.answer()   # removes the loading spinner on button

    if not query.data or ":" not in query.data:
        return

    action, owner_id_str = query.data.split(":", 1)
    chat_id = update.effective_chat.id

    # Retrieve cached data
    data = _user_cache.get(int(owner_id_str))
    if not data:
        await query.message.reply_text(
            "⚠️ Data expire ho gaya. Dobara screenshot bhejo.",
        )
        return

    # Format the requested section
    if action == "guns":
        text = format_guns(data)
    elif action == "vehicle":
        text = format_vehicles(data)
    else:   # "full"
        text = format_full_inventory(data)

    # Send as a new message (buttons stay visible for re-use)
    await _send_long_message(chat_id, text, context)


# ─────────────────────────────────────────────────────────────
# Long message helper
# ─────────────────────────────────────────────────────────────

async def _send_long_message(
    chat_id: int,
    text:    str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Send text, splitting on paragraph breaks if > Telegram's 4096 char limit."""
    MAX = 4096
    if len(text) <= MAX:
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    chunk = ""
    for para in text.split("\n\n"):
        candidate = chunk + para + "\n\n"
        if len(candidate) <= MAX:
            chunk = candidate
        else:
            if chunk.strip():
                await context.bot.send_message(chat_id=chat_id, text=chunk.strip())
            chunk = para + "\n\n"
    if chunk.strip():
        await context.bot.send_message(chat_id=chat_id, text=chunk.strip())


# ─────────────────────────────────────────────────────────────
# Telegram handlers
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎮 BGMI Describe Bot\n\n"
        "BGMI account ke screenshots bhejo — main analyze karke\n"
        "3 buttons deta hoon:\n\n"
        "🔫 GUNS — sirf gun skins\n"
        "🚘 VEHICLE — sirf vehicle skins\n"
        "📦 FULL INVENTORY — sab kuch\n\n"
        "Ek ya multiple screenshots ek saath bhej sakte ho.\n\n"
        "/help — commands dekhne ke liye"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 Help\n\n"
        "Screenshot bhejo → Bot analyze karega → 3 buttons aayenge:\n"
        "🔫 GUNS | 🚘 VEHICLE | 📦 FULL INVENTORY\n\n"
        "Jo chahiye woh button dabao — woh section milega.\n\n"
        "Commands:\n"
        "/start  — welcome message\n"
        "/help   — yeh message\n"
        "/model  — current AI model\n\n"
        "Detects:\n"
        "🔫 Gun skins with level + Final Form\n"
        "🎽 Outfit / character skins\n"
        "🚘 Vehicle skins\n"
        "🎒 Helmet / bag skins\n"
        "⛔️ Account stats, room cards, popularity etc."
    )


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🤖 Current model:\n{OPENROUTER_MODEL}\n\n"
        f"🌐 API Base URL:\n{API_BASE_URL}\n\n"
        "Change karne ke liye Railway → Variables:\n"
        "• OPENROUTER_MODEL\n"
        "• API_BASE_URL"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming photo messages.
    Single photo  → process immediately.
    Media group   → collect all, process together after 2 s.
    """
    chat_id        = update.effective_chat.id
    file_id        = update.message.photo[-1].file_id   # highest resolution
    media_group_id = update.message.media_group_id

    if media_group_id:
        # Batch mode: collect all photos first
        if media_group_id not in _pending_groups:
            _pending_groups[media_group_id] = []
        _pending_groups[media_group_id].append(file_id)

        # Schedule exactly ONE task per group
        if media_group_id not in _scheduled_groups:
            _scheduled_groups.add(media_group_id)
            asyncio.create_task(
                _process_group_after_delay(media_group_id, chat_id, context)
            )
    else:
        # Single photo
        status_msg = None
        try:
            status_msg = await update.message.reply_text(
                "⏳ Screenshot analyze ho raha hai... wait karo"
            )
            await _process_photos([file_id], chat_id, context)
        except Exception as e:
            logger.error(f"Single photo error: {e}")
            await update.message.reply_text("❌ Error aaya. Dobara try karo.")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except TelegramError:
                    pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📸 BGMI account ka screenshot bhejo — main listing bana dunga!"
    )


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    err = context.error
    if isinstance(err, Conflict):
        logger.warning("409 Conflict: Railway redeploy overlap. Will resolve in seconds.")
        return
    if isinstance(err, NetworkError):
        logger.warning(f"NetworkError (temporary): {err}")
        return
    logger.error(f"Unhandled error: {err}", exc_info=err)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Starting BGMI Describe Bot (@ListoAIbot)")
    logger.info(f"Model: {OPENROUTER_MODEL}")
    logger.info(f"API Base URL: {API_BASE_URL}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("model", cmd_model))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO,                   handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Global error handler
    app.add_error_handler(handle_error)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
