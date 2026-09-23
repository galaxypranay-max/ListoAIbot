"""
BGMI Describe Bot — @ListoAIbot
Analyzes BGMI screenshots and generates structured listings.
Deploy on Railway · Uses OpenRouter vision API
"""

import os
import io
import logging
import base64
import asyncio

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError

from prompt import SYSTEM_PROMPT, format_listing

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment Variables  (set these in Railway)
# ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL   = os.getenv(
    "OPENROUTER_MODEL",
    "meta-llama/llama-3.2-11b-vision-instruct:free",   # change via Railway env var
).strip()

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing env var: TELEGRAM_BOT_TOKEN")
if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing env var: OPENROUTER_API_KEY")

# ─────────────────────────────────────────────────────────────
# Media-group batching state
# ─────────────────────────────────────────────────────────────

# { media_group_id: [file_id, ...] }
_pending_groups: dict[str, list[str]] = {}

# media_group_ids that already have a scheduled asyncio task
_scheduled_groups: set[str] = set()

# ─────────────────────────────────────────────────────────────
# Image helpers
# ─────────────────────────────────────────────────────────────

def _detect_mime(data: bytes) -> str:
    """Detect image MIME type from magic bytes — no external library needed."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # safe fallback


def _prepare_image(raw: bytes) -> tuple[str, str]:
    """
    Compress & resize image, return (base64_string, mime_type).
    Falls back to raw bytes if Pillow is unavailable.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))

        # JPEG doesn't support alpha — convert to RGB
        if img.mode in ("RGBA", "P", "LA", "L"):
            img = img.convert("RGB")

        # Resize: keep longest side ≤ 1280 px  (saves API time & cost)
        if max(img.size) > 1280:
            img.thumbnail((1280, 1280), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()
        return base64.standard_b64encode(compressed).decode(), "image/jpeg"

    except ImportError:
        logger.warning("Pillow not installed — sending original image bytes")
    except Exception as e:
        logger.warning(f"Image compression failed: {e} — sending original")

    mime = _detect_mime(raw)
    return base64.standard_b64encode(raw).decode(), mime


# ─────────────────────────────────────────────────────────────
# OpenRouter API
# ─────────────────────────────────────────────────────────────

async def _call_openrouter(images: list[tuple[str, str]]) -> str:
    """
    Send images to OpenRouter vision model.
    images : list of (base64_data, mime_type)
    Returns: formatted listing string
    Retries up to 3 times with exponential backoff.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/listo-ai-bot",
        "X-Title": "BGMI Describe Bot",
    }

    # Build vision message: prompt text + one image block per screenshot
    content: list[dict] = [{"type": "text", "text": SYSTEM_PROMPT}]
    for b64, mime in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

            response_data = resp.json()
            content_value = response_data["choices"][0]["message"]["content"]

            # Some models return None when they don't support vision/images
            if content_value is None:
                finish_reason = response_data["choices"][0].get("finish_reason", "unknown")
                raise ValueError(
                    f"Model '{OPENROUTER_MODEL}' returned empty response "
                    f"(finish_reason={finish_reason}). "
                    f"Yeh model vision/image support nahi karta. "
                    f"Railway Variables mein OPENROUTER_MODEL change karo — "
                    f"recommended: meta-llama/llama-3.2-11b-vision-instruct:free"
                )

            raw = content_value.strip()
            logger.info(
                f"OpenRouter OK | model={OPENROUTER_MODEL} "
                f"| images={len(images)} | chars={len(raw)} | attempt={attempt}"
            )
            return format_listing(raw)

        except httpx.HTTPStatusError as e:
            last_exc = e
            code = e.response.status_code
            logger.error(f"OpenRouter HTTP {code} (attempt {attempt}): {e.response.text[:300]}")
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                await asyncio.sleep(2 ** attempt)   # 2 s → 4 s
                continue
            raise   # non-retryable (4xx etc.)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            logger.error(f"OpenRouter network error (attempt {attempt}): {e}")
            if attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            raise

    raise last_exc


# ─────────────────────────────────────────────────────────────
# Photo processing
# ─────────────────────────────────────────────────────────────

async def _process_photos(
    file_ids: list[str],
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Download → compress → analyze → send listing."""

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
            text="❌ Screenshots download hone mein error aaya.\nPlease dobara try karo.",
        )
        return

    # ── Call OpenRouter ──────────────────────────────────────
    try:
        listing = await _call_openrouter(images)
    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ AI API error. Thodi der baad try karo.",
        )
        return
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Screenshot analyze nahi hua. Dobara try karo.",
        )
        return

    # ── Send listing (split if > 4096 chars) ────────────────
    await _send_long_message(chat_id, listing, context)


