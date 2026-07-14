import os
import logging
import asyncio
import time
import json
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, MessageReactionHandler,
    ConversationHandler, ContextTypes, filters
)
from config import BOT_TOKEN, ADMIN_IDS, GROUP_ID
from database import (
    init_db, save_settings, get_active_settings,
    register_number, get_taken_numbers, get_paid_numbers,
    update_board_message_id, update_remaining_message_id,
    admin_remove_player, admin_mark_paid, mark_nekay,
    admin_set_nekay, get_nekay_numbers,
    clear_game, get_unpaid_numbers,
    get_winner_by_place, get_winners_by_place, deduct_winner_balance,
    user_owns_number, get_user_numbers, remove_number,
    change_number_type,
    save_failed_attempt, get_failed_attempts,
    get_ungreeted_winner, mark_winner_greeted,
    enable_group, disable_group, is_group_enabled,
    get_enabled_groups, register_group, add_group_admin,
    remove_group_admin, is_group_admin, get_group_admins,
    track_username, get_usernames, mark_usernames_read, clear_usernames,
    log_activity, get_activity,
    get_db_status, clear_db_data, check_and_rotate_db,
    get_recent_winners, mark_winner_sent, cleanup_old_winners,
    clear_balance_all, clear_balance_by_username,
    set_group_active, is_group_active,
    get_report, save_game_report, cleanup_old_reports,
    calculate_game_profit,
    set_warning_media, get_warning_media, get_all_warning_media, delete_warning_media,
    get_conn,
    update_countdown_settings,
    clear_prize_balance,
    all_numbers_paid,
    confirm_payment,
    reverse_winner_balance,
    delete_winner,
    add_complete_sticker, get_complete_stickers, remove_complete_sticker_by_index,
    add_prebooking_media, get_prebooking_media, remove_prebooking_media_by_index,
    get_user_balance,
    is_winner_photo_used, save_winner_photo,
    admin_set_owner,
    admin_replace_owner,
    clear_balance_by_telegram_id,
    record_message_sender,
    get_message_sender,
    cleanup_old_message_senders,
    clear_carry_balance,
    get_recent_winner_for_user,
    get_recent_winners_for_user,
    save_registrations_snapshot,
    set_name_override, get_name_override, clear_name_override,
    delete_user_fingerprint,
)
from parser import parse_numbers, format_number
from board import (
    build_board, build_remaining,
    count_remaining, get_group_start,
    build_warning, build_nekay
)
from handlers import handle_payment_photo, handle_sms_webhook, handle_winner_photo, handle_receipt_url, handle_payment_claim, handle_admin_sms_paste
from ai_fallback import get_ai_fallback, log_transaction, ensure_nvidia_text_health_task_started, clear_all_context_for_group

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
from responder import get_response, get_response_async, RESPONSES
from userbot import init_userbot_db, register_userbot_handlers, start_listeners
from userbot2 import init_userbot2_db, register_userbot2_handlers, start_winner_listeners
import random

(
    ASK_TOTAL, ASK_PER_PERSON, ASK_PRICE_FULL,
    ASK_PRICE_HALF, ASK_PRIZE_1, ASK_PRIZE_2,
    ASK_PRIZE_3, ASK_PAYMENT, ASK_GAME_RULE,
    ASK_SLOT_SYMBOL, ASK_COUNTDOWN_ENABLED,
    ASK_COUNTDOWN_MINUTES, ASK_PROFIT_PER_GAME,
    ASK_SEND_PLACE, ASK_SEND_AMOUNT, ASK_SEND_WINNER
) = range(16)

# ጨዋታ ካለቀ በኋላ (ሁሉም ✅ ሆነው live/pre-booking ሲጀምር ወይም ውጤት ሲላክ) daily
# profit ድጋሚ እንዳይቆጠር የሚከታተል set — game_id-based guard
profit_counted_games = set()

pending_ambiguous = {}
active_countdowns = {}
countdown_done = set()
nekay_active = set()
admin_nekay_games = set()
nekay_numbers = {}
msg_counter = {}

photo_processing = {}
pending_registrations = {}

handled_winner_photos = set()

low_remaining_trackers = {}

prebooking_groups = set()  # groups in silent pre-booking mode (live started, all paid)

# FIX: winner photo ከተላከ እስከ _auto_newgame ድረስ ያለው 30 ሰከንድ ክፍተት —
# board/ቀጣይ ዙር ገና ስላልተጠናቀቀ፣ በዚህ ጊዜ ውስጥ registration ቢሳካ ልክ እንደ
# prebooking_groups reaction-only (👍) ብቻ ይሆን (text reply አይላክም)
winner_pending_groups = set()
handled_video_boards = set()  # game_ids where 30s+ video board replace already done

# ============================================================
# FIX: cross-group data leak — ቦቱ 4 የተለያዩ databases ስላሉት
# (DATABASE_URLS rotation)፣ እያንዳንዱ DB የራሱ የተለየ game_settings.id
# (SERIAL) አቆጣጠር አለው። ስለዚህ ሁለት የተለያዩ groups በአጋጣሚ ተመሳሳይ game_id
# ቁጥር ሊኖራቸው ይችላል (ለምሳሌ Group A game_id=12 በ DB#1፣ Group B
# game_id=12 በ DB#2)። ከላይ ያሉት global trackers (nekay_numbers,
# nekay_active, ወዘተ) በ game_id ብቻ ስለሚቀመጡ ነበር፣ ይህ ማለት Group A's
# /nekay ውሂብ በ Group B's board ላይ ይታይ ነበር (ወይም በተቃራኒው)።
# FIX: ሁሉም እነዚህ trackers በ (group_id, game_id) combo ቁልፍ ብቻ
# እንዲቀመጡ ተቀይረዋል — _gk() helper ይህን combo ቁልፍ ይገነባል።
# ============================================================

def _gk(group_id, game_id):
    """Group-scoped key ለ in-memory trackers (cross-group game_id collision እንዳይፈጠር)"""
    return (group_id, game_id)

URGENCY_MESSAGES = [
    "ቤተሰብ ገባ ገባ በሉ🙏",
    "ቤተሰብ ጫወታውን አናድምቅ 🙏",
    "ቤተሰብ ቀሪ ቁጥሮች ብቻ አሉ ገባ ገባ በሉ 🙏",
]

NEKAY_COUNTDOWN_MESSAGE = "ቤተሰብ ትንሽ ይጠብቁ ነቃይ ላወጣ ነው 🙏"


# ============================================================
# TYPING INDICATOR
# ============================================================

async def keep_typing(bot, chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        await asyncio.sleep(4)


# ============================================================
# ALL PAID CHECK + BOARD RESEND + STICKERS
# ============================================================

async def _check_all_paid_and_resend(bot, settings: dict, group_id: int):
    game_id = settings["id"]
    if not all_numbers_paid(game_id, settings):
        return

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)

    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await bot.delete_message(chat_id=group_id, message_id=board_msg_id)
        except Exception:
            pass

    new_board = await bot.send_message(chat_id=group_id, text=board_text)
    update_board_message_id(game_id, new_board.message_id)

    stickers = get_complete_stickers()
    for sticker in stickers:
        await asyncio.sleep(2)
        try:
            await bot.send_sticker(chat_id=group_id, sticker=sticker["file_id"])
        except Exception as e:
            logging.warning(f"[CompleteSticker] Error: {e}")


# ============================================================
# INACTIVITY NOTIFICATION
# ============================================================

async def _inactivity_notify_task(bot, game_id: int, group_id: int):
    import pytz
    et_tz = pytz.timezone("Africa/Addis_Ababa")

    last_urgency_msg_id = None
    urgency_count = 0
    MAX_COUNT = 4

    try:
        while True:
            await asyncio.sleep(120)

            if _gk(group_id, game_id) not in low_remaining_trackers:
                return

            settings = get_active_settings(group_id=group_id)
            if not settings or settings["id"] != game_id:
                return

            taken = get_taken_numbers(game_id)
            remaining_count = count_remaining(settings, taken)
            is_nekay = _gk(group_id, game_id) in nekay_active

            if _gk(group_id, game_id) in active_countdowns:
                return

            if remaining_count == 0 and not is_nekay:
                return

            now_et = datetime.now(et_tz)
            hour = now_et.hour
            if hour >= 22 or hour < 8:
                continue

            if urgency_count >= MAX_COUNT:
                return

            if last_urgency_msg_id:
                try:
                    await bot.delete_message(chat_id=group_id, message_id=last_urgency_msg_id)
                except Exception:
                    pass
                last_urgency_msg_id = None

            notif = random.choice(URGENCY_MESSAGES)
            sent = await bot.send_message(chat_id=group_id, text=notif)
            last_urgency_msg_id = sent.message_id
            urgency_count += 1

            await asyncio.sleep(10)

            if _gk(group_id, game_id) not in low_remaining_trackers:
                return

            settings = get_active_settings(group_id=group_id)
            if not settings or settings["id"] != game_id:
                return

            taken = get_taken_numbers(game_id)
            remaining_count = count_remaining(settings, taken)
            is_nekay = _gk(group_id, game_id) in nekay_active

            if remaining_count == 0 and not is_nekay:
                return

            if is_nekay:
                snap = nekay_numbers.get(_gk(group_id, game_id), {})
                if snap:
                    rem_msg_id = settings.get("remaining_message_id")
                    if rem_msg_id:
                        try:
                            await bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                        except Exception:
                            pass
                    nekay_list = _build_nekay_from_snap(snap)
                    nekay_text = build_nekay(nekay_list)
                    rem_msg = await bot.send_message(chat_id=group_id, text=nekay_text)
                    update_remaining_message_id(game_id, rem_msg.message_id)
            elif 0 < remaining_count <= 7:
                remaining_text = build_remaining(settings, taken)
                rem_msg_id = settings.get("remaining_message_id")
                if rem_msg_id:
                    try:
                        await bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                    except Exception:
                        pass
                if remaining_text:
                    rem_msg = await bot.send_message(chat_id=group_id, text=remaining_text)
                    update_remaining_message_id(game_id, rem_msg.message_id)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.warning(f"[Inactivity] Error: {e}")
    finally:
        low_remaining_trackers.pop(_gk(group_id, game_id), None)


def _reset_inactivity_tracker(bot, game_id: int, group_id: int):
    key = _gk(group_id, game_id)
    existing = low_remaining_trackers.get(key)
    if existing and not existing["task"].done():
        existing["task"].cancel()
    task = asyncio.create_task(_inactivity_notify_task(bot, game_id, group_id))
    low_remaining_trackers[key] = {"task": task, "group_id": group_id}


def _stop_inactivity_tracker(game_id: int, group_id: int = None):
    key = _gk(group_id, game_id)
    existing = low_remaining_trackers.pop(key, None)
    if existing and not existing["task"].done():
        existing["task"].cancel()


# ============================================================
# ADMIN CHECK
# ============================================================

def is_main_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_admin(user_id: int, group_id: int = None) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if group_id:
        return is_group_admin(group_id, user_id)
    return False


def get_admin_group_id(user_id: int):
    enabled = get_enabled_groups()
    admin_groups = [g for g in enabled if is_admin(user_id, g["group_id"])]
    if not admin_groups:
        return None
    return admin_groups[0]["group_id"]


# ============================================================
# NEW — DEBOUNCED REMAINING/NEKAY RESEND (payment confirm → 5-second
# debounce → resend ቀሪ/ነቃይ list ከታች, no duplicates ever)
# ============================================================
_remaining_debounce_tasks = {}  # key: _gk(group_id, game_id) -> asyncio.Task


def _schedule_remaining_resend(bot, group_id: int, game_id: int):
    key = _gk(group_id, game_id)
    old_task = _remaining_debounce_tasks.get(key)
    if old_task and not old_task.done():
        old_task.cancel()
    _remaining_debounce_tasks[key] = asyncio.create_task(
        _debounced_resend_remaining_or_nekay(bot, group_id, game_id)
    )


async def _debounced_resend_remaining_or_nekay(bot, group_id: int, game_id: int):
    """
    Payment (photo/SMS) confirm → "መልካም ዕድል" ካለ በኋላ 5 ሰከንድ ምንም ተጨማሪ
    ክፍያ/እንቅስቃሴ ከሌለ ቀሪ (ወይም ነቃይ mode ገባሪ ከሆነ ነቃይ) ዝርዝር ከታች resend
    ይሁን — ነባሩን አጥፍቶ አዲስ ብቻ (duplicate በፍጹም እንዳይፈጠር)። 5 ሰከንድ ውስጥ
    ሌላ ክፍያ ቢመጣ (_schedule_remaining_resend ተጠርቶ) ይህ task ይሰረዛል
    (cancel) አዲስ 5 ሰከንድ ይጀምራል።
    """
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        return

    try:
        settings = get_active_settings(group_id=group_id)
        if not settings or settings["id"] != game_id:
            return
        _group_id = group_id or settings.get("group_id") or GROUP_ID
        key = _gk(group_id, game_id)

        if key in nekay_active:
            fresh_nekay = get_nekay_numbers(game_id)
            snap = {}
            for number, slots, is_half in fresh_nekay:
                snap[number] = 2 if is_half else 0
            nekay_numbers[key] = snap

            rem_msg_id = settings.get("remaining_message_id")
            if rem_msg_id:
                try:
                    await bot.delete_message(chat_id=_group_id, message_id=rem_msg_id)
                except Exception:
                    pass

            if snap:
                nekay_list = _build_nekay_from_snap(snap)
                nekay_text = build_nekay(nekay_list)
                new_nekay = await bot.send_message(chat_id=_group_id, text=nekay_text)
                update_remaining_message_id(game_id, new_nekay.message_id)
            else:
                update_remaining_message_id(game_id, None)
                nekay_active.discard(key)
                nekay_numbers.pop(key, None)
        else:
            taken = get_taken_numbers(game_id)
            remaining_text = build_remaining(settings, taken)
            rem_msg_id = settings.get("remaining_message_id")
            if rem_msg_id:
                try:
                    await bot.delete_message(chat_id=_group_id, message_id=rem_msg_id)
                except Exception:
                    pass
            if remaining_text:
                rem_msg = await bot.send_message(chat_id=_group_id, text=remaining_text)
                update_remaining_message_id(game_id, rem_msg.message_id)
            else:
                update_remaining_message_id(game_id, None)
    except Exception as e:
        logging.warning(f"[DebouncedResend] Error: {e}")


# ============================================================
# NEKAY PAYMENT CALLBACK
# ============================================================

async def nekay_payment_cb(bot, game_id: int, telegram_id: int, confirmed: list, group_id: int = None):
    key = _gk(group_id, game_id)
    if key not in nekay_active:
        # NEW: ነቃይ mode ባይሆንም እንኳ (ተራ ጨዋታ)፣ ክፍያ ከተረጋገጠ በኋላ ቀሪ ዝርዝር
        # 5 ሰከንድ debounce ቆይቶ resend ይሁን (ከዚህ በፊት ምንም አልነበረም — ይሄ
        # ክፍተት ነበር)
        _schedule_remaining_resend(bot, group_id, game_id)
        return

    fresh_nekay = get_nekay_numbers(game_id)
    snap = {}
    for number, slots, is_half in fresh_nekay:
        snap[number] = 2 if is_half else 0
    nekay_numbers[key] = snap

    if not snap:
        settings = get_active_settings(group_id=group_id)
        if settings:
            _group_id = group_id or settings.get("group_id") or GROUP_ID
            taken = get_taken_numbers(game_id)
            paid = get_paid_numbers(game_id)
            board_text = build_board(settings, taken, paid)
            board_msg_id = settings.get("board_message_id")
            if board_msg_id:
                try:
                    await bot.edit_message_text(chat_id=_group_id, message_id=board_msg_id, text=board_text)
                except Exception as e:
                    if "not modified" not in str(e).lower():
                        new_msg = await bot.send_message(chat_id=_group_id, text=board_text)
                        update_board_message_id(game_id, new_msg.message_id)

            rem_msg_id = settings.get("remaining_message_id")
            if rem_msg_id:
                try:
                    await bot.delete_message(chat_id=_group_id, message_id=rem_msg_id)
                except Exception:
                    pass
            update_remaining_message_id(game_id, None)
            nekay_active.discard(key)
            nekay_numbers.pop(key, None)
            _stop_inactivity_tracker(game_id, _group_id)
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    _group_id = group_id or settings.get("group_id") or GROUP_ID
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await bot.edit_message_text(chat_id=_group_id, message_id=board_msg_id, text=board_text)
        except Exception as e:
            if "not modified" not in str(e).lower():
                new_msg = await bot.send_message(chat_id=_group_id, text=board_text)
                update_board_message_id(game_id, new_msg.message_id)

    # NEW: ነቃይ ዝርዝር ወዲያውኑ ሳይሆን 5 ሰከንድ debounce ቆይቶ resend ይሁን (ሌላ
    # ክፍያ/እንቅስቃሴ በዚያ 5 ሰከንድ ውስጥ ቢመጣ timer ይታደሳል)
    _schedule_remaining_resend(bot, group_id, game_id)

    fresh = get_active_settings(group_id=_group_id)
    if fresh:
        await _check_all_paid_and_resend(bot, fresh, _group_id)


def _increment_counter(group_id: int) -> bool:
    msg_counter[group_id] = msg_counter.get(group_id, 0) + 1
    if msg_counter[group_id] >= 4:
        msg_counter[group_id] = 0
        return True
    return False


# ============================================================
# FIX #6: fire-and-forget helpers — reply/reaction Telegram API
# call ን board edit ከመጀመሩ በፊት እንዲጠብቅ ላለማድረግ (ቀድሞ sequential ስለነበር
# board edit ይዘገይ ነበር)። ውጤቱን አንጠብቅም፣ ስህተት ቢፈጠር log ብቻ እናደርጋለን።
# ============================================================

async def _safe_reply_text(msg, text: str):
    try:
        await msg.reply_text(text)
    except Exception as e:
        logging.warning(f"[SafeReply] Error: {e}")


async def _safe_set_reaction(bot, chat_id: int, message_id: int, emoji: str = "👍"):
    try:
        try:
            from telegram import ReactionTypeEmoji
            reaction = [ReactionTypeEmoji(emoji=emoji)]
        except ImportError:
            reaction = [emoji]
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id, reaction=reaction,
        )
    except Exception as e:
        logging.warning(f"[SafeReaction] Error: {e}")


# ============================================================
# FIX #4: admin confirmation messages ("✅ ...") ከተላኩ ከ1.5-2 ሰከንድ
# በኋላ በራሳቸው ይጠፉ (admin ካየ በቂ ነው)።
# ============================================================

async def _send_temp_admin_message(bot, chat_id: int, text: str, delay: float = 1.75):
    try:
        sent = await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logging.warning(f"[TempAdminMsg] Send error: {e}")
        return None

    async def _delete_later():
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        except Exception:
            pass

    asyncio.create_task(_delete_later())
    return sent


# ============================================================
# NEW — winner "🔥 reaction" balance-clear feature: admin puts a native
# 🔥 reaction on any message previously sent BY a recent winner (in the
# group) → that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched — this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message — only who reacted and which
# chat/message_id. So we keep a small bounded in-memory cache mapping
# (chat_id, message_id) -> (telegram_id, user_name) for recent group
# text messages, populated (read-only/additive) inside
# handle_group_message. This does not alter any existing behavior.
# ============================================================
# ============================================================
# NEW — winner "🔥 reaction" balance-clear feature: admin puts a native
# 🔥 reaction on any message previously sent BY a recent winner (in the
# group) → that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched — this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message — only who reacted and which
# chat/message_id. This mapping (chat_id, message_id) -> telegram_id is
# stored in the DB (message_senders table, via database.py) rather than
# an in-memory cache, so it survives bot restarts and scales correctly
# across 100,000+ users / many groups. Recording (inside
# handle_group_message) is additive and does not alter any existing
# behavior; cleanup happens on new-game start (clear_game) and via the
# periodic cleanup_old_message_senders() safety net.
# ============================================================

def _record_group_message(chat_id: int, message_id: int, telegram_id: int, user_name: str):
    try:
        record_message_sender(chat_id, message_id, telegram_id, user_name)
    except Exception as e:
        logging.warning(f"[RecordMsgSender] Error: {e}")


# ============================================================
# NEW — "እሺ/eshi NUM[+SLOT][✅] ..." admin replacement feature: bot's
# earlier "ተይዞብሃል"/booking_taken rejection reply message_id ተመዝግቦ
# ይቀመጣል፣ ስለዚህ admin ተጠቃሚው ኦርጅናል message ላይ reply አድርጎ "እሺ ..." ሲል
# ያንን ነባር rejection message ማጥፋት ይቻላል።
# key: (group_id, user_message_id) -> bot_reply_message_id
# ============================================================
_taken_rejection_msgs = {}
_TAKEN_REJECTION_CACHE_MAX = 500


async def _safe_reply_text_and_track(msg, text: str, group_id: int):
    try:
        sent = await msg.reply_text(text)
        key = (group_id, msg.message_id)
        _taken_rejection_msgs[key] = sent.message_id
        if len(_taken_rejection_msgs) > _TAKEN_REJECTION_CACHE_MAX:
            oldest_key = next(iter(_taken_rejection_msgs))
            _taken_rejection_msgs.pop(oldest_key, None)
    except Exception as e:
        logging.warning(f"[SafeReplyTrack] Error: {e}")


def _build_nekay_from_snap(snap: dict) -> list:
    result = []
    for number, slot in sorted(snap.items()):
        # 0 = ሙሉ nekay (full)፣ 2/-1/-2 ሁሉም half/slot-specific nekay ናቸው
        is_half = (slot != 0)
        result.append((number, is_half))
    return result


# ============================================================
# COUNTDOWN TASK
# ============================================================

async def _countdown_task(bot, game_id: int, group_id: int, warn_seconds: int = 120):
    countdown_mins = warn_seconds / 60

    media = get_warning_media(countdown_mins)
    warn_msg = None

    try:
        if media:
            mtype = media["media_type"]
            fid = media["file_id"]
            if mtype == "video":
                warn_msg = await bot.send_video(chat_id=group_id, video=fid)
            elif mtype == "animation":
                warn_msg = await bot.send_animation(chat_id=group_id, animation=fid)
            elif mtype == "sticker":
                warn_msg = await bot.send_sticker(chat_id=group_id, sticker=fid)
            else:
                warn_msg = await bot.send_photo(chat_id=group_id, photo=fid)
        else:
            warn_msg = await bot.send_message(chat_id=group_id, text=build_warning())
    except Exception:
        warn_msg = await bot.send_message(chat_id=group_id, text=build_warning())

    await asyncio.sleep(warn_seconds)

    unpaid = get_unpaid_numbers(game_id)
    if unpaid:
        if _gk(group_id, game_id) in admin_nekay_games:
            active_countdowns.pop(_gk(group_id, game_id), None)
            return

        snap = {}
        for number, slots, is_half in unpaid:
            snap[number] = 2 if is_half else 0
        nekay_numbers[_gk(group_id, game_id)] = snap

        for number, slots, is_half in unpaid:
            mark_nekay(game_id, number)

        nekay_list = _build_nekay_from_snap(snap)
        nekay_text = build_nekay(nekay_list)

        nekay_sent = await bot.send_message(chat_id=group_id, text=nekay_text)

        nekay_active.add(_gk(group_id, game_id))
        update_remaining_message_id(game_id, nekay_sent.message_id if nekay_sent else None)

    active_countdowns.pop(_gk(group_id, game_id), None)


# ============================================================
# /start
# ============================================================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot ተሰናድቷል!")


# ============================================================
# SETGAME CONVERSATION
# ============================================================

async def setgame_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        await update.message.reply_text("❌ Admin ብቻ ነው!")
        return ConversationHandler.END
    ctx.user_data["setup_group_id"] = group_id
    await update.message.reply_text("🎮 ስንት ቁጥሮች አሉ? (ለምሳሌ: 100)")
    return ASK_TOTAL