async def _send_long_message(
    chat_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Send text, splitting on paragraph breaks if it exceeds Telegram's 4096 char limit."""
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
# Media-group batch processor
# ─────────────────────────────────────────────────────────────

async def _process_group_after_delay(
    media_group_id: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Wait 2 s for all photos in a media group to arrive, then
    process them ALL together in a single API call.
    """
    await asyncio.sleep(2)

    _scheduled_groups.discard(media_group_id)
    file_ids = _pending_groups.pop(media_group_id, [])

    if not file_ids:
        return

    n = len(file_ids)
    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ {n} screenshot{'s' if n > 1 else ''} analyze ho raha hai... wait karo",
        )
        await _process_photos(file_ids, chat_id, context)
    except Exception as e:
        logger.error(f"Group {media_group_id} processing error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Kuch error aaya. Dobara try karo.",
        )
    finally:
        if status_msg:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                )
            except TelegramError:
                pass


# ─────────────────────────────────────────────────────────────
# Telegram handlers
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎮 BGMI Describe Bot\n\n"
        "BGMI account ke screenshots bhejo — main gun, outfit, vehicle, "
        "helmet/bag aur stats sab detect karke structured listing bana dunga.\n\n"
        "Ek ya multiple screenshots ek saath bhej sakte ho.\n\n"
        "/help — commands dekhne ke liye"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 BGMI Describe Bot — Help\n\n"
        "Kya karta hai:\n"
        "🔫 Gun skins (naam + level)\n"
        "🎽 Outfit / character skins\n"
        "🚘 Vehicle skins\n"
        "🎒 Helmet / bag skins\n"
        "⛔️ Account stats\n"
        "➖ Mythic Fashion count\n\n"
        "Commands:\n"
        "/start  — welcome message\n"
        "/help   — yeh message\n"
        "/model  — current AI model\n\n"
        "Screenshots bhejo — listing ready!"
    )


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🤖 Current model:\n{OPENROUTER_MODEL}\n\n"
        "Model change karne ke liye Railway → Variables mein\n"
        "OPENROUTER_MODEL update karo."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming photo messages.
    Single photo  → process immediately.
    Media group   → collect all photos, process together after 2 s.
    """
    chat_id        = update.effective_chat.id
    file_id        = update.message.photo[-1].file_id   # highest resolution
    media_group_id = update.message.media_group_id

    if media_group_id:
        # ── Media group: batch all photos first ──────────────
        if media_group_id not in _pending_groups:
            _pending_groups[media_group_id] = []
        _pending_groups[media_group_id].append(file_id)

        # Schedule exactly ONE processing task per group
        if media_group_id not in _scheduled_groups:
            _scheduled_groups.add(media_group_id)
            asyncio.create_task(
                _process_group_after_delay(media_group_id, chat_id, context)
            )

    else:
        # ── Single photo ─────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Starting BGMI Describe Bot (@ListoAIbot)")
    logger.info(f"Model: {OPENROUTER_MODEL}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("model", cmd_model))

    # Messages
    app.add_handler(MessageHandler(filters.PHOTO,                    handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,  handle_text))

    # Start polling (Railway supports long-running workers)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