async def ask_total(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["total_numbers"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")
        return ASK_TOTAL
    await update.message.reply_text("👥 ለ1 ሰው ስንት ቁጥሮች? (ለምሳሌ: 5)")
    return ASK_PER_PERSON


async def ask_per_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["numbers_per_person"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")
        return ASK_PER_PERSON
    await update.message.reply_text("💰 ሙሉ ዋጋ ስንት ብር?")
    return ASK_PRICE_FULL


async def ask_price_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["price_full"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")
        return ASK_PRICE_FULL
    await update.message.reply_text("💳 ግማሽ ዋጋ አለ? (ቁጥር ጻፍ ወይም 'አይደለም')")
    return ASK_PRICE_HALF


async def ask_price_half(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["አይደለም", "aydelem", "no", "የለም"]:
        ctx.user_data["price_half"] = None
    else:
        try:
            ctx.user_data["price_half"] = int(text)
        except ValueError:
            await update.message.reply_text("❌ ቁጥር ወይም 'አይደለም' ጻፍ!")
            return ASK_PRICE_HALF
    await update.message.reply_text("🥇 1ኛ ሽልማት ስንት ብር?")
    return ASK_PRIZE_1


async def ask_prize_1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["prize_1st"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")
        return ASK_PRIZE_1
    await update.message.reply_text("🥈 2ኛ ሽልማት? (ከሌለ 'አይደለም')")
    return ASK_PRIZE_2


async def ask_prize_2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["አይደለም", "aydelem", "no", "የለም"]:
        ctx.user_data["prize_2nd"] = None
    else:
        try:
            ctx.user_data["prize_2nd"] = int(text)
        except ValueError:
            await update.message.reply_text("❌ ቁጥር ወይም 'አይደለም' ጻፍ!")
            return ASK_PRIZE_2
    await update.message.reply_text("🥉 3ኛ ሽልማት? (ከሌለ 'አይደለም')")
    return ASK_PRIZE_3


async def ask_prize_3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["አይደለም", "aydelem", "no", "የለም"]:
        ctx.user_data["prize_3rd"] = None
    else:
        try:
            ctx.user_data["prize_3rd"] = int(text)
        except ValueError:
            await update.message.reply_text("❌ ቁጥር ወይም 'አይደለም' ጻፍ!")
            return ASK_PRIZE_3
    await update.message.reply_text("💳 Payment info ጻፍ (CBE, Telebirr...):")
    return ASK_PAYMENT


async def ask_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["payment_info"] = update.message.text.strip()
    await update.message.reply_text(
        "📌 Game rule ጻፍ (board ላይ ከላይ ይታያል)\n"
        "ወይም 'skip' ካልፈለጋቸህ"
    )
    return ASK_GAME_RULE


async def ask_game_rule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "አይደለም", "no", "የለም"]:
        ctx.user_data["game_rule"] = None
    else:
        ctx.user_data["game_rule"] = text
    await update.message.reply_text(
        "🔣 Slot symbol ምረጥ\n"
        "ለምሳሌ: # ⭐ 🎯 🔥 ወይም ባዶ (skip)\n"
        "Default: #"
    )
    return ASK_SLOT_SYMBOL


async def ask_slot_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "default", "#"]:
        ctx.user_data["slot_symbol"] = "#"
    elif text.lower() in ["ባዶ", "none", "empty", ""]:
        ctx.user_data["slot_symbol"] = ""
    else:
        ctx.user_data["slot_symbol"] = text
    await update.message.reply_text(
        "⏳ ተነቃይ countdown አለ?\n"
        "(አዎ / አይደለም)"
    )
    return ASK_COUNTDOWN_ENABLED


async def ask_countdown_enabled(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    yes = text in ["አዎ", "awo", "yes", "aha", "አዎን"]
    ctx.user_data["countdown_enabled"] = yes

    if yes:
        await update.message.reply_text(
            "⏱️ ስንት ደቂቃ?\n"
            "0.5 = 30 ሰከንድ\n"
            "1 = 1 ደቂቃ\n"
            "2 = 2 ደቂቃ\n"
            "5 = 5 ደቂቃ\n"
            "10 = 10 ደቂቃ\n"
            "(0.5 እስከ 10)"
        )
        return ASK_COUNTDOWN_MINUTES
    else:
        ctx.user_data["countdown_minutes"] = 0
        return await ask_profit_per_game_prompt(update, ctx)


async def ask_countdown_minutes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        mins = float(update.message.text.strip())
        if mins < 0.5 or mins > 10:
            raise ValueError
        ctx.user_data["countdown_minutes"] = mins
    except ValueError:
        await update.message.reply_text("❌ 0.5 እስከ 10 ብቻ ጻፍ!")
        return ASK_COUNTDOWN_MINUTES
    return await ask_profit_per_game_prompt(update, ctx)


async def ask_profit_per_game_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 ከ1 ጨዋታ ስንት ብር profit ያገኛሉ? (ለምሳሌ: 300)"
    )
    return ASK_PROFIT_PER_GAME


async def ask_profit_per_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["profit_per_game"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ! (ለምሳሌ: 300)")
        return ASK_PROFIT_PER_GAME
    return await _finish_setgame(update, ctx)


async def _finish_setgame(update, ctx):
    setup_group_id = ctx.user_data.get("setup_group_id")

    # NEW: /newgame ራሱ ከዚህ በፊት game switch ሲያደርግ (clear_game + in-memory
    # nekay/countdown state ማጽዳት) የሚያደርገውን ተመሳሳይ cleanup — /setgame ግን
    # ከዚህ በፊት ይህን አያደርግም ነበር (ወጥነት ማጣት፣ stale winners/nekay state
    # እንዲቀጥል ምክንያት ሆኖ ነበር)። አዲሱን game_id ከመፍጠሩ በፊት የቆየውን ያጸዳል።
    old_settings = get_active_settings(group_id=setup_group_id)
    if old_settings:
        old_group_id = setup_group_id or old_settings.get("group_id") or GROUP_ID
        try:
            clear_prize_balance(old_group_id)
            clear_carry_balance(old_group_id)
            clear_game(old_settings["id"])
        except Exception as e:
            logging.warning(f"[SetGame] old-game cleanup error: {e}")
        old_key = _gk(old_group_id, old_settings["id"])
        nekay_active.discard(old_key)
        admin_nekay_games.discard(old_key)
        active_countdowns.pop(old_key, None)
        nekay_numbers.pop(old_key, None)
        countdown_done.discard(old_key)
        handled_video_boards.discard(old_key)
        _stop_inactivity_tracker(old_settings["id"], old_group_id)
        try:
            clear_all_context_for_group(old_group_id)
        except Exception:
            pass

    game_id = save_settings(ctx.user_data, group_id=setup_group_id)

    settings = get_active_settings(group_id=setup_group_id)
    taken = {}
    board_text = build_board(settings, taken)

    target = setup_group_id or GROUP_ID
    if target:
        msg = await ctx.bot.send_message(chat_id=target, text=board_text)
        update_board_message_id(game_id, msg.message_id)

    countdown_status = "✅ On" if ctx.user_data.get("countdown_enabled") else "❌ Off"
    mins = ctx.user_data.get("countdown_minutes", 0)
    await update.message.reply_text(
        f"✅ Settings ተቀምጧል!\n"
        f"Game ID: {game_id}\n"
        f"⏳ Countdown: {countdown_status}"
        + (f" ({mins} ደቂቃ)" if ctx.user_data.get("countdown_enabled") else "")
    )
    return ConversationHandler.END


async def cancel_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup ተሰርዟል።")
    return ConversationHandler.END


# ============================================================
# SETCOUNTDOWN COMMAND
# ============================================================

async def handle_setcountdown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != "private":
        if not is_admin(user_id, update.effective_chat.id):
            return
        group_id = update.effective_chat.id
    else:
        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ ምሳሌ: /setcountdown 2\n"
            "0 = countdown አጥፋ\n"
            "0.5, 1, 2, 5, 10 = ደቂቃ"
        )
        return

    try:
        mins = float(parts[1])
        if mins != 0 and (mins < 0.5 or mins > 10):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ 0 ወይም 0.5 እስከ 10 ብቻ ጻፍ!")
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    enabled = mins > 0
    update_countdown_settings(settings["id"], enabled, mins if enabled else 0)

    if enabled:
        await update.message.reply_text(f"✅ Countdown {mins} ደቂቃ ተቀምጧል!")
    else:
        await update.message.reply_text("✅ Countdown ጠፍቷል!")


# ============================================================
# /showslots COMMAND
# ============================================================

async def handle_showslots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != "private":
        if not is_admin(user_id, update.effective_chat.id):
            return
        group_id = update.effective_chat.id
    else:
        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await update.message.reply_text(
            "❌ ምሳሌ: /showslots on\n"
            "       /showslots off\n"
            "sub-slots ላይ ስም ያሳያል / ያጠፋል"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    enabled = parts[1].lower() == "on"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE game_settings SET show_all_slots=%s WHERE id=%s",
        (enabled, settings["id"])
    )
    conn.commit()
    cur.close()
    conn.close()

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        taken = get_taken_numbers(fresh["id"])
        paid = get_paid_numbers(fresh["id"])
        board_text = build_board(fresh, taken, paid)
        board_msg_id = fresh.get("board_message_id")
        if board_msg_id:
            try:
                await ctx.bot.edit_message_text(
                    chat_id=group_id, message_id=board_msg_id, text=board_text
                )
            except Exception as e:
                if "not modified" not in str(e).lower():
                    new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    update_board_message_id(fresh["id"], new_msg.message_id)
        else:
            new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            update_board_message_id(fresh["id"], new_msg.message_id)

    status = "✅ On" if enabled else "❌ Off"
    await update.message.reply_text(f"Sub-slots display: {status}")


# ============================================================
# MANUAL /nekay COMMAND
# ============================================================

async def handle_nekay_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ ምሳሌ: /nekay 5 10+ 15 21\n"
            "+ = ግማሽ (ለምሳሌ 10+)\n"
            "5+1 = ቁጥር 5 slot 1 ብቻ\n"
            "ቀድሞ የነበረውን ነቃይ ሁሉ ይተካል"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    game_id = settings["id"]
    per_person = settings["numbers_per_person"]
    taken = get_taken_numbers(game_id)

    numbers = []   # (num, is_half, slot_only) — slot_only=None means all slots
    errors = []

    for part in parts[1:]:
        # NUM+SLOT pattern (ለምሳሌ 5+1 ወይም 5+2)
        import re as _re
        slot_match = _re.match(r'^(\d+)\+(\d+)$', part)
        if slot_match:
            num = int(slot_match.group(1))
            slot = int(slot_match.group(2))
            # ✅ FIX: 1-5 ቡድን ቢሆን (numbers_per_person>1)፣ ማንኛውም ቁጥር
            # በዚያ ቡድን ውስጥ (ለምሳሌ 4) → group's first number (1) ይሆናል፣
            # ምክንያቱም DB ላይ የተመዘገበው በ group start ብቻ ነው
            actual_num = get_group_start(num, per_person) if per_person > 1 else num
            if actual_num < 1 or actual_num > settings["total_numbers"]:
                errors.append(part)
                continue
            # ያ slot exist ያረጋግጥ
            slots_for_num = taken.get(actual_num, [])
            slot_exists = any(s[2] == slot for s in slots_for_num)
            if not slot_exists:
                errors.append(part)
                continue
            numbers.append((actual_num, True, slot))
            continue

        # NUM+ or NUM pattern
        is_half = part.endswith("+")
        part_clean = part.rstrip("+")
        try:
            num = int(part_clean)
        except ValueError:
            errors.append(part)
            continue
        # ✅ FIX: እዚህም ተመሳሳይ group-start mapping
        actual_num = get_group_start(num, per_person) if per_person > 1 else num
        if actual_num < 1 or actual_num > settings["total_numbers"]:
            errors.append(part)
            continue

        # NUM+ ሲሆን 2 slots ካለ አይሰራም
        if is_half:
            slots_for_num = taken.get(actual_num, [])
            if len(slots_for_num) > 1:
                errors.append(part + " (2 slots አለ — 5+1 ወይም 5+2 ጠቀስ)")
                continue

        numbers.append((actual_num, is_half, None))

    if not numbers:
        await update.message.reply_text("❌ ትክክለኛ ቁጥር አልተገኘም!")
        return

    # DB ላይ nekay ያደርጋል — slot_only ካለ ያ slot ብቻ
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE registrations SET is_nekay=FALSE WHERE game_id=%s AND is_nekay=TRUE", (game_id,))

    snap = {}
    for num, is_half, slot_only in numbers:
        if slot_only is not None:
            # slot ብቻ
            cur.execute("""
                UPDATE registrations SET is_nekay=TRUE
                WHERE game_id=%s AND number=%s AND slot=%s
            """, (game_id, num, slot_only))
            # FIX: የትኛው slot እንደሆነ ተለይቶ ይቀመጥ (-1 = slot 1, -2 = slot 2)
            # ስለዚህ user ሲይዝ ትክክለኛው slot force-overwrite ይደረግለታል
            snap[num] = -1 if slot_only == 1 else -2
        else:
            cur.execute("""
                UPDATE registrations SET is_nekay=TRUE
                WHERE game_id=%s AND number=%s
            """, (game_id, num))
            snap[num] = 2 if is_half else 0

    conn.commit()
    cur.close()
    conn.close()

    nekay_numbers[_gk(group_id, game_id)] = snap
    nekay_active.add(_gk(group_id, game_id))
    admin_nekay_games.add(_gk(group_id, game_id))

    # FIX: admin's own "/nekay ..." message ወዲያውኑ ይጠፋ (ልክ እንደ #/ እና #name)
    try:
        await ctx.bot.delete_message(chat_id=group_id, message_id=update.message.message_id)
    except Exception:
        pass

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
        except Exception:
            pass

    nekay_list = _build_nekay_from_snap(snap)
    nekay_text = build_nekay(nekay_list)
    new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
    update_remaining_message_id(game_id, new_nekay.message_id)

    reg_list = ", ".join(
        format_number(n) + (f"+{slot}" if slot else ("+" if h else ""))
        for n, h, slot in numbers
    )
    msg = f"✅ ነቃይ ተቀምጧል: {reg_list}"
    if errors:
        msg += f"\n❌ ያልተቀበለ: {', '.join(errors)}"
    # FIX #4: admin confirmation message ከ1.5-2 ሰከንድ በኋላ ራሱ ይጠፋል
    await _send_temp_admin_message(ctx.bot, group_id, msg)


# ============================================================
# COMPLETE STICKER COMMANDS
# ============================================================

async def handle_setcompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    ctx.user_data["awaiting_complete_sticker"] = True
    await update.message.reply_text("✅ አሁን sticker ይላኩ (ሁሉም group ላይ ይሰራል)")


async def handle_listcompletestickers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    stickers = get_complete_stickers()
    if not stickers:
        await update.message.reply_text("📋 Complete sticker የለም።")
        return
    lines = ["📋 Complete Stickers:\n"]
    for i, s in enumerate(stickers, 1):
        added = s["added_at"].strftime("%m/%d %H:%M") if s["added_at"] else "?"
        lines.append(f"{i}. file_id: {s['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removecompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /removecompletesticker 1")
        return
    try:
        index = int(parts[1])
        success = remove_complete_sticker_by_index(index)
        if success:
            await update.message.reply_text(f"✅ Sticker #{index} ጠፋ!")
        else:
            await update.message.reply_text(f"❌ #{index} አልተገኘም!")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")


async def handle_complete_sticker_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    if not ctx.user_data.get("awaiting_complete_sticker"):
        return
    msg = update.message
    if not msg.sticker:
        await msg.reply_text("❌ Sticker ብቻ ይላኩ!")
        return
    file_id = msg.sticker.file_id
    add_complete_sticker(file_id)
    ctx.user_data.pop("awaiting_complete_sticker", None)
    await msg.reply_text("✅ Complete sticker ተቀምጧል!")


# ============================================================
# PRE-BOOKING MEDIA COMMANDS
# ============================================================

async def handle_setprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    ctx.user_data["awaiting_prebooking_media"] = True
    await update.message.reply_text(
        "✅ አሁን photo/video/sticker ይላኩ (pre-booking ሲጀምር group ላይ ይላካል)\n"
        "ብዙ ጊዜ ሊጨምሩ ይችላሉ — ሁሉም በቅደም ተከተል ይላካሉ።"
    )


async def handle_listprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    medias = get_prebooking_media()
    if not medias:
        await update.message.reply_text("📋 Pre-booking media የለም።")
        return
    lines = ["📋 Pre-Booking Media:\n"]
    for i, m in enumerate(medias, 1):
        added = m["added_at"].strftime("%m/%d %H:%M") if m["added_at"] else "?"
        lines.append(f"{i}. {m['media_type']} — {m['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removeprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /removeprebookingmedia 1")
        return
    try:
        index = int(parts[1])
        success = remove_prebooking_media_by_index(index)
        if success:
            await update.message.reply_text(f"✅ Pre-booking media #{index} ጠፋ!")
        else:
            await update.message.reply_text(f"❌ #{index} አልተገኘም!")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")


async def handle_prebooking_media_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    if not ctx.user_data.get("awaiting_prebooking_media"):
        return
    msg = update.message
    file_id = None
    media_type = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        media_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        media_type = "video"
    elif msg.animation:
        file_id = msg.animation.file_id
        media_type = "animation"
    elif msg.sticker:
        file_id = msg.sticker.file_id
        media_type = "sticker"
    elif msg.document:
        file_id = msg.document.file_id
        media_type = "video"

    if not file_id:
        await msg.reply_text("❌ Photo/Video/Sticker ብቻ ይላኩ!")
        return

    add_prebooking_media(file_id, media_type)
    ctx.user_data.pop("awaiting_prebooking_media", None)
    await msg.reply_text(f"✅ Pre-booking media ተቀምጧል! ({media_type})\nተጨማሪ ለማስቀመጥ /setprebookingmedia ድጋሚ ጥቀስ።")


# ============================================================
# GROUP MESSAGE HANDLER
# ============================================================

async def handle_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    user = msg.from_user
    user_id = user.id
    user_name = user.first_name or "Unknown"
    text = msg.text.strip()
    group_id = update.effective_chat.id

    # NEW: winner-🔥-reaction feature — this message's sender ተመዝግቦ ይቀመጣል
    # (DB write ነው፣ event loop እንዳይዘገይ background thread ላይ fire-and-forget
    # ሆኖ ይሰራል፣ ምንም ነባር ሎጂክ አይነካም)
    asyncio.create_task(asyncio.to_thread(_record_group_message, group_id, msg.message_id, user_id, user_name))

    if not is_group_enabled(group_id):
        return

    if not is_group_active(group_id):
        return

    if is_admin(user_id, group_id):
        return

    if user.username:
        try:
            track_username(group_id, user.username)
        except Exception:
            pass

    try:
        log_activity(group_id, messages=1)
    except Exception:
        pass

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(ctx.bot, group_id, stop_typing))

    try:
        await _handle_group_message_inner(update, ctx, msg, user_id, user_name, text, group_id)
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


async def _handle_group_message_inner(update, ctx, msg, user_id, user_name, text, group_id):
    if user_id in pending_ambiguous:
        await handle_ambiguous_reply(update, ctx, text, user_id, user_name, group_id)
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    game_id = settings["id"]

    import re as _re_url
    _url_pattern = _re_url.compile(r'https?://[^\s\u1200-\u137F]+')
    _urls_in_msg = _url_pattern.findall(text)

    # ✅ ማናቸውም URL → fetch ይሞክራል (domain check የለም)
    for _url in _urls_in_msg:
        async def _nekay_cb_url(confirmed):
            await nekay_payment_cb(ctx.bot, game_id, user_id, confirmed, group_id=group_id)
        await handle_receipt_url(ctx.bot, msg, _url, user_id, group_id, nekay_cb=_nekay_cb_url)
        return

    if get_ungreeted_winner(game_id, user_id):
        mark_winner_greeted(user_id)
        await msg.reply_text(random.choice(RESPONSES["winner_greeting"]))

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    snap = nekay_numbers.get(_gk(group_id, game_id), {})
    nekay_list = _build_nekay_from_snap(snap)
    remaining = count_remaining(settings, taken)

    cd_data = active_countdowns.get(_gk(group_id, game_id))
    if cd_data and isinstance(cd_data, dict):
        elapsed = time.time() - cd_data["start"]
        countdown_seconds = max(0, int(cd_data["warn_secs"] - elapsed))
    else:
        countdown_seconds = 0

    user_numbers = get_user_numbers(game_id, user_id)
    recent_winners = get_recent_winners(group_id, hours=24)

    user_balance = get_user_balance(group_id, user_id)
    user_failed_attempts = get_failed_attempts(game_id, user_id)

    resp = await get_response_async(
        text=text,
        settings=settings,
        taken=taken,
        paid=paid,
        nekay_list=nekay_list,
        remaining_count=remaining,
        countdown_seconds=countdown_seconds,
        user_name=user_name,
        user_id=user_id,
        user_numbers=user_numbers,
        recent_winners=recent_winners,
        user_balance=user_balance,
        failed_attempts=user_failed_attempts,
    )

    if resp.get("payment_claim"):
        await handle_payment_claim(ctx.bot, msg, user_id, group_id, settings=settings)
        return

    if resp.get("my_numbers_query"):
        from responder import _format_my_numbers, RESPONSES as RESP
        if not user_numbers:
            await msg.reply_text(random.choice(RESP["my_numbers_none"]))
        else:
            numbers_text = _format_my_numbers(user_numbers)
            if numbers_text:
                await msg.reply_text(
                    random.choice(RESP["my_numbers_show"]).format(numbers_text=numbers_text)
                )
            else:
                await msg.reply_text(random.choice(RESP["my_numbers_none"]))
        return

    if resp.get("number_owner_query") is not None:
        return

    if resp.get("cancel_number"):
        num = resp["cancel_number"]
        if not user_owns_number(game_id, user_id, num):
            await msg.reply_text("ቁጥሩ የእርስዎ አይደለም 🙏")
            return
        removed = remove_number(game_id, user_id, num)
        if removed:
            if resp["reply"]:
                await msg.reply_text(resp["reply"])
            try:
                price_full_r = float(settings.get("price_full") or 0)
                log_transaction(
                    group_id=group_id, game_id=game_id,
                    telegram_id=user_id, amount=price_full_r,
                    reason="number_removed_refund", number=num,
                    done_by="user",
                )
            except Exception as _log_err:
                logging.warning(f"[log_transaction] Error: {_log_err}")
            if _gk(group_id, game_id) in nekay_active:
                fresh_nekay = get_nekay_numbers(game_id)
                rebuilt_snap = {}
                for n, slots, is_half in fresh_nekay:
                    rebuilt_snap[n] = 2 if is_half else 0
                nekay_numbers[_gk(group_id, game_id)] = rebuilt_snap
            fresh = get_active_settings(group_id=group_id)
            if fresh:
                await _refresh_board(ctx, fresh, group_id)
                if _gk(group_id, game_id) in nekay_active:
                    snap2 = nekay_numbers.get(_gk(group_id, game_id), {})
                    rem_msg_id = fresh.get("remaining_message_id")
                    if rem_msg_id:
                        try:
                            await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                        except Exception:
                            pass
                    if snap2:
                        nekay_list2 = _build_nekay_from_snap(snap2)
                        nekay_text2 = build_nekay(nekay_list2)
                        new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text2)
                        update_remaining_message_id(game_id, new_nekay.message_id)
                    else:
                        update_remaining_message_id(game_id, None)
                        nekay_active.discard(_gk(group_id, game_id))
                        nekay_numbers.pop(_gk(group_id, game_id), None)
                fresh2 = get_active_settings(group_id=group_id)
                if fresh2:
                    await _check_all_paid_and_resend(ctx.bot, fresh2, group_id)
        return

    if resp.get("type_change"):
        tc = resp["type_change"]
        target = tc["target"]
        numbers = tc["numbers"]

        price_full = float(settings.get("price_full") or 0)
        price_half = float(settings.get("price_half") or 0)
        parse_result = parse_numbers(text, price_full=price_full, price_half=price_half)
        parsed_name = None
        if parse_result and parse_result["numbers"]:
            parsed_name = parse_result["numbers"][0][2]

        for num in numbers:
            actual_num = get_group_start(num, settings["numbers_per_person"]) \
                if settings["numbers_per_person"] > 1 else num

            if actual_num not in taken:
                is_half = (target == "half")
                await process_registration(
                    ctx, settings,
                    [(actual_num, is_half, parsed_name)],
                    user_id, user_name, group_id, msg,
                    skip_board_update=True
                )
            elif not user_owns_number(game_id, user_id, actual_num):
                await msg.reply_text(f"{actual_num:02d} የእርስዎ ቁጥር አይደለም 🙏")
            else:
                if parsed_name:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE registrations SET user_name=%s
                        WHERE game_id=%s AND number=%s AND user_id=%s
                    """, (parsed_name, game_id, actual_num, user_id))
                    conn.commit()
                    cur.close()
                    conn.close()

                result_tc = change_number_type(game_id, user_id, actual_num, target)
                if result_tc["status"] == "conflict":
                    await msg.reply_text(
                        random.choice(RESPONSES["type_change_conflict"]).format(num=f"{actual_num:02d}")
                    )
                elif result_tc["status"] == "no_change":
                    pass
                elif resp["reply"]:
                    await msg.reply_text(resp["reply"])

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            fresh_taken = get_taken_numbers(game_id)
            fresh_paid = get_paid_numbers(game_id)
            fresh_remaining = count_remaining(fresh, fresh_taken)
            fresh_board = build_board(fresh, fresh_taken, fresh_paid)
            fresh_board_msg_id = fresh.get("board_message_id")

            should_resend_tc = _increment_counter(group_id)

            if _gk(group_id, game_id) in nekay_active:
                if should_resend_tc:
                    if fresh_board_msg_id:
                        try:
                            await ctx.bot.delete_message(chat_id=group_id, message_id=fresh_board_msg_id)
                        except Exception:
                            pass
                    new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                    update_board_message_id(game_id, new_msg.message_id)
                else:
                    if fresh_board_msg_id:
                        try:
                            await ctx.bot.edit_message_text(
                                chat_id=group_id, message_id=fresh_board_msg_id, text=fresh_board
                            )
                        except Exception as e:
                            if "not modified" in str(e).lower():
                                pass
                            else:
                                try:
                                    await ctx.bot.delete_message(chat_id=group_id, message_id=fresh_board_msg_id)
                                except Exception:
                                    pass
                                new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                                update_board_message_id(game_id, new_msg.message_id)
                    else:
                        new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                        update_board_message_id(game_id, new_msg.message_id)

                snap_fresh = nekay_numbers.get(_gk(group_id, game_id), {})
                for num in numbers:
                    actual_num = get_group_start(num, fresh["numbers_per_person"]) \
                        if fresh["numbers_per_person"] > 1 else num
                    if actual_num in snap_fresh:
                        if target == "full":
                            del snap_fresh[actual_num]
                        elif target == "half" and snap_fresh[actual_num] == 0:
                            snap_fresh[actual_num] = 2
                nekay_numbers[_gk(group_id, game_id)] = snap_fresh

                rem_msg_id = fresh.get("remaining_message_id")
                if rem_msg_id:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                    except Exception:
                        pass
                if snap_fresh:
                    nekay_list_f = _build_nekay_from_snap(snap_fresh)
                    nekay_text_f = build_nekay(nekay_list_f)
                    new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text_f)
                    update_remaining_message_id(game_id, new_nekay.message_id)
                else:
                    update_remaining_message_id(game_id, None)
                    nekay_active.discard(_gk(group_id, game_id))
                    nekay_numbers.pop(_gk(group_id, game_id), None)
                    _stop_inactivity_tracker(game_id, group_id)
            elif fresh_remaining <= 7 and should_resend_tc:
                if fresh_board_msg_id:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=fresh_board_msg_id)
                    except Exception:
                        pass
                new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                update_board_message_id(game_id, new_msg.message_id)
            else:
                if fresh_board_msg_id:
                    try:
                        await ctx.bot.edit_message_text(
                            chat_id=group_id, message_id=fresh_board_msg_id, text=fresh_board
                        )
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                            update_board_message_id(game_id, new_msg.message_id)
                else:
                    new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                    update_board_message_id(game_id, new_msg.message_id)

            if _gk(group_id, game_id) not in nekay_active:
                if fresh_remaining <= 7:
                    await _send_remaining(ctx, fresh, group_id)
                    _reset_inactivity_tracker(ctx.bot, game_id, group_id)

                if fresh_remaining == 0 and _gk(group_id, game_id) not in active_countdowns and _gk(group_id, game_id) not in countdown_done and _gk(group_id, game_id) not in admin_nekay_games:
                    _stop_inactivity_tracker(game_id, group_id)
                    countdown_enabled = fresh.get("countdown_enabled", True)
                    if countdown_enabled:
                        countdown_mins = fresh.get("countdown_minutes") or 2
                        warn_secs = int(float(countdown_mins) * 60)
                        task = asyncio.create_task(_countdown_task(ctx.bot, game_id, group_id, warn_seconds=warn_secs))
                        active_countdowns[_gk(group_id, game_id)] = {"task": task, "start": time.time(), "warn_secs": warn_secs}
                        countdown_done.add(_gk(group_id, game_id))

            fresh2 = get_active_settings(group_id=group_id)
            if fresh2:
                await _check_all_paid_and_resend(ctx.bot, fresh2, group_id)
        return

    if resp.get("change_number"):
        ch = resp["change_number"]
        from_num = ch["from"]
        to_num = ch["to"]

        if not user_owns_number(game_id, user_id, from_num):
            await msg.reply_text(f"{from_num:02d} የእርስዎ ቁጥር አይደለም 🙏")
            return
        if to_num in paid:
            await msg.reply_text(f"{to_num:02d} ✅ ተከፍሏል መቀየር አይቻልም 🙏")
            return
        if to_num in taken:
            await msg.reply_text(f"{to_num:02d} ተይዟል ቤተሰብ ሌላ ምረጥ 🙏")
            return

        removed = remove_number(game_id, user_id, from_num)
        if removed:
            result = register_number(game_id, user_id, user_name, to_num, False)
            if result in ("registered", "registered_half"):
                if resp["reply"]:
                    await msg.reply_text(resp["reply"])
                if _gk(group_id, game_id) in nekay_numbers:
                    snap3 = nekay_numbers.get(_gk(group_id, game_id), {})
                    if from_num in snap3:
                        del snap3[from_num]
                    nekay_numbers[_gk(group_id, game_id)] = snap3
                fresh = get_active_settings(group_id=group_id)
                if fresh:
                    await _refresh_board(ctx, fresh, group_id)
                    await _check_all_paid_and_resend(ctx.bot, fresh, group_id)
            else:
                register_number(game_id, user_id, user_name, from_num, False)
                await msg.reply_text(f"{to_num:02d} አልተቻለም 🙏")
        return

    if resp.get("why_not_registered") is not None:
        target_num = resp["why_not_registered"]["number"]
        attempts = get_failed_attempts(game_id, user_id, target_num)

        if not attempts:
            await msg.reply_text(random.choice(RESPONSES["why_not_registered_none"]))
            return

        lines = []
        for a in attempts:
            num = f"{a['number']:02d}"
            t = a["attempted_at"].strftime("%I:%M %p")
            if a["reason"] == "taken":
                if a["slot2_name"]:
                    line = random.choice(RESPONSES["why_not_registered_taken_both"]).format(
                        num=num, name1=a["slot1_name"], type1=a["slot1_type"],
                        name2=a["slot2_name"], time=t
                    )
                else:
                    line = random.choice(RESPONSES["why_not_registered_taken"]).format(
                        num=num, name=a["slot1_name"], type=a["slot1_type"], time=t
                    )
            elif a["reason"] == "range":
                line = random.choice(RESPONSES["why_not_registered_range"]).format(num=num)
            else:
                line = f"{num} — ምክንያት ታወቀ 🙏"
            lines.append(line)

        await msg.reply_text("\n".join(lines))
        return

    import re as _re
    if _re.findall(r'\b\d{9,}\b', text):
        if resp["reply"]:
            await msg.reply_text(resp["reply"])
        return

    price_full = float(settings.get("price_full") or 0)
    price_half = float(settings.get("price_half") or 0)
    parse_result = parse_numbers(text, price_full=price_full, price_half=price_half)

    if not parse_result:
        if resp["reply"]:
            await msg.reply_text(resp["reply"])
        elif not resp["resend_remaining"] and not resp["resend_nekay"]:
            try:
                game_data_slice = {
                    "total_numbers": settings.get("total_numbers"),
                    "price_full": settings.get("price_full"),
                    "price_half": settings.get("price_half"),
                    "prize_1st": settings.get("prize_1st"),
                    "prize_2nd": settings.get("prize_2nd"),
                    "prize_3rd": settings.get("prize_3rd"),
                    "remaining_count": remaining,
                    "countdown_seconds": countdown_seconds,
                    "nekay_active": _gk(group_id, game_id) in nekay_active,
                    "recent_winners": [
                        {"place": w["place"], "user_name": w["user_name"], "prize": w["prize"]}
                        for w in (recent_winners or [])[:3]
                    ],
                }
                ai_reply = await get_ai_fallback(
                    text=text,
                    user_id=user_id,
                    group_id=group_id,
                    game_data=game_data_slice,
                )
                if ai_reply:
                    await msg.reply_text(ai_reply)
            except Exception as _ai_err:
                logging.warning(f"[AI Fallback] Error: {_ai_err}")
        if resp["resend_remaining"]:
            if _gk(group_id, game_id) in nekay_active:
                rem_msg_id = settings.get("remaining_message_id")
                if rem_msg_id:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                    except Exception:
                        pass
                if snap:
                    nekay_text_r = build_nekay(nekay_list)
                    new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text_r)
                    update_remaining_message_id(game_id, new_nekay.message_id)
            else:
                await _send_remaining(ctx, settings, group_id)
        if resp["resend_nekay"]:
            if snap:
                nekay_text = build_nekay(nekay_list)
                rem_msg_id = settings.get("remaining_message_id")
                if rem_msg_id:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                    except Exception:
                        pass
                new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
                update_remaining_message_id(game_id, new_nekay.message_id)
        return

    if photo_processing.get(group_id):
        q = pending_registrations.setdefault(group_id, [])
        q.append((user_id, user_name, text, msg))
        return

    if not parse_result.get("is_clear_pattern", True):
        try:
            from ai_fallback import ai_parse_booking
            ai_result = await ai_parse_booking(text, settings)
            if ai_result.get("is_booking") and ai_result.get("numbers"):
                numbers = [(n["num"], n["is_half"], n.get("name")) for n in ai_result["numbers"]]
                await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)
                return
            else:
                if resp["reply"]:
                    await msg.reply_text(resp["reply"])
                return
        except Exception as _ai_err:
            logging.warning(f"[AI BookingCheck] Error: {_ai_err}")

    numbers = parse_result["numbers"]
    ambiguous = parse_result["ambiguous"]
    ambiguous_number = parse_result["ambiguous_number"]

    if ambiguous:
        pending_ambiguous[user_id] = {
            "numbers": numbers, "ambiguous": ambiguous,
            "ambiguous_number": ambiguous_number,
            "game_id": settings["id"], "settings": settings,
            "group_id": group_id, "user_name": user_name
        }
        # FIX: መጀመሪያ እንደተጻፈው (as-typed — "+" የሌላቸው ሙሉ፣ "+" ያላቸው ግማሽ)
        # ወዲያውኑ ይመዘገባል፤ ጥያቄው ከዚያ በኋላ ብቻ ይጠየቃል (ካስፈለገ ለውጥ ብቻ
        # handle_ambiguous_reply ላይ ይደረጋል)። ቀድሞ ምዝገባው ጥያቄው እስኪመለስ
        # ድረስ ይጠብቅ ነበር፣ ይህም ሌላ action ቢመጣ ምዝገባ ሳይፈጸም ይቀር ነበር።
        await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)
        if ambiguous == "all_half":
            await msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
        elif ambiguous == "last_half":
            await msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
        return

    if _gk(group_id, game_id) in active_countdowns:
        per_person = settings["numbers_per_person"]
        for num, is_half, parsed_name in numbers:
            actual_num = get_group_start(num, per_person) if per_person > 1 else num
            if actual_num in taken and user_owns_number(game_id, user_id, actual_num):
                pass
            elif actual_num in taken and not user_owns_number(game_id, user_id, actual_num):
                await msg.reply_text(NEKAY_COUNTDOWN_MESSAGE)
                return

    await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)

    try:
        log_activity(group_id, registrations=1)
    except Exception:
        pass


async def handle_ambiguous_reply(update, ctx, text, user_id, user_name, group_id):
    pending = pending_ambiguous.get(user_id)
    if not pending:
        return

    text_lower = text.lower()
    yes = text_lower in ["አዎ", "awo", "yes", "aha", "አዎን"]
    no = text_lower in ["አይደለም", "aydelem", "no", "የለም"]
    if not yes and not no:
        no = True

    numbers = pending["numbers"]
    ambiguous = pending["ambiguous"]
    ambiguous_number = pending["ambiguous_number"]
    settings = pending["settings"]

    del pending_ambiguous[user_id]

    # FIX: ምዝገባው ቀድሞ (as-typed) ተመዝግቧል — እዚህ ደግሞ የሚያስፈልገው ለውጥ ብቻ
    # ነው የሚደረገው (register_number's toggle/target logic ቀድሞ የተመዘገቡትን
    # ወደ አዲሱ half/full ይቀይራል)። ለውጥ የማያስፈልግ ከሆነ ምንም አይደረግም።
    if ambiguous == "all_half" and yes:
        converted = [(n, True, nm) for n, _, nm in numbers]
        await process_registration(ctx, settings, converted, user_id, user_name, group_id, update.message)
    elif ambiguous == "last_half" and not yes:
        converted = [(n, False, nm) for n, _, nm in numbers]
        await process_registration(ctx, settings, converted, user_id, user_name, group_id, update.message)


async def process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg, skip_board_update=False):
    game_id = settings["id"]
    per_person = settings["numbers_per_person"]

    taken_before = get_taken_numbers(game_id)
    remaining_before = count_remaining(settings, taken_before)

    registered = []
    all_taken = []
    no_change_reply = False

    allow_toggle = (len(numbers) == 1)

    # FIX #3: admin "#name <name>" override ካለ (highest priority) —
    # parsed_name/telegram username ምንም ይሁኑ ሁሌም override ስም ጥቅም ላይ ይውላል።
    name_override = get_name_override(group_id, user_id)

    for num, is_half, parsed_name in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        nekay_snap_value = None
        if _gk(group_id, game_id) in nekay_numbers and actual_num in nekay_numbers.get(_gk(group_id, game_id), {}):
            nekay_snap_value = nekay_numbers[_gk(group_id, game_id)][actual_num]

        is_nekay = (nekay_snap_value is not None)
        # FIX: -1/-2 (06+1 / 06+2 slot-specific nekay) ደግሞ force ናቸው —
        # ቀደም ብሎ 0 ብቻ ነበር force ተብሎ የሚታየው፣ ስለዚህ +1/+2 slot-specific
        # nekay ላይ force overwrite ፈጽሞ አይሰራም ነበር።
        is_nekay_force = nekay_snap_value in (0, -1, -2)
        force_slot = None
        if nekay_snap_value == -1:
            force_slot = 1
        elif nekay_snap_value == -2:
            force_slot = 2

        # FIX: parsed_name (ተጠቃሚው በጽሁፍ ያስገባው ስም) ከ #name override የበለጠ
        # ቅድሚያ ያገኛል። Override የሚሰራው ተጠቃሚው ምንም ስም ካልጻፈ ብቻ ነው
        # (default/fallback)።
        if parsed_name:
            actual_name = parsed_name
        elif name_override:
            actual_name = name_override
        elif is_nekay_force:
            actual_name = user_name
        elif actual_num in taken_before:
            existing_slots = taken_before[actual_num]
            slot1 = next((s for s in existing_slots if s[2] == 1), None)
            if slot1 and slot1[0] != user_name and slot1[1]:
                actual_name = user_name
            else:
                actual_name = slot1[0] if slot1 else user_name
        else:
            actual_name = user_name

        if actual_num < 1 or actual_num > settings["total_numbers"]:
            all_taken.append(actual_num)
            continue

        if user_owns_number(game_id, user_id, actual_num) and not is_nekay:
            target_type = "half" if is_half else "full"
            result_tc = change_number_type(game_id, user_id, actual_num, target_type)
            if result_tc["status"] == "ok":
                actual_is_half = is_half
                if result_tc.get("pending_upgrade"):
                    actual_is_half = True
                # FIX: ትክክለኛውን slot ያግኝ (is_paid ማረጋገጫ ትክክለኛውን slot እንዲፈትሽ)
                actual_slot = 1
                for n_num, n_half, n_slot, n_paid in get_user_numbers(game_id, user_id):
                    if n_num == actual_num and n_slot != 1:
                        actual_slot = n_slot
                        break
                registered.append((actual_num, actual_is_half, actual_slot))
            elif result_tc["status"] == "no_change":
                no_change_reply = True
            elif result_tc["status"] == "conflict":
                all_taken.append(actual_num)
            continue

        result = register_number(
            game_id, user_id, actual_name, actual_num, is_half,
            force=is_nekay_force, allow_toggle=allow_toggle,
            is_parsed_name=bool(parsed_name), force_slot=force_slot,
        )
        if result in ["registered", "registered_half"]:
            # FIX: is_half እና slot ትክክለኛውን ውጤት ያንፀባርቁ — ቀድሞ "registered_half"
            # (አዲስ ሰው ቀድሞ በግማሽ ወደተያዘ ቁጥር ላይ "+" ሳይጠቀም ሲቀላቀል) is_half=False
            # ተብሎ በስህተት ይመዘገብ ነበር፣ ይህም is_paid ማረጋገጫ የተሳሳተ slot እንዲፈትሽ
            # ያደርግ ነበር (የተሳሳተ "still needs payment" መልእክት ያመጣ ነበር)።
            actual_is_half = is_half or (force_slot is not None) or (result == "registered_half")
            if force_slot is not None:
                actual_slot = force_slot
            elif result == "registered_half":
                actual_slot = 2
            else:
                actual_slot = 1
            registered.append((actual_num, actual_is_half, actual_slot))
        elif isinstance(result, dict) and result.get("status") == "ok":
            new_is_half = get_user_numbers(game_id, user_id)
            actual_is_half = is_half
            actual_slot = 1
            for n_num, n_half, n_slot, n_paid in new_is_half:
                if n_num == actual_num and n_slot == 1:
                    actual_is_half = n_half
                    actual_slot = n_slot
                    break
            registered.append((actual_num, actual_is_half, actual_slot))
        elif isinstance(result, dict) and result.get("status") == "no_change":
            no_change_reply = True
        else:
            all_taken.append(actual_num)

    # FIX: board edit delay — get_taken_numbers/get_paid_numbers (psycopg2,
    # blocking) event loop ን እንዳያግድ asyncio.to_thread ውስጥ ይሮጣሉ። register_number
    # (ከላይ ባለው loop ውስጥ) ሆን ተብሎ አልተነካም — race condition እንዳይፈጠር።
    taken = await asyncio.to_thread(get_taken_numbers, game_id)
    paid = await asyncio.to_thread(get_paid_numbers, game_id)
    remaining_count = count_remaining(settings, taken)
    snap = nekay_numbers.get(_gk(group_id, game_id), {})
    nekay_list = _build_nekay_from_snap(snap)

    if not registered and not all_taken and no_change_reply:
        await msg.reply_text("እሺ 🙏")
        return

    reg_result = "registered" if registered else ("taken" if all_taken else None)

    # FIX #2: ሁሉም ቁጥሮች ✅ (ሁሉም ተከፍለው) ካለቁ በኋላ (ውጤት ገና ካልታወቀ/pre-booking
    # ገና ካልጀመረ)፣ ሰው ቁጥር ለመያዝ ቢሞክር "ተቀደምክ" ከመመለስ ይልቅ "አሁን የውጤት ሰዓት
    # ነው" ይመለስ።
    if reg_result == "taken" and all_numbers_paid(game_id, settings):
        await msg.reply_text("አሁን የውጤት ሰዓት ነው ቤተሰብ ትንሽ ይጠብቁ 🙏")
        return

    is_paid_result = None
    if registered:
        is_paid_result = all(
            num in paid and slot in paid[num]
            for num, _is_half, slot in registered
        )

    resp = get_response(
        text=msg.text or "",
        settings=settings,
        taken=taken,
        paid=paid,
        nekay_list=nekay_list,
        remaining_count=remaining_count,
        countdown_seconds=0,
        user_name=user_name,
        registration_result=reg_result,
        is_paid=is_paid_result,
    )

    # FIX #1 + #6: pre-booking ሰዓት (ውጤት/board ገና ስላልታወቀ ገንዘቡ ማን
    # እንደሚይዘው ገና ስለማይታወቅ) የተሳካ ምዝገባ ላይ የጽሁፍ reply ሳይሆን 👍 reaction
    # ብቻ ይላክ። ደግሞም reply/reaction Telegram API call ን fire-and-forget
    # (asyncio.create_task) አድርገን እንልካለን፣ ስለዚህ ከታች ያለው board edit
    # ይህን call እስኪመለስ ድረስ መጠበቅ አያስፈልገውም (ቀድሞ sequential ስለነበር board
    # edit ይዘገይ ነበር)።
    if reg_result == "registered" and (group_id in prebooking_groups or group_id in winner_pending_groups):
        asyncio.create_task(_safe_set_reaction(ctx.bot, group_id, msg.message_id))
    elif resp["reply"]:
        if reg_result == "taken":
            # NEW: "እሺ/eshi" replacement feature ይህን rejection reply message_id
            # እንዲያገኘው (ወደፊት admin ቢተካው እንዲጠፋ) ተመዝግቦ ይቀመጣል
            asyncio.create_task(_safe_reply_text_and_track(msg, resp["reply"], group_id))
        else:
            asyncio.create_task(_safe_reply_text(msg, resp["reply"]))

    if not registered:
        return

    if skip_board_update:
        return

    # pre-booking mode (ወይም winner photo 30s ክፍተት) — registration ተሰርቷል
    # ግን board አይታይም
    if group_id in prebooking_groups or group_id in winner_pending_groups:
        return

    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")

    should_resend = _increment_counter(group_id)

    crossed_into_low = (remaining_before > 7) and (remaining_count <= 7)
    if crossed_into_low and _gk(group_id, game_id) not in nekay_active:
        should_resend = True

    if remaining_count > 7 and _gk(group_id, game_id) not in nekay_active:
        should_resend = False

    if _gk(group_id, game_id) in nekay_active:
        if should_resend:
            if board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                except Exception:
                    pass
            new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)
        else:
            if board_msg_id:
                try:
                    await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
                except Exception as e:
                    if "not modified" in str(e).lower():
                        pass
                    else:
                        try:
                            await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                        except Exception:
                            pass
                        new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                        await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)
            else:
                new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)

        # FIX: intermittent nekay-list corruption — ከላይ snap ከተነበበ ጀምሮ
        # (መስመር ~1968) እስከዚህ ድረስ ብዙ awaits (board/nekay message edits)
        # ስላሉ፣ 2 ሰዎች በተመሳሳይ ሰዓት የተለያየ ቁጥር ቢይዙ (interleaved coroutines)
        # በአንድ shared dict ላይ ተደራርበው ሊጣረሱ ይችላሉ (ሌላውን entry ሊያጠፉ
        # ይችላሉ)። ስለዚህ ልክ ከመንካቱ በፊት የቅርብ ጊዜውን nekay_numbers ደግሞ
        # እናነብበዋለን (race window ለመቀነስ)።
        snap = nekay_numbers.get(_gk(group_id, game_id), snap)
        for num, is_half, _slot in registered:
            if num in snap:
                if is_half and snap[num] == 0:
                    snap[num] = 2
                else:
                    del snap[num]
        nekay_numbers[_gk(group_id, game_id)] = snap

        rem_msg_id = settings.get("remaining_message_id")
        if rem_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
            except Exception:
                pass
        if snap:
            nekay_list2 = _build_nekay_from_snap(snap)
            nekay_text = build_nekay(nekay_list2)
            new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
            await asyncio.to_thread(update_remaining_message_id, game_id, new_nekay.message_id)
        else:
            await asyncio.to_thread(update_remaining_message_id, game_id, None)
            nekay_active.discard(_gk(group_id, game_id))
            nekay_numbers.pop(_gk(group_id, game_id), None)
            _stop_inactivity_tracker(game_id, group_id)

        _reset_inactivity_tracker(ctx.bot, game_id, group_id)

    elif remaining_count <= 7:
        if should_resend:
            if board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                except Exception:
                    pass
            new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)
        else:
            if board_msg_id:
                try:
                    await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
                except Exception as e:
                    if "not modified" not in str(e).lower():
                        new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                        await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)
        await _send_remaining(ctx, settings, group_id)
        _reset_inactivity_tracker(ctx.bot, game_id, group_id)

    else:
        if board_msg_id:
            try:
                await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
            except Exception as e:
                if "not modified" not in str(e).lower():
                    new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    await asyncio.to_thread(update_board_message_id, game_id, new_board.message_id)

    if remaining_count == 0 and _gk(group_id, game_id) not in active_countdowns and _gk(group_id, game_id) not in countdown_done and _gk(group_id, game_id) not in admin_nekay_games:
        _stop_inactivity_tracker(game_id, group_id)

        fresh_settings_for_resend = await asyncio.to_thread(get_active_settings, group_id=group_id)
        if fresh_settings_for_resend:
            final_board_msg_id = fresh_settings_for_resend.get("board_message_id")
            if final_board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=final_board_msg_id)
                except Exception:
                    pass
            final_taken = await asyncio.to_thread(get_taken_numbers, game_id)
            final_paid = await asyncio.to_thread(get_paid_numbers, game_id)
            final_board_text = build_board(fresh_settings_for_resend, final_taken, final_paid)
            final_new_board = await ctx.bot.send_message(chat_id=group_id, text=final_board_text)
            await asyncio.to_thread(update_board_message_id, game_id, final_new_board.message_id)

        countdown_enabled = settings.get("countdown_enabled", True)
        if countdown_enabled:
            countdown_mins = settings.get("countdown_minutes") or 2
            warn_secs = int(float(countdown_mins) * 60)
            task = asyncio.create_task(_countdown_task(ctx.bot, game_id, group_id, warn_seconds=warn_secs))
            active_countdowns[_gk(group_id, game_id)] = {"task": task, "start": time.time(), "warn_secs": warn_secs}
            countdown_done.add(_gk(group_id, game_id))

    fresh = await asyncio.to_thread(get_active_settings, group_id=group_id)
    if fresh:
        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)

    try:
        await asyncio.to_thread(check_and_rotate_db)
    except Exception:
        pass


# ============================================================
# HELPERS
# ============================================================

async def _send_remaining(ctx, settings, group_id):
    game_id = settings["id"]
    taken = await asyncio.to_thread(get_taken_numbers, game_id)
    remaining_text = build_remaining(settings, taken)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
        except Exception:
            pass

    if remaining_text:
        rem_msg = await ctx.bot.send_message(chat_id=group_id, text=remaining_text)
        await asyncio.to_thread(update_remaining_message_id, game_id, rem_msg.message_id)
    else:
        await asyncio.to_thread(update_remaining_message_id, game_id, None)


async def _refresh_board(ctx, settings, group_id=None):
    game_id = settings["id"]
    _group_id = group_id or settings.get("group_id") or GROUP_ID
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")

    if board_msg_id:
        try:
            await ctx.bot.edit_message_text(chat_id=_group_id, message_id=board_msg_id, text=board_text)
        except Exception as e:
            if "not modified" not in str(e).lower():
                new_msg = await ctx.bot.send_message(chat_id=_group_id, text=board_text)
                update_board_message_id(game_id, new_msg.message_id)
    else:
        new_msg = await ctx.bot.send_message(chat_id=_group_id, text=board_text)
        update_board_message_id(game_id, new_msg.message_id)


# ============================================================
# BOARD REPLY PARSE
# ============================================================

def _parse_name_and_pending(raw: str):
    """
    ✅/? marker parsing — ተጠቃሚው እውነተኛ ስም ራሱ "?" ቢይዝ (ለምሳሌ ስሙ በትክክል
    "??" ቢሆን) stripping ስሙን ሙሉ ለሙሉ ባዶ እንዳያደርገው ይጠብቃል፦ stripping "?"
    ስሙን ባዶ የሚያደርገው ከሆነ (እና stripping ከመደረጉ በፊት ይዘት ነበረ) ያ "?" እንደ
    pending marker ሳይሆን የስሙ አካል ተደርጎ ይያዛል።
    """
    paid = "✅" in raw
    no_check = raw.replace("✅", "").strip()
    stripped = no_check.replace("?", "").strip()
    if not stripped and no_check:
        return no_check, False, paid
    return stripped, ("?" in no_check), paid


def _parse_board_text(text: str, symbol: str = "#") -> dict:
    import re
    changes = {}

    for line in text.split("\n"):
        line = line.strip()
        escaped = re.escape(symbol)
        pattern = rf"^(\d{{2}}){escaped}\s*(.*)$"
        match = re.match(pattern, line)
        if not match:
            continue

        number = int(match.group(1))
        rest = match.group(2).strip()

        if not rest:
            changes[number] = None
            continue

        data = {}

        if "+" in rest:
            parts = rest.split("+", 1)
            slot1_raw = parts[0].strip()
            slot2_raw = parts[1].strip()

            name1, _pending1_unused, paid1 = _parse_name_and_pending(slot1_raw)
            data["name1"] = name1 if name1 else None
            data["paid1"] = paid1
            data["is_half1"] = True
            data["pending1"] = False

            name2, _pending2_unused, paid2 = _parse_name_and_pending(slot2_raw)
            data["name2"] = name2 if name2 else None
            data["paid2"] = paid2
        else:
            name1, pending1, paid1 = _parse_name_and_pending(rest)
            data["name1"] = name1 if name1 else None
            data["paid1"] = paid1
            data["is_half1"] = False
            data["pending1"] = pending1
            data["name2"] = None
            data["paid2"] = False

        changes[number] = data

    return changes


# ============================================================
# NEW — WINNER "🔥 REACTION" BALANCE-CLEAR FEATURE
# Admin puts a native 🔥 reaction on any message previously sent BY a
# recent winner (1ኛ/2ኛ/3ኛ) in the group → that winner's balance ONLY
# gets cleared (exactly like /clearbalance @username, by telegram_id).
# Board/registrations/paid status ናቸው untouched — user_balance ብቻ ነው
# የሚጸዳው። Confirmation message ("✅ ... ጸድቷል") ይላካል እና 1.5 ሰከንድ ቆይቶ
# ራሱ ይጠፋል (_send_temp_admin_message helper ተጠቅሞ)።
# ============================================================

async def handle_winner_fire_reaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reaction = update.message_reaction
    if not reaction:
        return

    new_emojis = set()
    for r in (reaction.new_reaction or []):
        emoji = getattr(r, "emoji", None)
        if emoji:
            new_emojis.add(emoji)

    if "🔥" not in new_emojis:
        return

    old_emojis = set()
    for r in (reaction.old_reaction or []):
        emoji = getattr(r, "emoji", None)
        if emoji:
            old_emojis.add(emoji)

    if "🔥" in old_emojis:
        # ቀድሞውኑ 🔥 ነበረው (አዲስ addition አይደለም) — ድጋሚ balance ማጽዳት አያስፈልግም
        return

    group_id = reaction.chat.id
    actor = reaction.user
    if not actor:
        return

    if not is_admin(actor.id, group_id):
        return

    if not is_group_enabled(group_id):
        return

    try:
        sender = await asyncio.to_thread(get_message_sender, group_id, reaction.message_id)
    except Exception as e:
        logging.warning(f"[WinnerFireReaction] get_message_sender error: {e}")
        return
    if not sender:
        return

    target_telegram_id = sender["telegram_id"]
    target_name = sender["user_name"]

    try:
        cleared = clear_balance_by_telegram_id(group_id, target_telegram_id)
    except Exception as e:
        logging.warning(f"[WinnerFireReaction] clear_balance error: {e}")
        return

    if not cleared:
        return

    # ✅ "cleared" ማረጋገጫ message ይላካል፣ ልክ እንደ nekay 1.5 ሰከንድ ቆይቶ ራሱ ይጠፋል
    await _send_temp_admin_message(
        ctx.bot, group_id, f"✅ {target_name} ባላንስ ጸድቷል", delay=1.5,
    )


async def handle_winner_correction_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group ላይ bot winner announcement ላይ '#/ 10 20 31' reply ሲያደርግ
    handle_winner_correction ይጠራ።
    """
    msg = update.message
    if not msg or not msg.text:
        return

    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_admin(user_id, group_id):
        return
    if not is_group_enabled(group_id):
        return
    if not is_group_active(group_id):
        return

    # '#/' pattern check
    text = msg.text.strip()
    if not text.startswith("#/"):
        return

    # reply to bot message ብቻ ይሰራ
    if not msg.reply_to_message:
        return
    if not msg.reply_to_message.from_user:
        return
    if not msg.reply_to_message.from_user.is_bot:
        return

    # 'Winners!' ወይም 'Winners (ተስተካከለ)' announcement ላይ ብቻ
    replied_text = msg.reply_to_message.text or ""
    if "🏆" not in replied_text and "Winners" not in replied_text:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    from handlers import handle_winner_correction, parse_winner_correction
    numbers = parse_winner_correction(text)
    if not numbers:
        await msg.reply_text("❌ ምሳሌ: #/ 10  ወይም  #/ 10 20  ወይም  #/ 10 20 31")
        return

    # DB ላይ ያሉ current winners ያምጣ (ለ reverse ያስፈልጋሉ)
    game_id = settings["id"]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT place, telegram_id, user_name, prize
        FROM winners
        WHERE game_id=%s AND group_id=%s
        ORDER BY place ASC
    """, (game_id, group_id))
    winner_rows = cur.fetchall()
    cur.close()
    conn.close()

    # previous_winners format ለ handle_winner_correction
    prev_by_place = {}
    for place, telegram_id, user_name, prize in winner_rows:
        if place not in prev_by_place:
            prev_by_place[place] = {"place": place, "number": None, "users": []}
        prev_by_place[place]["users"].append({
            "telegram_id": telegram_id,
            "user_name": user_name,
            "split_prize": float(prize or 0),
        })
    previous_winners = list(prev_by_place.values())

    try:
        await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
    except Exception:
        pass

    await handle_winner_correction(
        bot=ctx.bot,
        msg=msg,
        previous_winners=previous_winners,
        settings=settings,
        group_id=group_id,
    )


async def handle_admin_board_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_admin(user_id, group_id):
        return

    if not is_group_enabled(group_id):
        return

    if not is_group_active(group_id):
        return

    if not msg.reply_to_message:
        return

    if not msg.reply_to_message.from_user:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    symbol = settings.get("slot_symbol") or "#"
    import re
    escaped = re.escape(symbol)
    if not re.search(rf"\d{{2}}{escaped}", msg.text):
        return

    game_id = settings["id"]
    text = msg.text.strip()

    changes = _parse_board_text(text, symbol)
    if not changes:
        return

    try:
        await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
    except Exception as e:
        logging.warning(f"[BoardReply] Delete admin msg error: {e}")

    for number, data in changes.items():
        if number < 1 or number > settings["total_numbers"]:
            continue

        if data is None:
            admin_remove_player(game_id, number, slot=None)
            if _gk(group_id, game_id) in nekay_numbers:
                snap = nekay_numbers.get(_gk(group_id, game_id), {})
                snap.pop(number, None)
                nekay_numbers[_gk(group_id, game_id)] = snap
        else:
            name1 = data.get("name1")
            paid1 = data.get("paid1", False)
            is_half1 = data.get("is_half1", False)
            pending1 = data.get("pending1", False)
            name2 = data.get("name2")
            paid2 = data.get("paid2", False)

            conn_check = get_conn()
            cur_check = conn_check.cursor()
            cur_check.execute("""
                SELECT slot, user_id, user_name, is_paid FROM registrations
                WHERE game_id=%s AND number=%s
            """, (game_id, number))
            existing_rows = cur_check.fetchall()
            cur_check.close()
            conn_check.close()
            uid_map = {row[0]: row[1] for row in existing_rows}
            name_map = {row[0]: row[2] for row in existing_rows}
            paid_map = {row[0]: row[3] for row in existing_rows}
            was_paid1 = bool(paid_map.get(1, False))

            # FIX: admin ብዙ ጊዜ ሙሉውን board ጽሁፍ ኮፒ አድርጎ (የፈለገውን 1 መስመር
            # ብቻ ቀይሮ) reply ያደርጋል — ስለዚህ _parse_board_text() ያልተነኩትንም
            # መስመሮች (ሁሉንም ቁጥሮች) ጭምር ይመልሳል። ይህ line ከ DB ውስጥ ካለው ጋር
            # ፍጹም ተመሳሳይ (ምንም ያልተቀየረ) ከሆነ ጨርሶ አንንካውም — አለበለዚያ
            # admin_remove_player+register_number (is_nekay ሁልጊዜ FALSE
            # አድርጎ ስለሚያስገባ) ያልተነኩ ቁጥሮች ላይ ያለውን is_nekay ሁኔታ ያጠፋዋል
            # (ይህ ነው ነቃይ list ሙሉ ለሙሉ ድንገት ይጠፋ የነበረው ትክክለኛ ምክንያት)።
            current_name1 = name_map.get(1)
            current_paid1 = bool(paid_map.get(1, False))
            current_name2 = name_map.get(2)
            current_paid2 = bool(paid_map.get(2, False))
            if (name1 == current_name1 and paid1 == current_paid1
                    and name2 == current_name2 and paid2 == current_paid2):
                continue

            # FIX: slot1/slot2 ን ተነጣጥሎ ማነጻጸር (ከዚህ በፊት ሁለቱም slots
            # ላይ ትንሽ ለውጥ እንኳ ቢኖር ሁለቱም ይሰረዙ ነበር — ስለዚህ ያልተነካው slot
            # (ለምሳሌ nekay/unpaid የሆነ) ጭምር ይጠፋ ነበር)
            slot1_changed = not (name1 == current_name1 and paid1 == current_paid1)
            slot2_changed = not (name2 == current_name2 and paid2 == current_paid2)

            if not slot1_changed and not slot2_changed:
                continue

            if slot1_changed:
                admin_remove_player(game_id, number, slot=1)
                if name1:
                    orig_uid1 = uid_map.get(1, 0)
                    conn1 = get_conn()
                    cur1 = conn1.cursor()
                    cur1.execute("""
                        INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                        VALUES (%s, %s, %s, %s, %s, 1, %s, FALSE, %s)
                        ON CONFLICT DO NOTHING
                    """, (game_id, orig_uid1, name1, number, is_half1, paid1, pending1))
                    conn1.commit()
                    cur1.close()
                    conn1.close()

            if slot2_changed:
                admin_remove_player(game_id, number, slot=2)
                if name2:
                    orig_uid2 = uid_map.get(2, 0)
                    conn2 = get_conn()
                    cur2 = conn2.cursor()
                    cur2.execute("""
                        INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                        VALUES (%s, %s, %s, %s, TRUE, 2, %s, FALSE, FALSE)
                        ON CONFLICT DO NOTHING
                    """, (game_id, orig_uid2, name2, number, paid2))
                    conn2.commit()
                    cur2.close()
                    conn2.close()

            if _gk(group_id, game_id) in nekay_numbers and slot1_changed:
                snap = nekay_numbers.get(_gk(group_id, game_id), {})
                if number in snap:
                    if paid1 and not was_paid1:
                        pass
                    elif not paid1 and was_paid1:
                        snap[number] = 2 if is_half1 else 0
                    elif name1:
                        del snap[number]
                else:
                    if not paid1 and was_paid1:
                        snap[number] = 2 if is_half1 else 0
                nekay_numbers[_gk(group_id, game_id)] = snap

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        taken_fresh = get_taken_numbers(game_id)
        paid_fresh = get_paid_numbers(game_id)
        board_text_fresh = build_board(fresh, taken_fresh, paid_fresh)
        board_msg_id_now = fresh.get("board_message_id")
        if board_msg_id_now:
            try:
                await ctx.bot.edit_message_text(
                    chat_id=group_id, message_id=board_msg_id_now, text=board_text_fresh
                )
            except Exception as e:
                if "not modified" in str(e).lower():
                    pass
                else:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id_now)
                    except Exception:
                        pass
                    new_board_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text_fresh)
                    update_board_message_id(game_id, new_board_msg.message_id)
        else:
            new_board_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text_fresh)
            update_board_message_id(game_id, new_board_msg.message_id)

        if _gk(group_id, game_id) in nekay_active:
            nekay_fresh = get_nekay_numbers(game_id)
            snap = {}
            for number, slots, is_half in nekay_fresh:
                snap[number] = 2 if is_half else 0
            nekay_numbers[_gk(group_id, game_id)] = snap

            rem_msg_id = fresh.get("remaining_message_id")
            if rem_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                except Exception:
                    pass
            if snap:
                nekay_list = _build_nekay_from_snap(snap)
                nekay_text = build_nekay(nekay_list)
                new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
                update_remaining_message_id(game_id, new_nekay.message_id)
            else:
                update_remaining_message_id(game_id, None)
                nekay_active.discard(_gk(group_id, game_id))
                nekay_numbers.pop(_gk(group_id, game_id), None)
                _stop_inactivity_tracker(game_id, group_id)

        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)


# ============================================================
# OWNER REASSIGNMENT — admin replies to a REAL USER's message with
# "#/ 01 21 31+1" to attach that user's telegram_id to numbers that
# were registered manually (board edit / /register) without a real
# telegram user_id. Only fixes ownership (user_id) — user_name and
# paid status entered by the admin are left untouched.
#   #/ 01        → number 1, all slots → this user
#   #/ 31+1      → number 31, slot 1 only → this user
#   #/ 11        → if number 11 already belongs to someone else,
#                   ownership is transferred to this user
# ============================================================

async def handle_owner_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # ✅ FIX: 2 ሙሉ በሙሉ የተለያዩ syntax — እንዳይምታቱ (ይህ ፍተሻ ቀድሞ እንዲደረግ
    # ተንቀሳቅሷል፣ ስለዚህ "#" ባልጀመረ message ላይ ዋጋ የሌለው DB call አይደረግም)
    #   "#<amount>"   (ስላሽ የለውም) → Winner ክፍያ ብቻ, ለምሳሌ #300
    #   "#/ NUM ..."  (ስላሽ አለው)  → Owner reassignment ብቻ, ለምሳሌ #/ 01 21 31+1
    #   "#name <ስም>"  → FIX #3: name override, ለምሳሌ #name አበበ ወይም #name አበበ ከበደ
    #                    "#name" ብቻ (ስም ሳይከተል) → override reset
    #   "##cancel"    → payment-fingerprint feature: ያ user's fingerprint ያጠፋል
    #   "##<SMS text>" → payment-fingerprint feature: admin ራሱ የደረሰውን SMS
    #                    ጽሁፍ ኮፒ አድርጎ reply ያደርጋል → AI parse → confirm_payment
    #                    + fingerprint learn (ወደፊት "ልኬያለው" ራስ-ሰር እንዲሆን)
    #   "#እሺ/#eshi NUM[+SLOT][✅] ..." → NEW: reply-to-user (ተይዞብሃል ያለበት
    #                    ኦርጅናል message ላይ reply) ባለቤት+ስም ይተካል፣ ✅ ካለ paid
    #                    ተብሎ ይመዘገባል፣ ቀደም ያለው bot rejection message ይጠፋል፣
    #                    "NUM ተይዞልሃል 🙏" አዲስ message ይላካል። "#" prefix ግድ
    #                    ነው (ያለ # ብቻውን "እሺ" ተራ ወሬ/reply ጋር እንዳይምታታ)
    is_sms_cancel_form = text.lower().startswith("##cancel")
    is_sms_paste_form = text.startswith("##") and not is_sms_cancel_form
    is_name_form = text.lower().startswith("#name")
    is_eshi_form = text.startswith("#እሺ") or text.lower().startswith("#eshi")
    is_payment_form = (
        text.startswith("#") and not text.startswith("#/")
        and not is_name_form and not text.startswith("##")
        and not is_eshi_form
    )
    is_owner_form = text.startswith("#/")
    if not (is_payment_form or is_owner_form or is_name_form or is_sms_cancel_form or is_sms_paste_form or is_eshi_form):
        return

    logging.info(f"[OwnerReply] Triggered: text={text!r} chat={update.effective_chat.id} user={update.effective_user.id}")

    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_admin(user_id, group_id):
        logging.info(f"[OwnerReply] Rejected: user {user_id} is not admin in group {group_id}")
        return

    if not is_group_enabled(group_id):
        logging.info(f"[OwnerReply] Rejected: group {group_id} not enabled")
        return

    if not is_group_active(group_id):
        logging.info(f"[OwnerReply] Rejected: group {group_id} not active")
        return

    # winner-correction replies (reply to the BOT's Winners announcement)
    # are handled by handle_winner_correction_reply — this handler is only
    # for replies to a REAL USER's message (ownership fix / payment).
    if not msg.reply_to_message:
        logging.info("[OwnerReply] Rejected: not a reply to any message")
        return
    if not msg.reply_to_message.from_user:
        logging.info("[OwnerReply] Rejected: reply_to_message has no from_user")
        return
    if msg.reply_to_message.from_user.is_bot:
        logging.info("[OwnerReply] Rejected: replied-to message is from the bot (handled elsewhere)")
        return

    owner = msg.reply_to_message.from_user
    owner_id = owner.id

    import re as _re_owner

    # ============================================================
    # FIX #3: "#name <name>" — name override reply-to-user command
    # "#name" ብቻ (ስም ሳይከተል) → override ይጠፋል፣ ወደ original ስም-መለያ logic
    # ይመለሳል (parsed_name ራሱ አልተነካም)። admin ደጋግሞ ሊቀይረው ይችላል — ሁልጊዜ
    # የመጨረሻው ትዕዛዝ ይሰራል። admin's own "#name ..." message ወዲያውኑ ይጠፋል
    # (ልክ እንደ #/ እና # ትዕዛዞች)።
    # ============================================================
    if is_name_form:
        body = text[len("#name"):].strip()
        if body:
            set_name_override(group_id, owner_id, body)
        else:
            clear_name_override(group_id, owner_id)
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        return

    # ============================================================
    # "##cancel" — admin የተሳሳተ fingerprint (ስም/last4) ካስቀመጠ ለዚህ user
    # (reply-to-user) ያለውን fingerprint ሙሉ በሙሉ ያጠፋል።
    # ============================================================
    if is_sms_cancel_form:
        delete_user_fingerprint(group_id, owner_id)
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        winner_name = owner.first_name or owner.username or "Unknown"
        await _send_temp_admin_message(ctx.bot, group_id, f"✅ {winner_name} fingerprint ጠፋ")
        return

    # ============================================================
    # "##<SMS text>" — admin የደረሰውን ትክክለኛ SMS ጽሁፍ ኮፒ አድርጎ user's
    # message ላይ reply ያደርጋል። AI (Groq) parse ያደርገዋል፣ ስም/last4
    # ካጣ ብቻ (URL ካለ) Jina+Groq ሙሉ receipt ያመጣል፣ ከዛ reply-to ያለው
    # owner_id ላይ በቀጥታ confirm_payment() ተጠርቶ fingerprint ይማራል።
    # ============================================================
    if is_sms_paste_form:
        sms_text = text[2:].strip()
        if not sms_text:
            await msg.reply_text("❌ ምሳሌ: ##<SMS ጽሁፍ ኮፒ አድርገህ ለጥፍ>")
            return

        settings_for_sms = get_active_settings(group_id=group_id)
        result = await handle_admin_sms_paste(ctx.bot, msg, sms_text, owner_id, group_id)

        if not result.get("success"):
            await msg.reply_text("❌ SMS ሊተነተን አልቻለም — ጽሁፉን እንደገና ኮፒ አድርገህ ላክ")
            return

        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        winner_name = owner.first_name or owner.username or "Unknown"
        amount = result.get("amount")
        await _send_temp_admin_message(
            ctx.bot, group_id, f"✅ {winner_name} → ETB {amount} ተረጋግጧል (SMS)"
        )

        if settings_for_sms:
            await _refresh_board(ctx, settings_for_sms, group_id)
        return

    if is_payment_form:
        # ✅ WINNER PAYMENT/CORRECTION: "#<amount>" (ስላሽ የለውም) — reply
        # ተደረገበት ሰው real winner ሆኖ ብቻ ይሰራል። AI/userbot ሳይጠቀም admin ራሱ
        # ስንት ብር እንደላከ በ reply ያረጋግጣል። ይህ active game መኖር አያስፈልገውም
        # (ገንዘቡ ቀድሞ ለተመዘገበ winner ብቻ ስለሚሰራ)። ድጋሚ ተመሳሳይ ሰው (የትኛውም
        # message ላይ) #<new_amount> ቢልክ፣ ቀድሞ የተላከው ይሻራል (reverse) እና
        # አዲሱ amount ብቻ ተቀናሽ ይደረጋል (ድምር ሳይሆን ትክክለኛው የመጨረሻ amount ብቻ
        # ውጤት ይሆናል)።
        #
        # FIX: አንድ ሰው ብዙ places (ለምሳሌ 2ኛ እና 3ኛ፣ ወይም 1ኛ እና 2ኛ) በአንድ ጊዜ
        # ካሸነፈ፣ ልክ እንደ userbot2.py's process_winner_payment style ሁሉንም
        # tied ቦታዎች ድምር አድርጎ በአንድ payment (single deduct + single
        # announcement) ይይዛል፣ ምንም ቦታ ሳይዘነጋ።
        body = text[1:].strip()
        amount_match = _re_owner.match(r'^(\d+(?:\.\d+)?)$', body)
        if not amount_match:
            await msg.reply_text("❌ ምሳሌ: #300  (ለ winner ክፍያ ብቻ፣ ቁጥር ብቻ ጻፍ)")
            return

        all_winner_records = get_recent_winners_for_user(group_id, owner_id)
        if not all_winner_records:
            logging.info(f"[OwnerReply] Payment rejected: telegram_id {owner_id} has no recent winner record with prize_balance>0 in group {group_id}")
            await msg.reply_text("❌ ይህ ሰው በቅርብ ጊዜ winner አይደለም — ክፍያ አይሰራም!")
            return

        new_amount = float(amount_match.group(1))

        # tied ቦታዎች ካሉ (ተመሳሳይ game_id+telegram_id) mark_winner_sent
        # single call ሁሉንም rows ወደ ተመሳሳይ sent_amount ስለሚያደርግ፣ ድርብ-ቁጥር
        # እንዳይፈጠር prev_sent የሚሰላው በ MAX (ድምር ሳይሆን) ነው።
        prev_sent = max((w["sent_amount"] for w in all_winner_records), default=0.0)
        primary = all_winner_records[0]  # ዝቅተኛው place (1ኛ ቀዳሚ)
        win_game_id = primary["game_id"]
        places = sorted(set(w["place"] for w in all_winner_records))
        delta = new_amount - prev_sent

        result = deduct_winner_balance(win_game_id, owner_id, delta, group_id=group_id)
        new_balance = result["new_balance"]

        # ሁሉንም tied places (ምናልባትም የተለያዩ game_id ቢኖራቸውም) sent=TRUE
        # እና sent_amount=new_amount አድርጎ ምልክት ያድርግ
        distinct_game_ids = set(w["game_id"] for w in all_winner_records)
        for gid in distinct_game_ids:
            mark_winner_sent(gid, owner_id, new_amount)

        try:
            from ai_fallback import log_transaction
            log_transaction(
                group_id=group_id, game_id=win_game_id,
                telegram_id=owner_id, amount=-delta,
                reason="winner_sent" if prev_sent == 0 else "winner_sent_correction",
                done_by="admin", balance_after=new_balance,
            )
        except Exception as _log_err:
            logging.warning(f"[log_transaction] Error: {_log_err}")

        place_label = " & ".join(
            {1: "1ኛ", 2: "2ኛ", 3: "3ኛ"}.get(p, f"{p}ኛ") for p in places
        )
        winner_name = owner.first_name or owner.username or "Unknown"

        if prev_sent > 0 and prev_sent != new_amount:
            out_text = f"✏️ {place_label} winner: {winner_name} → ተስተካክሏል: ETB {prev_sent:.0f} → ETB {new_amount:.0f}"
        else:
            out_text = f"💸 {place_label} winner: {winner_name} → ETB {new_amount:.0f} ተልኳል"

        # ✅ ተቀባይነት ስላገኘ ብቻ admin's own "#<amount>" message ይጠፋል
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        # FIX #4: admin confirmation message ከ1.5-2 ሰከንድ በኋላ ራሱ ይጠፋል
        await _send_temp_admin_message(ctx.bot, group_id, out_text)

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _refresh_board(ctx, fresh, group_id)
        return

    # ============================================================
    # NEW — "እሺ/eshi NUM[+SLOT][✅] ..." REPLACEMENT (reply-to-user's own
    # "01" attempt message, ልክ ካለፈው ወይም ገና ካለው rejection ("ተይዞብሃል") ጋር)።
    # ባለቤት+ስም ይተካል፣ ✅ ካለ ያ ቁጥር paid ተብሎ ይመዘገባል (ካልሆነ unpaid ይሆናል)፣
    # ቀደም ያለው bot rejection message ይጠፋል፣ "NUM ተይዞልሃል 🙏" አዲስ message
    # ለ user ይላካል፣ board ላይ ስም ይቀየራል።
    # ============================================================
    if is_eshi_form:
        settings_eshi = get_active_settings(group_id=group_id)
        if not settings_eshi:
            return
        game_id_eshi = settings_eshi["id"]

        if text.startswith("#እሺ"):
            eshi_body = text[len("#እሺ"):].strip()
        else:
            eshi_body = text[len("#eshi"):].strip()

        eshi_parts = [p for p in re.split(r'[,\s]+', eshi_body.strip()) if p]
        if not eshi_parts:
            await msg.reply_text("❌ ምሳሌ: #እሺ 01 ወይም #እሺ 01+2 06✅")
            return

        target_name = owner.first_name or owner.username or "Unknown"

        assigned = []
        errors = []
        for part in eshi_parts:
            mark_paid = "✅" in part
            clean_part = part.replace("✅", "")
            slot_match = _re_owner.match(r'^(\d+)\+(\d+)$', clean_part)
            if slot_match:
                number = int(slot_match.group(1))
                slot = int(slot_match.group(2))
                is_half = True
            elif clean_part.endswith("+"):
                try:
                    number = int(clean_part.rstrip("+"))
                except ValueError:
                    errors.append(part)
                    continue
                slot = None
                is_half = True
            else:
                try:
                    number = int(clean_part)
                except ValueError:
                    errors.append(part)
                    continue
                slot = None
                is_half = False

            if number < 1 or number > settings_eshi["total_numbers"]:
                errors.append(part)
                continue

            found = admin_replace_owner(
                game_id_eshi, number, owner_id, target_name,
                slot=slot, mark_paid=mark_paid,
            )

            if not found:
                # NEW: ቁጥሩ ባዶ (ምንም registration ስላልነበረ replace ያልተሳካ)
                # ከሆነ — replace ብቻ ሳይሆን አዲስ registration ደግሞ ይፍጠር
                # (register_number()'s force_slot path is_nekay=TRUE የሚጠይቅ
                # ስለሆነ እና ሌላኛው slot ነባር ቢሆን ትክክል ስለማይሰራ፣ በቀጥታ INSERT
                # እንጠቀማለን — admin override ስለሆነ balance አይነካም)
                reg_slot = slot if slot is not None else 1
                inserted = False
                try:
                    conn_reg = get_conn()
                    cur_reg = conn_reg.cursor()
                    cur_reg.execute("""
                        INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, FALSE)
                        ON CONFLICT DO NOTHING
                    """, (game_id_eshi, owner_id, target_name, number, is_half, reg_slot, mark_paid))
                    inserted = cur_reg.rowcount > 0
                    conn_reg.commit()
                    cur_reg.close()
                    conn_reg.close()
                except Exception as e:
                    logging.warning(f"[Eshi] direct insert fallback error: {e}")

                if inserted:
                    found = True

            if found:
                label = f"{number:02d}" + (f"+{slot}" if slot else "")
                assigned.append(label)
            else:
                errors.append(part)

        if not assigned:
            if errors:
                await msg.reply_text(f"❌ ያልተገኘ: {', '.join(errors)}")
            return

        # ቀደም ያለው bot "ተይዞብሃል" rejection message ካለ ይጠፋ
        rejection_key = (group_id, msg.reply_to_message.message_id)
        old_rejection_msg_id = _taken_rejection_msgs.pop(rejection_key, None)
        if old_rejection_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=old_rejection_msg_id)
            except Exception:
                pass

        # admin's own "እሺ ..." command message ይጠፋ
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        # አዲስ "NUM ተይዞልሃል 🙏" confirmation ለ user (reply-to ኦርጅናል message)
        numbers_label = " ".join(assigned)
        try:
            await msg.reply_to_message.reply_text(f"{numbers_label} ተይዞልሃል 🙏")
        except Exception as e:
            logging.warning(f"[Eshi] confirmation reply error: {e}")

        if errors:
            await _send_temp_admin_message(ctx.bot, group_id, f"❌ ያልተገኘ: {', '.join(errors)}")

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _refresh_board(ctx, fresh, group_id)
        return

    # ============================================================
    # OWNER REASSIGNMENT — "#/ NUM NUM+SLOT" ብቻ (ስላሽ አለው)፣ active
    # game ያስፈልገዋል (total_numbers ማረጋገጥ ስላለበት)
    # ============================================================
    settings = get_active_settings(group_id=group_id)
    if not settings:
        return
    game_id = settings["id"]

    parts = text[2:].strip().split()
    if not parts:
        await msg.reply_text("❌ ምሳሌ: #/ 01 21 31+1")
        return

    assigned = []
    errors = []

    for part in parts:
        slot_match = _re_owner.match(r'^(\d+)\+(\d+)$', part)
        if slot_match:
            number = int(slot_match.group(1))
            slot = int(slot_match.group(2))
        else:
            try:
                number = int(part.rstrip("+"))
            except ValueError:
                errors.append(part)
                continue
            slot = None

        if number < 1 or number > settings["total_numbers"]:
            errors.append(part)
            continue

        found = admin_set_owner(game_id, number, owner_id, slot=slot)
        if found:
            label = f"{number:02d}" + (f"+{slot}" if slot else "")
            assigned.append(label)
        else:
            errors.append(part)

    reply_lines = []
    if assigned:
        reply_lines.append(f"✅ {', '.join(assigned)} → ባለቤት ተስተካክሏል!")
    if errors:
        reply_lines.append(f"❌ ያልተገኘ: {', '.join(errors)}")

    if assigned:
        # ✅ ተቀባይነት ስላገኘ (ቢያንስ አንድ ቁጥር ስለተስተካከለ) admin's own
        # "#/ ..." message ይጠፋል — ልክ እንደ board reply
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        if reply_lines:
            # FIX #4: admin confirmation message ከ1.5-2 ሰከንድ በኋላ ራሱ ይጠፋል
            await _send_temp_admin_message(ctx.bot, group_id, "\n".join(reply_lines))
    elif reply_lines:
        # ምንም ካልተስተካከለ message እንዳለ ይቆያል (admin ምን እንደጻፈ እንዲያይ)
        await msg.reply_text("\n".join(reply_lines))


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def handle_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /remove 5  ወይም  /remove 5:1 10 15:2  ወይም  5+1 15+2")
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    per_person = settings["numbers_per_person"]
    removed = []
    errors = []

    for part in parts[1:]:
        try:
            if ":" in part:
                num_str, slot_str = part.split(":", 1)
                number = int(num_str)
                slot = int(slot_str)
            elif "+" in part:
                # ✅ FIX: NUM+SLOT (ለምሳሌ 5+1 ወይም 5+2) — ልክ እንደ /nekay slot መለያ
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = None
            # ✅ FIX: 1-5 ቡድን ቢሆን (numbers_per_person>1)፣ group start ይሆናል
            actual_num = get_group_start(number, per_person) if per_person > 1 else number
            admin_remove_player(settings["id"], actual_num, slot)
            label = f"{format_number(actual_num)}:{slot}" if slot else format_number(actual_num)
            removed.append(label)
        except ValueError:
            errors.append(part)

    # ✅ FIX: duplicate board — _check_all_paid_and_resend እዚህ መጠራት
    # የለበትም ነበር (ማስወገድ ውጤት "ሁሉም ተከፍሏል" ፈጽሞ ማምጣት ስለማይችል፣ ያንን
    # ይህ function ራሱ ካስፈለገ resend ስለሚያደርግ ከ _refresh_board's edit ጋር
    # ግጭት ውስጥ ገብቶ 2 board messages ይፈጥር ነበር)
    await _refresh_board(ctx, settings, group_id)

    msg = ""
    if removed:
        msg += f"✅ {', '.join(removed)} ተወጣ!"
    if errors:
        msg += f"\n❌ ያልተቀበለ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_paid_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /paid 5 10 15  ወይም  /paid 5:2  ወይም  5+2")
        return

    is_paid = update.message.text.startswith("/paid")
    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    per_person = settings["numbers_per_person"]
    updated = []
    errors = []

    for part in parts[1:]:
        try:
            if ":" in part:
                num_str, slot_str = part.split(":", 1)
                number = int(num_str)
                slot = int(slot_str)
            elif "+" in part:
                # ✅ FIX: NUM+SLOT (ለምሳሌ 5+1 ወይም 5+2) — ልክ እንደ /nekay slot መለያ
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = 1
            # ✅ FIX: 1-5 ቡድን ቢሆን (numbers_per_person>1)፣ group start ይሆናል
            actual_num = get_group_start(number, per_person) if per_person > 1 else number
            admin_mark_paid(settings["id"], actual_num, slot, is_paid)
            updated.append((actual_num, slot))

            if is_paid and _gk(group_id, settings["id"]) in nekay_active:
                snap = nekay_numbers.get(_gk(group_id, settings["id"]), {})
                if actual_num in snap:
                    del snap[actual_num]
                    nekay_numbers[_gk(group_id, settings["id"])] = snap
        except ValueError:
            errors.append(part)

    if is_paid and _gk(group_id, settings["id"]) in nekay_active:
        snap = nekay_numbers.get(_gk(group_id, settings["id"]), {})
        rem_msg_id = settings.get("remaining_message_id")
        if rem_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
            except Exception:
                pass
        if snap:
            from board import build_nekay
            nekay_list = _build_nekay_from_snap(snap)
            nekay_text = build_nekay(nekay_list)
            new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
            update_remaining_message_id(settings["id"], new_nekay.message_id)
        else:
            update_remaining_message_id(settings["id"], None)
            nekay_active.discard(_gk(group_id, settings["id"]))
            nekay_numbers.pop(_gk(group_id, settings["id"]), None)

    await _refresh_board(ctx, settings, group_id)

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)

    mark = "✅" if is_paid else "❌"
    updated_str = ", ".join(f"{format_number(n)}:{s}" for n, s in updated)
    msg = f"{mark} {updated_str} updated!"
    if errors:
        msg += f"\n❌ ያልተቀበለ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    # pre-booking mode — registrations ቀድሞ አሉ፣ board ብቻ ይላክ
    if group_id in prebooking_groups:
        prebooking_groups.discard(group_id)
        clear_prize_balance(group_id)

        # balance ካለው pre-booked registrations ✅ ያደርጋቸዋል
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT user_id FROM registrations
            WHERE game_id=%s AND is_paid=FALSE AND user_id != 0
        """, (settings["id"],))
        unpaid_users = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        for uid in unpaid_users:
            try:
                confirm_payment(uid, 0, group_id)
            except Exception:
                pass

        taken = get_taken_numbers(settings["id"])
        paid = get_paid_numbers(settings["id"])
        board_text = build_board(settings, taken, paid)
        rem_msg_id = settings.get("remaining_message_id")
        if rem_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
            except Exception:
                pass
        new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
        update_board_message_id(settings["id"], new_msg.message_id)
        update_remaining_message_id(settings["id"], None)
        await update.message.reply_text("✅ አዲስ ጨዋታ ተጀምሯል!")
        return

    clear_prize_balance(group_id)
    clear_carry_balance(group_id)
    clear_game(settings["id"])
    nekay_active.discard(_gk(group_id, settings["id"]))
    admin_nekay_games.discard(_gk(group_id, settings["id"]))
    active_countdowns.pop(_gk(group_id, settings["id"]), None)
    nekay_numbers.pop(_gk(group_id, settings["id"]), None)
    countdown_done.discard(_gk(group_id, settings["id"]))
    handled_video_boards.discard(_gk(group_id, settings["id"]))
    _stop_inactivity_tracker(settings["id"], group_id)
    clear_all_context_for_group(group_id)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
        except Exception:
            pass

    board_text = build_board(settings, {}, {})
    new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
    update_board_message_id(settings["id"], new_msg.message_id)
    update_remaining_message_id(settings["id"], None)

    await update.message.reply_text("✅ አዲስ ጨዋታ ተጀምሯል!")


async def handle_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 3:
        await update.message.reply_text("❌ ምሳሌ: /register 5 አበበ  ወይም  /register 5 10 15+ አበበ")
        return

    user_name = parts[-1]
    number_parts = parts[1:-1]

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    per_person = settings["numbers_per_person"]
    registered = []
    failed = []

    for part in number_parts:
        is_half = part.endswith("+")
        part_clean = part.rstrip("+")
        try:
            num = int(part_clean)
        except ValueError:
            failed.append(part)
            continue

        actual_num = get_group_start(num, per_person) if per_person > 1 else num
        if actual_num < 1 or actual_num > settings["total_numbers"]:
            failed.append(part)
            continue

        is_nekay = _gk(group_id, settings["id"]) in nekay_numbers and actual_num in nekay_numbers.get(_gk(group_id, settings["id"]), {})
        result = register_number(settings["id"], 0, user_name, actual_num, is_half, force=is_nekay)
        if result in ["registered", "registered_half"]:
            registered.append((actual_num, is_half))
        else:
            failed.append(format_number(num))

    if not registered:
        if failed:
            await update.message.reply_text(f"❌ {', '.join(failed)} ቀድሞ ተወስዷል!")
        return

    await _refresh_board(ctx, settings, group_id)

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)

    reg_list = ", ".join(format_number(n) + ("+" if h else "") for n, h in registered)
    msg = f"✅ {reg_list} → {user_name} ተመዘገበ!"
    if failed:
        msg += f"\n❌ {', '.join(failed)} ቀድሞ ተወስዷል!"
    await update.message.reply_text(msg)


# ============================================================
# MULTI-GROUP COMMANDS
# ============================================================

async def handle_enable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            gname = update.effective_chat.title or str(gid)
            enable_group(gid, gname)
            await update.message.reply_text(f"✅ Group {gname} enabled!")
            return
        await update.message.reply_text("❌ ምሳሌ: /enable -100123456789")
        return

    try:
        gid = int(parts[1])
        enable_group(gid)
        await update.message.reply_text(f"✅ Group {gid} enabled!")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር ብቻ ጻፍ!")


async def handle_disable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            disable_group(gid)
            await update.message.reply_text(f"✅ Group {gid} disabled!")
            return
        await update.message.reply_text("❌ ምሳሌ: /disable -100123456789")
        return

    try:
        gid = int(parts[1])
        disable_group(gid)
        await update.message.reply_text(f"✅ Group {gid} disabled!")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር ብቻ ጻፍ!")


async def handle_enablelist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    groups = get_enabled_groups()
    if not groups:
        await update.message.reply_text("📋 Enabled group የለም።")
        return

    lines = ["📋 Enabled Groups:\n"]
    for i, g in enumerate(groups, 1):
        name = g["group_name"] or "Unknown"
        enabled_at = g["enabled_at"].strftime("%Y-%m-%d %H:%M") if g["enabled_at"] else "?"
        lines.append(f"{i}. {name}\n   ID: {g['group_id']}\n   Enabled: {enabled_at}")

    await update.message.reply_text("\n\n".join(lines))


async def handle_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /addadmin 123456789")
        return

    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("❌ Group ID ያስፈልጋል: /addadmin USER_ID GROUP_ID")
            return
        add_group_admin(gid, admin_id)
        await update.message.reply_text(f"✅ {admin_id} group admin ሆኗል!")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ ትክክለኛ ID ጻፍ!")


async def handle_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /removeadmin 123456789")
        return
    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("❌ Group ID ያስፈልጋል")
            return
        remove_group_admin(gid, admin_id)
        await update.message.reply_text(f"✅ {admin_id} admin ተወጣ!")
    except ValueError:
        await update.message.reply_text("❌ ትክክለኛ ID ጻፍ!")


async def handle_userlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return

    if not group_id:
        await update.message.reply_text("❌ Group ውስጥ ብቻ ይሰራል!")
        return

    users = get_usernames(group_id)
    if not users:
        await update.message.reply_text("📋 Username የለም።")
        return

    lines = [f"👥 Members ({len(users)} total):\n"]
    for u in users:
        badge = "🆕" if not u["is_read"] else "  "
        lines.append(f"{badge} @{u['username']}")

    await update.message.reply_text("\n".join(lines))
    mark_usernames_read(group_id)


async def handle_clearusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return
    if not group_id:
        await update.message.reply_text("❌ Group ውስጥ ብቻ ይሰራል!")
        return
    clear_usernames(group_id)
    await update.message.reply_text("✅ Username list ጸዳ!")


async def handle_activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    activities = get_activity()
    if not activities:
        await update.message.reply_text("📊 Activity data የለም።")
        return

    lines = ["📊 Group Activity:\n"]
    for a in activities:
        name = a.get("group_name") or str(a["group_id"])
        last = a["last_active"].strftime("%m/%d %H:%M") if a["last_active"] else "?"
        lines.append(
            f"📌 {name}\n"
            f"   💬 Messages: {a['messages'] or 0}\n"
            f"   📝 Registrations: {a['registrations'] or 0}\n"
            f"   💰 Payments: {a['payments'] or 0}\n"
            f"   🕐 Last active: {last}"
        )

    await update.message.reply_text("\n\n".join(lines))


async def handle_dbstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    statuses = get_db_status()
    lines = ["🗄️ Database Status:\n"]
    for s in statuses:
        if s.get("error"):
            lines.append(f"DB{s['index']}: ❌ Error")
            continue
        active = "🟢 ACTIVE" if s["is_active"] else ("🔴 FULL" if s["is_full"] else "⚪ Standby")
        lines.append(
            f"DB{s['index']}: {active}\n"
            f"   Rows: {s['row_count']:,} / {s['limit']:,} ({s['percent']}%)"
        )

    await update.message.reply_text("\n\n".join(lines))


async def handle_dbclear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /dbclear 2  (DB2 ያጸዳል)")
        return

    try:
        db_num = int(parts[1])
        clear_db_data(db_num)
        await update.message.reply_text(f"✅ DB{db_num} ጸዳ! (usernames ይቀራሉ)")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")


async def handle_winners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != "private":
        group_id = update.effective_chat.id
        if not is_admin(user_id, group_id):
            return
    else:
        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

    winners = get_recent_winners(group_id, hours=24)

    if not winners:
        await update.message.reply_text("🏆 Last 24hr winners የሉም።")
        return

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 Last 24hr Winners:\n"]
    for w in winners:
        medal = medals.get(w["place"], "🎖️")
        balance = w["balance"]
        sent_mark = "✅" if w["sent"] else "⚠️ ያልተላከ"
        time_str = w["created_at"].strftime("%H:%M") if w["created_at"] else "?"
        line = f"{medal} {w['place']}ኛ: {w['user_name']} — ETB {w['prize']} {sent_mark}"
        if balance > 0:
            line += f"\n   💳 ቀሪ balance: ETB {balance}"
        line += f"\n   🕐 {time_str}"
        lines.append(line)

    await update.message.reply_text("\n\n".join(lines))

    try:
        cleanup_old_winners()
    except Exception:
        pass


async def handle_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    set_group_active(group_id, True)
    await update.message.reply_text("✅ Bot on ሆኗል!")


async def handle_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    set_group_active(group_id, False)
    await update.message.reply_text("🔴 Bot off ሆኗል!")


async def handle_clearbalance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != "private":
        group_id = update.effective_chat.id
        if not is_admin(user_id, group_id):
            return
    else:
        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

    parts = update.message.text.strip().split()

    if len(parts) == 1:
        clear_balance_all(group_id)
        await update.message.reply_text("✅ ሁሉም balance ጸዳ!")
    else:
        username = parts[1].lstrip("@")
        success = clear_balance_by_username(group_id, username)
        if success:
            await update.message.reply_text(f"✅ @{username} balance ጸዳ!")
        else:
            await update.message.reply_text(f"❌ @{username} አልተገኘም!")


async def handle_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
        return

    report = get_report(group_id)
    lines = ["📊 Report (Last 24hr)\n"]

    if report["games_count"] > 0:
        lines.append(
            f"🎮 ጨዋታዎች: {report['games_count']}\n"
            f"💰 Total bet: ETB {report['total_bet']:,.0f}\n"
            f"🏆 Prize total: ETB {report['prize_total']:,.0f}\n"
            f"📈 Profit: ETB {report['profit']:,.0f}"
        )
    else:
        lines.append("🎮 ዛሬ ጨዋታ አልተጫወተም")

    active = report.get("active")
    if active:
        lines.append("\n⚡ Active Game (Real-time)")
        lines.append(f"📝 Registered: {active['total_slots']}")
        if active["counted"]:
            lines.append(
                f"💰 Total bet: ETB {active['total_bet']:,.0f}\n"
                f"🏆 Prize: ETB {active['prize_total']:,.0f}\n"
                f"📈 Profit: ETB {active['profit']:,.0f}"
            )
        else:
            lines.append(f"⚠️ 15+ ሲሆን profit ይታያል ({active['total_slots']}/15)")

    await update.message.reply_text("\n".join(lines))

    try:
        cleanup_old_reports()
    except Exception:
        pass


async def handle_setwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ ምሳሌ: /setwarnmedia 2\n"
            "ከዛ photo/video/sticker ይላኩ\n"
            "Available: 0.5, 1, 2, 3, 5, 10 ደቂቃ"
        )
        return

    try:
        mins = float(parts[1])
        if mins < 0.5 or mins > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ 0.5 እስከ 10 ብቻ!")
        return

    ctx.user_data["setwarn_minutes"] = mins
    await update.message.reply_text(
        f"✅ {mins} ደቂቃ ተዘጋጅቷል!\n"
        f"አሁን photo/video/sticker/gif ይላኩ"
    )


async def handle_warnmedia_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    if ctx.user_data.get("awaiting_complete_sticker"):
        await handle_complete_sticker_upload(update, ctx)
        return

    mins = ctx.user_data.get("setwarn_minutes")
    if not mins:
        return

    msg = update.message
    file_id = None
    media_type = "photo"

    if msg.photo:
        file_id = msg.photo[-1].file_id
        media_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        media_type = "video"
    elif msg.animation:
        file_id = msg.animation.file_id
        media_type = "animation"
    elif msg.sticker:
        file_id = msg.sticker.file_id
        media_type = "sticker"
    elif msg.document:
        file_id = msg.document.file_id
        media_type = "video"

    if not file_id:
        return

    set_warning_media(mins, file_id, media_type, update.effective_user.id)
    ctx.user_data.pop("setwarn_minutes", None)
    await msg.reply_text(f"✅ {mins} ደቂቃ warning media ተቀምጧል! ({media_type})")


async def handle_listwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    medias = get_all_warning_media()
    if not medias:
        await update.message.reply_text("📋 Warning media የለም።")
        return

    lines = ["📋 Warning Media:\n"]
    for m in medias:
        lines.append(f"⏱️ {m['minutes']} ደቂቃ — {m['media_type']}")

    await update.message.reply_text("\n".join(lines))


async def handle_deletewarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /deletewarnmedia 2")
        return

    try:
        mins = float(parts[1])
        delete_warning_media(mins)
        await update.message.reply_text(f"✅ {mins} ደቂቃ warning media ጠፋ!")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")


# ============================================================
# PHOTO HANDLER
# ============================================================

async def handle_group_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_group_enabled(group_id):
        return

    if not is_group_active(group_id):
        return

    if is_main_admin(user_id) and ctx.user_data.get("setwarn_minutes"):
        await handle_warnmedia_upload(update, ctx)
        return

    if is_admin(user_id, group_id):
        settings = get_active_settings(group_id=group_id)
        if settings:
            photo_uid = update.message.photo[-1].file_unique_id
            # ✅ used ፎቶ ከሆነ (ቀድሞ real winner አምጥቶ የነበረ) AI ጨርሶ አንጠራም
            if photo_uid in handled_winner_photos or is_winner_photo_used(photo_uid):
                return

            winner_found = await handle_winner_photo(ctx.bot, update.message, settings, group_id=group_id)
            if winner_found:
                # ✅ winner ሲገኝ ብቻ ነው "used" የሚደረገው — not-lottery/failed ፎቶ
                # ድጋሚ መላክ ቢቻል (retry) እንዲኖር used አይደረግም
                handled_winner_photos.add(photo_uid)
                save_winner_photo(photo_uid, group_id=group_id)
                # announcement ወዲያውኑ ተላከ — board 30 seconds ቆይቶ ይምጣ
                winner_pending_groups.add(group_id)
                try:
                    await asyncio.sleep(30)
                    await _auto_newgame(ctx.bot, settings, group_id)
                finally:
                    winner_pending_groups.discard(group_id)
        return

    _increment_counter(group_id)
    settings = get_active_settings(group_id=group_id)
    game_id = settings["id"] if settings else None

    if update.effective_user.username:
        try:
            track_username(group_id, update.effective_user.username)
        except Exception:
            pass

    photo_processing[group_id] = True

    async def _nekay_cb(confirmed):
        if game_id:
            await nekay_payment_cb(ctx.bot, game_id, update.effective_user.id, confirmed, group_id=group_id)

    try:
        await handle_payment_photo(ctx.bot, update.message, nekay_cb=_nekay_cb, group_id=group_id)
    finally:
        photo_processing[group_id] = False
        queued = pending_registrations.pop(group_id, [])
        for (q_user_id, q_user_name, q_text, q_msg) in queued:
            settings2 = get_active_settings(group_id=group_id)
            if not settings2:
                continue
            price_full2 = float(settings2.get("price_full") or 0)
            price_half2 = float(settings2.get("price_half") or 0)
            result = parse_numbers(q_text, price_full=price_full2, price_half=price_half2)
            if not result:
                continue
            numbers = result["numbers"]
            ambiguous = result["ambiguous"]
            ambiguous_number = result["ambiguous_number"]
            if ambiguous:
                pending_ambiguous[q_user_id] = {
                    "numbers": numbers, "ambiguous": ambiguous,
                    "ambiguous_number": ambiguous_number,
                    "game_id": settings2["id"], "settings": settings2,
                    "group_id": group_id, "user_name": q_user_name
                }
                # FIX: መጀመሪያ እንደተጻፈው ወዲያውኑ ይመዘገባል፣ ጥያቄው ከዚያ በኋላ ብቻ
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)
                if ambiguous == "all_half":
                    await q_msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
                elif ambiguous == "last_half":
                    await q_msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
            else:
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _check_all_paid_and_resend(ctx.bot, fresh, group_id)


# ============================================================
# DAILY PROFIT: ጨዋታው ካለቀ (ሁሉም ✅ ሆነው) በኋላ admin በ /setgame ላይ
# ካስገባው profit_per_game (ቋሚ ቁጥር) ውጪ ምንም ስሌት አይደረግም። 1 ጨዋታ = 1 ጊዜ
# profit_per_game ይደመራል። ትሪገር ሁለት ቦታ ነው (የትኛውም መጀመሪያ ቢደርስ)፦
#   1) ሁሉም ✅ ሆነው live/pre-booking ሲጀምር (handle_video_chat_started)
#   2) Live ካልተጠቀሙ፣ ሁሉም ✅ ሆነው ውጤት (winner photo) ሲላክ (_auto_newgame)
# profit_counted_games (in-memory set) ተመሳሳይ game_id ድጋሚ እንዳይቆጠር ይጠብቃል።
# ============================================================

def _maybe_record_game_profit(group_id: int, game_id: int, settings: dict):
    if _gk(group_id, game_id) in profit_counted_games:
        return
    try:
        if not all_numbers_paid(game_id, settings):
            return
        profit_per_game = float(settings.get("profit_per_game") or 0)
        taken = get_taken_numbers(game_id)
        registered_count = len(taken)
        save_game_report(
            group_id=group_id,
            game_id=game_id,
            total_bet=0,
            prize_total=0,
            profit=profit_per_game,
            registered_count=registered_count,
        )
        profit_counted_games.add(_gk(group_id, game_id))
    except Exception as e:
        logging.warning(f"[DailyProfit] Record error: {e}")


async def _auto_newgame(bot, settings: dict, group_id: int = None):
    game_id = settings["id"]
    _group_id = group_id or settings.get("group_id") or GROUP_ID

    if _group_id:
        _maybe_record_game_profit(_group_id, game_id, settings)

    nekay_active.discard(_gk(_group_id, game_id))
    admin_nekay_games.discard(_gk(_group_id, game_id))
    active_countdowns.pop(_gk(_group_id, game_id), None)
    nekay_numbers.pop(_gk(_group_id, game_id), None)
    countdown_done.discard(_gk(_group_id, game_id))
    handled_video_boards.discard(_gk(_group_id, game_id))
    _stop_inactivity_tracker(game_id, _group_id)
    clear_all_context_for_group(_group_id)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await bot.delete_message(chat_id=_group_id, message_id=rem_msg_id)
        except Exception:
            pass

    # pre-booking mode — registrations ቀድሞ አሉ፣ board ብቻ ይላክ
    if _group_id in prebooking_groups:
        prebooking_groups.discard(_group_id)
        clear_prize_balance(_group_id)

        # balance ካለው pre-booked registrations ✅ ያደርጋቸዋል
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT user_id FROM registrations
            WHERE game_id=%s AND is_paid=FALSE AND user_id != 0
        """, (game_id,))
        unpaid_users = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        for uid in unpaid_users:
            try:
                confirm_payment(uid, 0, _group_id)
            except Exception:
                pass

        taken = get_taken_numbers(game_id)
        paid = get_paid_numbers(game_id)
        board_text = build_board(settings, taken, paid)
        new_msg = await bot.send_message(chat_id=_group_id, text=board_text)
        update_board_message_id(game_id, new_msg.message_id)
        update_remaining_message_id(game_id, None)
        return

    clear_prize_balance(_group_id)
    clear_carry_balance(_group_id)
    clear_game(game_id)
    board_text = build_board(settings, {}, {})
    new_msg = await bot.send_message(chat_id=_group_id, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    update_remaining_message_id(game_id, None)


# ============================================================
# /send CONVERSATION
# ============================================================

async def send_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("❌ Private chat ብቻ ነው!")
        return ConversationHandler.END

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
        return ConversationHandler.END

    ctx.user_data["send_group_id"] = group_id
    return await _send_show_places(update, ctx, group_id)


async def _send_show_places(update, ctx, group_id: int):
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return ConversationHandler.END

    ctx.user_data["send_settings"] = settings

    prize_1st = settings.get("prize_1st", 0)
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")

    lines = ["💸 ለማን ብር ትልካለህ?"]
    lines.append(f"1 — 1ኛ winner (prize: {prize_1st} ብር)")
    if prize_2nd:
        lines.append(f"2 — 2ኛ winner (prize: {prize_2nd} ብር)")
    if prize_3rd:
        lines.append(f"3 — 3ኛ winner (prize: {prize_3rd} ብር)")
    lines.append("\n(1, 2, ወይም 3 ጻፍ)")

    await update.message.reply_text("\n".join(lines))
    return ASK_SEND_PLACE


async def send_ask_place(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text not in ("1", "2", "3"):
        await update.message.reply_text("❌ 1, 2, ወይም 3 ብቻ ጻፍ!")
        return ASK_SEND_PLACE

    place = int(text)
    settings = ctx.user_data.get("send_settings")
    group_id = ctx.user_data.get("send_group_id")

    if not settings:
        settings = get_active_settings(group_id=group_id)
    if not settings:
        return ConversationHandler.END

    winners = get_winners_by_place(settings["id"], place)
    if not winners:
        await update.message.reply_text(f"❌ {place}ኛ winner አልተመዘገበም!")
        return ConversationHandler.END

    ctx.user_data["send_place"] = place
    ctx.user_data["send_game_id"] = settings["id"]

    if len(winners) == 1:
        winner = winners[0]
        ctx.user_data["send_telegram_id"] = winner["telegram_id"]
        ctx.user_data["send_user_name"] = winner["user_name"]

        balance = winner.get("balance", 0)
        await update.message.reply_text(
            f"👤 {place}ኛ: {winner['user_name']}\n"
            f"💳 አሁን balance: ETB {balance}\n\n"
            f"💸 ስንት ብር ላካህ? (ቁጥር ጻፍ)"
        )
        return ASK_SEND_AMOUNT

    ctx.user_data["send_winners_list"] = winners
    lines = [f"⚠️ {place}ኛ ቦታ ላይ {len(winners)} ሰው አለ (tie)፦\n"]
    for i, w in enumerate(winners, 1):
        bal = w.get("balance", 0)
        lines.append(f"{i}. {w['user_name']} (balance: ETB {bal})")
    lines.append("\nማንን ትልካለህ? ቁጥር ጻፍ (1, 2, ...)")
    await update.message.reply_text("\n".join(lines))
    return ASK_SEND_WINNER


async def send_ask_winner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    winners = ctx.user_data.get("send_winners_list") or []

    try:
        idx = int(text)
        if idx < 1 or idx > len(winners):
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"❌ 1 እስከ {len(winners)} ቁጥር ብቻ ጻፍ!")
        return ASK_SEND_WINNER

    winner = winners[idx - 1]
    place = ctx.user_data.get("send_place")
    ctx.user_data["send_telegram_id"] = winner["telegram_id"]
    ctx.user_data["send_user_name"] = winner["user_name"]

    balance = winner.get("balance", 0)
    await update.message.reply_text(
        f"👤 {place}ኛ: {winner['user_name']}\n"
        f"💳 አሁን balance: ETB {balance}\n\n"
        f"💸 ስንት ብር ላካህ? (ቁጥር ጻፍ)"
    )
    return ASK_SEND_AMOUNT


async def send_ask_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ ትክክለኛ ቁጥር ጻፍ!")
        return ASK_SEND_AMOUNT

    place = ctx.user_data["send_place"]
    telegram_id = ctx.user_data["send_telegram_id"]
    user_name = ctx.user_data["send_user_name"]
    game_id = ctx.user_data["send_game_id"]
    group_id = ctx.user_data.get("send_group_id")

    result = deduct_winner_balance(game_id, telegram_id, amount, group_id=group_id)
    new_balance = result["new_balance"]

    mark_winner_sent(game_id, telegram_id, amount)

    try:
        if group_id:
            log_transaction(
                group_id=group_id, game_id=game_id,
                telegram_id=telegram_id, amount=-amount,
                reason="winner_sent", done_by="admin",
                balance_after=new_balance,
            )
    except Exception as _log_err:
        logging.warning(f"[log_transaction] Error: {_log_err}")

    place_label = {1: "1ኛ", 2: "2ኛ", 3: "3ኛ"}.get(place, f"{place}ኛ")

    lines = [
        f"✅ {place_label} winner: {user_name}",
        f"💸 የላካህ: ETB {amount}",
        f"💳 ቀሪ balance: ETB {new_balance}",
    ]
    await update.message.reply_text("\n".join(lines))

    if group_id:
        try:
            announcement = (
                f"💸 {place_label} winner ብር ተላከ!\n"
                f"👤 {user_name}\n"
                f"💰 ETB {amount}"
            )
            await ctx.bot.send_message(chat_id=group_id, text=announcement)
        except Exception:
            pass

    settings = ctx.user_data.get("send_settings")
    if settings:
        await _refresh_board(ctx, settings, group_id)

    return ConversationHandler.END


async def cancel_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ /send ተሰርዟል።")
    return ConversationHandler.END


# ============================================================
# /status
# ============================================================

async def handle_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != "private":
        group_id = update.effective_chat.id
        if not is_admin(user_id, group_id):
            return
    else:
        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

    is_main = is_main_admin(user_id)

    text = (
        "🤖 Commands:\n\n"
        "🎮 *Game*\n"
        "/setgame — አዲስ game settings ያቀናብራል\n"
        "/newgame — ቁጥሮችን ጠርጎ አዲስ ጨዋታ ይጀምራል\n"
        "/setcountdown 2 — countdown ደቂቃ ይቀይራል (0=አጥፋ)\n"
        "/showslots on/off — sub-slots ላይ ስም ያሳያል/ያጠፋል\n"
        "/nekay 5 10+ 15 — manually ነቃይ ያደርጋል\n"
        "/status — ሁሉንም commands ያሳያል\n\n"
        "👤 *ምዝገባ*\n"
        "/register 5 10+ አበበ — ቁጥር manually ይመዘግባል\n"
        "  • + = ግማሽ (ለምሳሌ 5+)\n\n"
        "💰 *ክፍያ*\n"
        "/paid 5 10 15 — ብዙ ቁጥሮች paid ያደርጋል\n"
        "/paid 5:2 — slot 2 paid ያደርጋል\n"
        "/unpaid 5 10 — ብዙ ቁጥሮች unpaid ያደርጋል\n\n"
        "🗑️ *አስተዳደር*\n"
        "/remove 5 — ቁጥር ከ board ያስወጣል\n"
        "/remove 5:1 — slot 1 ብቻ ያስወጣል\n"
        "/on — Bot ያስነሳል\n"
        "/off — Bot ያቆማል\n"
        "/clearbalance — ሁሉም balance ያጸዳል\n"
        "/clearbalance @username — አንድ user balance ያጸዳል\n\n"
        "👥 *Members*\n"
        "/userlist — username ዝርዝር\n"
        "/clearusers — username list ያጸዳል\n\n"
        "📊 *Report*\n"
        "/report — real-time profit + games (last 24hr)\n\n"
        "🏆 *Winner*\n"
        "/winners — last 24hr winners\n"
        "/send — winner ብር ይላካል (private chat ብቻ)\n\n"
        "💸 *Winner Auto-Sender (userbot2)*\n"
        "/setwinnerapi api_id api_hash — winner API ያስቀምጣል (main admin)\n"
        "/startsession2 +phone — winner session ይጀምራል (private chat)\n"
        "/verifycode2 +phone code — session ያረጋግጣል\n"
        "/verify2fa2 +phone password — 2FA ካለ\n"
        "/listsessions2 — group ይህ sessions ዝርዝር\n"
        "/removesession2 +phone — session ያስወግዳል\n\n"
        "✏️ *Manual Board Edit*\n"
        "Board copy አርጎ edit አርጎ bot message ላይ reply አርግ\n"
        "Bot automatically ይቀይረዋል!\n"
    )

    if is_main:
        text += (
            "\n🔧 *Main Admin*\n"
            "/enable — group ያስነሳል\n"
            "/disable — group ያጠፋል\n"
            "/enablelist — enabled groups ዝርዝር\n"
            "/addadmin USER_ID — group admin ይጨምራል\n"
            "/removeadmin USER_ID — group admin ያስወጣል\n"
            "/activity — group activity ያሳያል\n"
            "/dbstatus — DB status ያሳያል\n"
            "/dbclear N — DBN ያጸዳል (username ሳይነካ)\n"
            "/setwarnmedia 2 — warning media ያስቀምጣል\n"
            "/listwarnmedia — warning media ዝርዝር\n"
            "/deletewarnmedia 2 — warning media ያጸዳል\n"
            "/setcompletesticker — ሁሉም ✅ ሲሆን sticker ያስቀምጣል\n"
            "/listcompletestickers — complete stickers ዝርዝር\n"
            "/removecompletesticker N — sticker #N ያስወጣል\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

async def handle_admin_group_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group ላይ 30+ seconds video ሲልክ → ቀደም ያለውን board ይሰርዛል፣
    አዲሱን board ከታች ይላካል (አንድ ጊዜ ብቻ per game)
    """
    msg = update.message
    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_admin(user_id, group_id):
        return
    if not is_group_enabled(group_id):
        return
    if not is_group_active(group_id):
        return

    video = msg.video or msg.document
    if not video:
        return

    # duration check — 30 seconds+
    duration = getattr(video, "duration", None)
    if not duration or duration < 30:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    game_id = settings["id"]

    # አንድ ጊዜ ብቻ per game
    if _gk(group_id, game_id) in handled_video_boards:
        return
    handled_video_boards.add(_gk(group_id, game_id))

    # ቀደም ያለውን board ይሰርዝ
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
        except Exception:
            pass

    # አዲሱን board ከታች ይላክ
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    logging.info(f"[VideoBoard] Group {group_id} game {game_id} board replaced after 30s+ video")


async def handle_video_chat_started(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin live ሲጀምር + ሁሉም ቁጥሮች ✅ ከሆኑ → silent pre-booking mode ይጀምር።
    Board አይላክም፣ ሰዎች ቁጥር መያዝ ይችላሉ፣ /newgame ሲል board ይታያል።
    """
    group_id = update.effective_chat.id

    if not is_group_enabled(group_id):
        return
    if not is_group_active(group_id):
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    if not all_numbers_paid(settings["id"], settings):
        return

    game_id = settings["id"]

    # FIX: daily profit — ሁሉም ✅ ሆነው live ሲጀምር 1 ጨዋታ ተብሎ profit_per_game
    # ይመዘገባል (registrations ከመጥፋታቸው በፊት)
    _maybe_record_game_profit(group_id, game_id, settings)

    # ✅ FIX: registrations ከመጥፋቱ በፊት snapshot ያድርግ — winner photo
    # ገና ውጤቱ ካልታወቀ (ገና admin ካልላከው) በፊት pre-booking ቢጀምር፣ winner
    # lookup snapshot ላይ ተመልክቶ ትክክለኛውን ባለቤት ማግኘት ይችላል
    save_registrations_snapshot(game_id)

    # silently clear registrations only (game_settings row ይቀራል)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations WHERE game_id=%s", (game_id,))
    cur.execute("DELETE FROM sms_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    cur.execute("DELETE FROM screenshot_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

    # ✅ ያለቀው ጨዋታ carry_balance እዚህ ጋር ይጸዳል (እውነተኛው ጨዋታ ያለቀበት ቦታ) —
    # pre-booking round ራሱ ገና ስላልጀመረ፣ ከዚህ በኋላ የሚገባ ገንዘብ ሁሉ ለአዲሱ ዙር
    # ንፁህ (ካለፈው ጨዋታ ቀሪ ሳይቀላቀል) ይሆናል
    clear_carry_balance(group_id)

    # in-memory state reset
    nekay_active.discard(_gk(group_id, game_id))
    admin_nekay_games.discard(_gk(group_id, game_id))
    active_countdowns.pop(_gk(group_id, game_id), None)
    nekay_numbers.pop(_gk(group_id, game_id), None)
    countdown_done.discard(_gk(group_id, game_id))
    _stop_inactivity_tracker(game_id, group_id)

    # pre-booking mode ይጀምር
    prebooking_groups.add(group_id)
    logging.info(f"[PreBooking] Group {group_id} entered pre-booking mode (live started, all paid)")

    # pre-booking media ይላካ (sticker/photo/video announcement)
    medias = get_prebooking_media()
    for m in medias:
        try:
            mtype = m["media_type"]
            fid = m["file_id"]
            if mtype == "photo":
                await ctx.bot.send_photo(chat_id=group_id, photo=fid)
            elif mtype == "video":
                await ctx.bot.send_video(chat_id=group_id, video=fid)
            elif mtype == "animation":
                await ctx.bot.send_animation(chat_id=group_id, animation=fid)
            elif mtype == "sticker":
                await ctx.bot.send_sticker(chat_id=group_id, sticker=fid)
            await asyncio.sleep(1)
        except Exception as e:
            logging.warning(f"[PreBooking] Media send error: {e}")


async def handle_my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        try:
            register_group(chat.id, chat.title)
        except Exception:
            pass


# ============================================================
# SMS ENDPOINT
# ============================================================

async def sms_endpoint(request):
    try:
        group_id = request.match_info.get("group_id")
        if group_id:
            try:
                group_id = int(group_id)
            except ValueError:
                group_id = None

        # bot off ሲሆን SMS ምንም አያስኬድ
        if group_id and not is_group_active(group_id):
            return web.json_response({"success": False, "reason": "bot_off"})

        raw = await request.text()
        try:
            parsed = json.loads(raw)
            sms_text = parsed.get("sms", raw)
        except Exception:
            sms_text = raw

        if not sms_text:
            return web.json_response({"success": False, "reason": "empty_body"})

        result = await handle_sms_webhook(
            sms_text,
            bot=_bot_instance,
            nekay_cb=_make_nekay_cb(group_id),
            group_id=group_id,
        )
        return web.json_response(result)
    except Exception as e:
        logging.error(f"[SMS Endpoint] Error: {e}", exc_info=True)
        return web.json_response({"success": False, "reason": "server_error"}, status=500)


async def health_check(request):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return web.Response(text=f"🤖 Bot is running!\n🕐 Server time: {now}")


_bot_instance = None


def _make_nekay_cb(group_id: int = None):
    async def _nekay_cb(confirmed):
        settings = get_active_settings(group_id=group_id)
        if settings and _bot_instance:
            await nekay_payment_cb(_bot_instance, settings["id"], 0, confirmed, group_id=group_id)
    return _nekay_cb


async def start_server():
    web_app = web.Application()
    web_app.router.add_post("/sms/{group_id}", sms_endpoint)
    web_app.router.add_get("/", health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("🌐 SMS Server started on port 8080")
    print("📱 SMS endpoint: /sms/{group_id}")


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()
    init_userbot_db()
    init_userbot2_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    register_userbot_handlers(app)
    register_userbot2_handlers(app, app.bot)

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setgame", setgame_start)],
        states={
            ASK_TOTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_total)],
            ASK_PER_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_per_person)],
            ASK_PRICE_FULL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_price_full)],
            ASK_PRICE_HALF: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_price_half)],
            ASK_PRIZE_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_prize_1)],
            ASK_PRIZE_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_prize_2)],
            ASK_PRIZE_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_prize_3)],
            ASK_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payment)],
            ASK_GAME_RULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_game_rule)],
            ASK_SLOT_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_slot_symbol)],
            ASK_COUNTDOWN_ENABLED: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_countdown_enabled)],
            ASK_COUNTDOWN_MINUTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_countdown_minutes)],
            ASK_PROFIT_PER_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_profit_per_game)],
        },
        fallbacks=[CommandHandler("cancel", cancel_setup)],
    )

    send_conv = ConversationHandler(
        entry_points=[CommandHandler("send", send_start)],
        states={
            ASK_SEND_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_ask_place)],
            ASK_SEND_WINNER: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_ask_winner)],
            ASK_SEND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_ask_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel_send)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(setup_conv)
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("register", handle_register))
    app.add_handler(CommandHandler("remove", handle_remove))
    app.add_handler(CommandHandler("paid", handle_paid_cmd))
    app.add_handler(CommandHandler("unpaid", handle_paid_cmd))
    app.add_handler(CommandHandler("newgame", handle_newgame))
    app.add_handler(CommandHandler("setcountdown", handle_setcountdown))
    app.add_handler(CommandHandler("showslots", handle_showslots))
    app.add_handler(CommandHandler("nekay", handle_nekay_cmd))
    app.add_handler(CommandHandler("setcompletesticker", handle_setcompletesticker))
    app.add_handler(CommandHandler("listcompletestickers", handle_listcompletestickers))
    app.add_handler(CommandHandler("removecompletesticker", handle_removecompletesticker))
    app.add_handler(CommandHandler("setprebookingmedia", handle_setprebookingmedia))
    app.add_handler(CommandHandler("listprebookingmedia", handle_listprebookingmedia))
    app.add_handler(CommandHandler("removeprebookingmedia", handle_removeprebookingmedia))

    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        handle_prebooking_media_upload
    ))
    app.add_handler(MessageHandler(
        filters.VIDEO & filters.ChatType.PRIVATE,
        handle_prebooking_media_upload
    ))
    app.add_handler(MessageHandler(
        filters.ANIMATION & filters.ChatType.PRIVATE,
        handle_prebooking_media_upload
    ))
    app.add_handler(MessageHandler(
        filters.Sticker.ALL & filters.ChatType.PRIVATE,
        handle_prebooking_media_upload
    ))
    app.add_handler(send_conv)

    app.add_handler(CommandHandler("enable", handle_enable))
    app.add_handler(CommandHandler("disable", handle_disable))
    app.add_handler(CommandHandler("enablelist", handle_enablelist))
    app.add_handler(CommandHandler("addadmin", handle_addadmin))
    app.add_handler(CommandHandler("removeadmin", handle_removeadmin))
    app.add_handler(CommandHandler("activity", handle_activity))
    app.add_handler(CommandHandler("dbstatus", handle_dbstatus))
    app.add_handler(CommandHandler("dbclear", handle_dbclear))

    app.add_handler(CommandHandler("userlist", handle_userlist))
    app.add_handler(CommandHandler("clearusers", handle_clearusers))
    app.add_handler(CommandHandler("winners", handle_winners))
    app.add_handler(CommandHandler("on", handle_on))
    app.add_handler(CommandHandler("off", handle_off))
    app.add_handler(CommandHandler("clearbalance", handle_clearbalance))
    # NEW: winner "🔥 reaction" balance-clear feature
    app.add_handler(MessageReactionHandler(handle_winner_fire_reaction))
    app.add_handler(CommandHandler("report", handle_report))
    app.add_handler(CommandHandler("setwarnmedia", handle_setwarnmedia))
    app.add_handler(CommandHandler("listwarnmedia", handle_listwarnmedia))
    app.add_handler(CommandHandler("deletewarnmedia", handle_deletewarnmedia))

    app.add_handler(MessageHandler(
        filters.Sticker.ALL & filters.ChatType.PRIVATE,
        handle_warnmedia_upload
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        handle_warnmedia_upload
    ))
    app.add_handler(MessageHandler(
        filters.VIDEO & filters.ChatType.PRIVATE,
        handle_warnmedia_upload
    ))
    app.add_handler(MessageHandler(
        filters.ANIMATION & filters.ChatType.PRIVATE,
        handle_warnmedia_upload
    ))

    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.GROUPS,
        handle_group_photo
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_winner_correction_reply
    ), group=-1)

    # ✅ FIX: የራሱ group (-2) ላይ መመዝገብ አለበት! python-telegram-bot በአንድ
    # group ውስጥ የመጀመሪያውን filter-matching handler ብቻ ይጠራል — ይህ
    # ከ handle_winner_correction_reply ጋር ተመሳሳይ group (-1) እና ተመሳሳይ
    # filter ስለነበረው፣ ፈጽሞ አይጠራም ነበር (dead code)።
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_owner_reply
    ), group=-2)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_admin_board_reply
    ), group=0)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ), group=1)

    from telegram.ext import ChatMemberHandler
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.VIDEO_CHAT_STARTED & filters.ChatType.GROUPS,
        handle_video_chat_started
    ))

    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.VIDEO) & filters.ChatType.GROUPS,
        handle_admin_group_video
    ))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server())
    loop.run_until_complete(start_listeners())
    loop.run_until_complete(start_winner_listeners(app.bot))
    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))

    global _bot_instance
    _bot_instance = app.bot

    async def _init_jina_background():
        try:
            from jina_brain import init_jina_brain
            from responder import INTENT_EXAMPLES
            from config import JINA_API_KEYS as _jina_keys
            await init_jina_brain(INTENT_EXAMPLES, _jina_keys)
        except Exception as e:
            logging.warning(f"[Jina] Background init error: {e}")

    loop.create_task(_init_jina_background())

    from handlers import ensure_nvidia_health_task_started
    ensure_nvidia_health_task_started()
    ensure_nvidia_text_health_task_started()

    async def _daily_report_scheduler():
        import pytz
        et_tz = pytz.timezone("Africa/Addis_Ababa")
        while True:
            now = datetime.now(et_tz)
            target = now.replace(hour=23, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_secs = (target - now).total_seconds()
            await asyncio.sleep(wait_secs)

            try:
                groups = get_enabled_groups()
                for g in groups:
                    gid = g["group_id"]
                    if not is_group_active(gid):
                        continue
                    report = get_report(gid)
                    lines = ["📊 የዛሬ Daily Report\n"]
                    if report["games_count"] > 0:
                        lines.append(
                            f"🎮 ጨዋታዎች: {report['games_count']}\n"
                            f"💰 Total bet: ETB {report['total_bet']:,.0f}\n"
                            f"🏆 Prize: ETB {report['prize_total']:,.0f}\n"
                            f"📈 Profit: ETB {report['profit']:,.0f}"
                        )
                    else:
                        lines.append("🎮 ዛሬ ጨዋታ አልተጫወተም")
                    try:
                        admins = get_group_admins(gid)
                        for admin_id in admins:
                            try:
                                await _bot_instance.send_message(chat_id=admin_id, text="\n".join(lines))
                            except Exception:
                                pass
                    except Exception:
                        pass
                cleanup_old_reports()
                # NEW: winner-🔥-reaction feature — message_senders ላይ ደግሞ
                # ደህንነት (safety-net) periodic cleanup (clear_game ራሱ አዲስ
                # game ሲጀመር ያ group's records ቢያጸዳም፣ ይሄ ተጨማሪ ጥንቃቄ ነው)
                try:
                    cleanup_old_message_senders()
                except Exception:
                    pass
            except Exception as e:
                logging.warning(f"[Daily Report] Error: {e}")

    loop.create_task(_daily_report_scheduler())

    print("🤖 Bot started!")
    # NEW: allowed_updates ግልጽ ተብሎ ካልተሰጠ Telegram የድሮውን cached setting
    # ብቻ ይጠቀማል (message_reaction ላይካተት ይችላል) — ስለዚህ winner-🔥-reaction
    # feature እንዲሰራ Update.ALL_TYPES ግልጽ ተብሎ ተሰጥቷል።
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
