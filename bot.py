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

# áŒ¨á‹‹á‰³ áŠ«áˆˆá‰€ á‰ áŠ‹áˆ‹ (áˆáˆ‰áˆ âœ… áˆ†áŠá‹ live/pre-booking áˆ²áŒ€áˆáˆ­ á‹ˆá‹­áˆ á‹áŒ¤á‰µ áˆ²áˆ‹áŠ­) daily
# profit á‹µáŒ‹áˆš áŠ¥áŠ•á‹³á‹­á‰†áŒ áˆ­ á‹¨áˆšáŠ¨á‰³á‰°áˆ set â€” game_id-based guard
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

# FIX: winner photo áŠ¨á‰°áˆ‹áŠ¨ áŠ¥áˆµáŠ¨ _auto_newgame á‹µáˆ¨áˆµ á‹«áˆˆá‹ 30 áˆ°áŠ¨áŠ•á‹µ áŠ­áá‰°á‰µ â€”
# board/á‰€áŒ£á‹­ á‹™áˆ­ áŒˆáŠ“ áˆµáˆ‹áˆá‰°áŒ áŠ“á‰€á‰€á£ á‰ á‹šáˆ… áŒŠá‹œ á‹áˆµáŒ¥ registration á‰¢áˆ³áŠ« áˆáŠ­ áŠ¥áŠ•á‹°
# prebooking_groups reaction-only (ðŸ‘) á‰¥á‰» á‹­áˆ†áŠ• (text reply áŠ á‹­áˆ‹áŠ­áˆ)
winner_pending_groups = set()
handled_video_boards = set()  # game_ids where 30s+ video board replace already done

# ============================================================
# FIX: cross-group data leak â€” á‰¦á‰± 4 á‹¨á‰°áˆˆá‹«á‹© databases áˆµáˆ‹áˆ‰á‰µ
# (DATABASE_URLS rotation)á£ áŠ¥á‹«áŠ•á‹³áŠ•á‹± DB á‹¨áˆ«áˆ± á‹¨á‰°áˆˆá‹¨ game_settings.id
# (SERIAL) áŠ á‰†áŒ£áŒ áˆ­ áŠ áˆˆá‹á¢ áˆµáˆˆá‹šáˆ… áˆáˆˆá‰µ á‹¨á‰°áˆˆá‹«á‹© groups á‰ áŠ áŒ‹áŒ£áˆš á‰°áˆ˜áˆ³áˆ³á‹­ game_id
# á‰áŒ¥áˆ­ áˆŠáŠ–áˆ«á‰¸á‹ á‹­á‰½áˆ‹áˆ (áˆˆáˆáˆ³áˆŒ Group A game_id=12 á‰  DB#1á£ Group B
# game_id=12 á‰  DB#2)á¢ áŠ¨áˆ‹á‹­ á‹«áˆ‰á‰µ global trackers (nekay_numbers,
# nekay_active, á‹ˆá‹˜á‰°) á‰  game_id á‰¥á‰» áˆµáˆˆáˆšá‰€áˆ˜áŒ¡ áŠá‰ áˆ­á£ á‹­áˆ… áˆ›áˆˆá‰µ Group A's
# /nekay á‹áˆ‚á‰¥ á‰  Group B's board áˆ‹á‹­ á‹­á‰³á‹­ áŠá‰ áˆ­ (á‹ˆá‹­áˆ á‰ á‰°á‰ƒáˆ«áŠ’á‹)á¢
# FIX: áˆáˆ‰áˆ áŠ¥áŠá‹šáˆ… trackers á‰  (group_id, game_id) combo á‰áˆá á‰¥á‰»
# áŠ¥áŠ•á‹²á‰€áˆ˜áŒ¡ á‰°á‰€á‹­áˆ¨á‹‹áˆ â€” _gk() helper á‹­áˆ…áŠ• combo á‰áˆá á‹­áŒˆáŠá‰£áˆá¢
# ============================================================

def _gk(group_id, game_id):
    """Group-scoped key áˆˆ in-memory trackers (cross-group game_id collision áŠ¥áŠ•á‹³á‹­áˆáŒ áˆ­)"""
    return (group_id, game_id)

URGENCY_MESSAGES = [
    "á‰¤á‰°áˆ°á‰¥ áŒˆá‰£ áŒˆá‰£ á‰ áˆ‰ðŸ™",
    "á‰¤á‰°áˆ°á‰¥ áŒ«á‹ˆá‰³á‹áŠ• áŠ áŠ“á‹µáˆá‰… ðŸ™",
    "á‰¤á‰°áˆ°á‰¥ á‰€áˆª á‰áŒ¥áˆ®á‰½ á‰¥á‰» áŠ áˆ‰ áŒˆá‰£ áŒˆá‰£ á‰ áˆ‰ ðŸ™",
]

NEKAY_COUNTDOWN_MESSAGE = "á‰¤á‰°áˆ°á‰¥ á‰µáŠ•áˆ½ á‹­áŒ á‰¥á‰ áŠá‰ƒá‹­ áˆ‹á‹ˆáŒ£ áŠá‹ ðŸ™"


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
# NEW â€” DEBOUNCED REMAINING/NEKAY RESEND (payment confirm â†’ 5-second
# debounce â†’ resend á‰€áˆª/áŠá‰ƒá‹­ list áŠ¨á‰³á‰½, no duplicates ever)
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
    Payment (photo/SMS) confirm â†’ "áˆ˜áˆáŠ«áˆ á‹•á‹µáˆ" áŠ«áˆˆ á‰ áŠ‹áˆ‹ 5 áˆ°áŠ¨áŠ•á‹µ áˆáŠ•áˆ á‰°áŒ¨áˆ›áˆª
    áŠ­áá‹«/áŠ¥áŠ•á‰…áˆµá‰ƒáˆ´ áŠ¨áˆŒáˆˆ á‰€áˆª (á‹ˆá‹­áˆ áŠá‰ƒá‹­ mode áŒˆá‰£áˆª áŠ¨áˆ†áŠ áŠá‰ƒá‹­) á‹áˆ­á‹áˆ­ áŠ¨á‰³á‰½ resend
    á‹­áˆáŠ• â€” áŠá‰£áˆ©áŠ• áŠ áŒ¥áá‰¶ áŠ á‹²áˆµ á‰¥á‰» (duplicate á‰ ááŒ¹áˆ áŠ¥áŠ•á‹³á‹­áˆáŒ áˆ­)á¢ 5 áˆ°áŠ¨áŠ•á‹µ á‹áˆµáŒ¥
    áˆŒáˆ‹ áŠ­áá‹« á‰¢áˆ˜áŒ£ (_schedule_remaining_resend á‰°áŒ áˆ­á‰¶) á‹­áˆ… task á‹­áˆ°áˆ¨á‹›áˆ
    (cancel) áŠ á‹²áˆµ 5 áˆ°áŠ¨áŠ•á‹µ á‹­áŒ€áˆáˆ«áˆá¢
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
                if is_half:
                    snap[number] = -1 if slots == {1} else (-2 if slots == {2} else 0)
                else:
                    snap[number] = 0
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
        # NEW: áŠá‰ƒá‹­ mode á‰£á‹­áˆ†áŠ•áˆ áŠ¥áŠ•áŠ³ (á‰°áˆ« áŒ¨á‹‹á‰³)á£ áŠ­áá‹« áŠ¨á‰°áˆ¨áŒ‹áŒˆáŒ  á‰ áŠ‹áˆ‹ á‰€áˆª á‹áˆ­á‹áˆ­
        # 5 áˆ°áŠ¨áŠ•á‹µ debounce á‰†á‹­á‰¶ resend á‹­áˆáŠ• (áŠ¨á‹šáˆ… á‰ áŠá‰µ áˆáŠ•áˆ áŠ áˆáŠá‰ áˆ¨áˆ â€” á‹­áˆ„
        # áŠ­áá‰°á‰µ áŠá‰ áˆ­)
        _schedule_remaining_resend(bot, group_id, game_id)
        return

    fresh_nekay = get_nekay_numbers(game_id)
    snap = {}
    for number, slots, is_half in fresh_nekay:
        if is_half:
            snap[number] = -1 if slots == {1} else (-2 if slots == {2} else 0)
        else:
            snap[number] = 0
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

    # NEW: áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ á‹ˆá‹²á‹«á‹áŠ‘ áˆ³á‹­áˆ†áŠ• 5 áˆ°áŠ¨áŠ•á‹µ debounce á‰†á‹­á‰¶ resend á‹­áˆáŠ• (áˆŒáˆ‹
    # áŠ­áá‹«/áŠ¥áŠ•á‰…áˆµá‰ƒáˆ´ á‰ á‹šá‹« 5 áˆ°áŠ¨áŠ•á‹µ á‹áˆµáŒ¥ á‰¢áˆ˜áŒ£ timer á‹­á‰³á‹°áˆ³áˆ)
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
# FIX #6: fire-and-forget helpers â€” reply/reaction Telegram API
# call áŠ• board edit áŠ¨áˆ˜áŒ€áˆ˜áˆ© á‰ áŠá‰µ áŠ¥áŠ•á‹²áŒ á‰¥á‰… áˆ‹áˆˆáˆ›á‹µáˆ¨áŒ (á‰€á‹µáˆž sequential áˆµáˆˆáŠá‰ áˆ­
# board edit á‹­á‹˜áŒˆá‹­ áŠá‰ áˆ­)á¢ á‹áŒ¤á‰±áŠ• áŠ áŠ•áŒ á‰¥á‰…áˆá£ áˆµáˆ…á‰°á‰µ á‰¢áˆáŒ áˆ­ log á‰¥á‰» áŠ¥áŠ“á‹°áˆ­áŒ‹áˆˆáŠ•á¢
# ============================================================

async def _safe_reply_text(msg, text: str):
    try:
        await msg.reply_text(text)
    except Exception as e:
        logging.warning(f"[SafeReply] Error: {e}")


async def _safe_set_reaction(bot, chat_id: int, message_id: int, emoji: str = "ðŸ‘"):
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
# FIX #4: admin confirmation messages ("âœ… ...") áŠ¨á‰°áˆ‹áŠ© áŠ¨1.5-2 áˆ°áŠ¨áŠ•á‹µ
# á‰ áŠ‹áˆ‹ á‰ áˆ«áˆ³á‰¸á‹ á‹­áŒ á‰ (admin áŠ«á‹¨ á‰ á‰‚ áŠá‹)á¢
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
# NEW â€” winner "ðŸ”¥ reaction" balance-clear feature: admin puts a native
# ðŸ”¥ reaction on any message previously sent BY a recent winner (in the
# group) â†’ that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched â€” this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message â€” only who reacted and which
# chat/message_id. So we keep a small bounded in-memory cache mapping
# (chat_id, message_id) -> (telegram_id, user_name) for recent group
# text messages, populated (read-only/additive) inside
# handle_group_message. This does not alter any existing behavior.
# ============================================================
# ============================================================
# NEW â€” winner "ðŸ”¥ reaction" balance-clear feature: admin puts a native
# ðŸ”¥ reaction on any message previously sent BY a recent winner (in the
# group) â†’ that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched â€” this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message â€” only who reacted and which
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
# NEW â€” "# NUM[+SLOT][âœ…] ..." admin replacement feature: bot's
# earlier "á‰°á‹­á‹žá‰¥áˆƒáˆ"/booking_taken rejection reply message_id á‰°áˆ˜á‹áŒá‰¦
# á‹­á‰€áˆ˜áŒ£áˆá£ áˆµáˆˆá‹šáˆ… admin á‰°áŒ á‰ƒáˆšá‹ áŠ¦áˆ­áŒ…áŠ“áˆ message áˆ‹á‹­ reply áŠ á‹µáˆ­áŒŽ "# ..." áˆ²áˆ
# á‹«áŠ•áŠ• áŠá‰£áˆ­ rejection message áˆ›áŒ¥á‹á‰µ á‹­á‰»áˆ‹áˆá¢
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
        # 0 = áˆ™áˆ‰ nekay (full)á£ 2/-1/-2 áˆáˆ‰áˆ half/slot-specific nekay áŠ“á‰¸á‹
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
            if is_half:
                snap[number] = -1 if slots == {1} else (-2 if slots == {2} else 0)
            else:
                snap[number] = 0
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
    await update.message.reply_text("ðŸ¤– Bot á‰°áˆ°áŠ“á‹µá‰·áˆ!")


# ============================================================
# SETGAME CONVERSATION
# ============================================================

async def setgame_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        await update.message.reply_text("âŒ Admin á‰¥á‰» áŠá‹!")
        return ConversationHandler.END
    ctx.user_data["setup_group_id"] = group_id
    await update.message.reply_text("ðŸŽ® áˆµáŠ•á‰µ á‰áŒ¥áˆ®á‰½ áŠ áˆ‰? (áˆˆáˆáˆ³áˆŒ: 100)")
    return ASK_TOTAL


async def ask_total(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["total_numbers"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")
        return ASK_TOTAL
    await update.message.reply_text("ðŸ‘¥ áˆˆ1 áˆ°á‹ áˆµáŠ•á‰µ á‰áŒ¥áˆ®á‰½? (áˆˆáˆáˆ³áˆŒ: 5)")
    return ASK_PER_PERSON


async def ask_per_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["numbers_per_person"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")
        return ASK_PER_PERSON
    await update.message.reply_text("ðŸ’° áˆ™áˆ‰ á‹‹áŒ‹ áˆµáŠ•á‰µ á‰¥áˆ­?")
    return ASK_PRICE_FULL


async def ask_price_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["price_full"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")
        return ASK_PRICE_FULL
    await update.message.reply_text("ðŸ’³ áŒáˆ›áˆ½ á‹‹áŒ‹ áŠ áˆˆ? (á‰áŒ¥áˆ­ áŒ»á á‹ˆá‹­áˆ 'áŠ á‹­á‹°áˆˆáˆ')")
    return ASK_PRICE_HALF


async def ask_price_half(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["áŠ á‹­á‹°áˆˆáˆ", "aydelem", "no", "á‹¨áˆˆáˆ"]:
        ctx.user_data["price_half"] = None
    else:
        try:
            ctx.user_data["price_half"] = int(text)
        except ValueError:
            await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‹ˆá‹­áˆ 'áŠ á‹­á‹°áˆˆáˆ' áŒ»á!")
            return ASK_PRICE_HALF
    await update.message.reply_text("ðŸ¥‡ 1áŠ› áˆ½áˆáˆ›á‰µ áˆµáŠ•á‰µ á‰¥áˆ­?")
    return ASK_PRIZE_1


async def ask_prize_1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["prize_1st"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")
        return ASK_PRIZE_1
    await update.message.reply_text("ðŸ¥ˆ 2áŠ› áˆ½áˆáˆ›á‰µ? (áŠ¨áˆŒáˆˆ 'áŠ á‹­á‹°áˆˆáˆ')")
    return ASK_PRIZE_2


async def ask_prize_2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["áŠ á‹­á‹°áˆˆáˆ", "aydelem", "no", "á‹¨áˆˆáˆ"]:
        ctx.user_data["prize_2nd"] = None
    else:
        try:
            ctx.user_data["prize_2nd"] = int(text)
        except ValueError:
            await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‹ˆá‹­áˆ 'áŠ á‹­á‹°áˆˆáˆ' áŒ»á!")
            return ASK_PRIZE_2
    await update.message.reply_text("ðŸ¥‰ 3áŠ› áˆ½áˆáˆ›á‰µ? (áŠ¨áˆŒáˆˆ 'áŠ á‹­á‹°áˆˆáˆ')")
    return ASK_PRIZE_3


async def ask_prize_3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["áŠ á‹­á‹°áˆˆáˆ", "aydelem", "no", "á‹¨áˆˆáˆ"]:
        ctx.user_data["prize_3rd"] = None
    else:
        try:
            ctx.user_data["prize_3rd"] = int(text)
        except ValueError:
            await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‹ˆá‹­áˆ 'áŠ á‹­á‹°áˆˆáˆ' áŒ»á!")
            return ASK_PRIZE_3
    await update.message.reply_text("ðŸ’³ Payment info áŒ»á (CBE, Telebirr...):")
    return ASK_PAYMENT


async def ask_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["payment_info"] = update.message.text.strip()
    await update.message.reply_text(
        "ðŸ“Œ Game rule áŒ»á (board áˆ‹á‹­ áŠ¨áˆ‹á‹­ á‹­á‰³á‹«áˆ)\n"
        "á‹ˆá‹­áˆ 'skip' áŠ«áˆáˆáˆˆáŒ‹á‰¸áˆ…"
    )
    return ASK_GAME_RULE


async def ask_game_rule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "áŠ á‹­á‹°áˆˆáˆ", "no", "á‹¨áˆˆáˆ"]:
        ctx.user_data["game_rule"] = None
    else:
        ctx.user_data["game_rule"] = text
    await update.message.reply_text(
        "ðŸ”£ Slot symbol áˆáˆ¨áŒ¥\n"
        "áˆˆáˆáˆ³áˆŒ: # â­ ðŸŽ¯ ðŸ”¥ á‹ˆá‹­áˆ á‰£á‹¶ (skip)\n"
        "Default: #"
    )
    return ASK_SLOT_SYMBOL


async def ask_slot_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "default", "#"]:
        ctx.user_data["slot_symbol"] = "#"
    elif text.lower() in ["á‰£á‹¶", "none", "empty", ""]:
        ctx.user_data["slot_symbol"] = ""
    else:
        ctx.user_data["slot_symbol"] = text
    await update.message.reply_text(
        "â³ á‰°áŠá‰ƒá‹­ countdown áŠ áˆˆ?\n"
        "(áŠ á‹Ž / áŠ á‹­á‹°áˆˆáˆ)"
    )
    return ASK_COUNTDOWN_ENABLED


async def ask_countdown_enabled(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    yes = text in ["áŠ á‹Ž", "awo", "yes", "aha", "áŠ á‹ŽáŠ•"]
    ctx.user_data["countdown_enabled"] = yes

    if yes:
        await update.message.reply_text(
            "â±ï¸ áˆµáŠ•á‰µ á‹°á‰‚á‰ƒ?\n"
            "0.5 = 30 áˆ°áŠ¨áŠ•á‹µ\n"
            "1 = 1 á‹°á‰‚á‰ƒ\n"
            "2 = 2 á‹°á‰‚á‰ƒ\n"
            "5 = 5 á‹°á‰‚á‰ƒ\n"
            "10 = 10 á‹°á‰‚á‰ƒ\n"
            "(0.5 áŠ¥áˆµáŠ¨ 10)"
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
        await update.message.reply_text("âŒ 0.5 áŠ¥áˆµáŠ¨ 10 á‰¥á‰» áŒ»á!")
        return ASK_COUNTDOWN_MINUTES
    return await ask_profit_per_game_prompt(update, ctx)


async def ask_profit_per_game_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ðŸ“ˆ áŠ¨1 áŒ¨á‹‹á‰³ áˆµáŠ•á‰µ á‰¥áˆ­ profit á‹«áŒˆáŠ›áˆ‰? (áˆˆáˆáˆ³áˆŒ: 300)"
    )
    return ASK_PROFIT_PER_GAME


async def ask_profit_per_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["profit_per_game"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á! (áˆˆáˆáˆ³áˆŒ: 300)")
        return ASK_PROFIT_PER_GAME
    return await _finish_setgame(update, ctx)


async def _finish_setgame(update, ctx):
    setup_group_id = ctx.user_data.get("setup_group_id")

    # NEW: /newgame áˆ«áˆ± áŠ¨á‹šáˆ… á‰ áŠá‰µ game switch áˆ²á‹«á‹°áˆ­áŒ (clear_game + in-memory
    # nekay/countdown state áˆ›áŒ½á‹³á‰µ) á‹¨áˆšá‹«á‹°áˆ­áŒˆá‹áŠ• á‰°áˆ˜áˆ³áˆ³á‹­ cleanup â€” /setgame áŒáŠ•
    # áŠ¨á‹šáˆ… á‰ áŠá‰µ á‹­áˆ…áŠ• áŠ á‹«á‹°áˆ­áŒáˆ áŠá‰ áˆ­ (á‹ˆáŒ¥áŠá‰µ áˆ›áŒ£á‰µá£ stale winners/nekay state
    # áŠ¥áŠ•á‹²á‰€áŒ¥áˆ áˆáŠ­áŠ•á‹«á‰µ áˆ†áŠ– áŠá‰ áˆ­)á¢ áŠ á‹²áˆ±áŠ• game_id áŠ¨áˆ˜ááŒ áˆ© á‰ áŠá‰µ á‹¨á‰†á‹¨á‹áŠ• á‹«áŒ¸á‹³áˆá¢
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
        profit_counted_games.discard(old_key)
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

    countdown_status = "âœ… On" if ctx.user_data.get("countdown_enabled") else "âŒ Off"
    mins = ctx.user_data.get("countdown_minutes", 0)
    await update.message.reply_text(
        f"âœ… Settings á‰°á‰€áˆáŒ§áˆ!\n"
        f"Game ID: {game_id}\n"
        f"â³ Countdown: {countdown_status}"
        + (f" ({mins} á‹°á‰‚á‰ƒ)" if ctx.user_data.get("countdown_enabled") else "")
    )
    return ConversationHandler.END


async def cancel_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("âŒ Setup á‰°áˆ°áˆ­á‹Ÿáˆá¢")
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
            await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "âŒ áˆáˆ³áˆŒ: /setcountdown 2\n"
            "0 = countdown áŠ áŒ¥á‹\n"
            "0.5, 1, 2, 5, 10 = á‹°á‰‚á‰ƒ"
        )
        return

    try:
        mins = float(parts[1])
        if mins != 0 and (mins < 0.5 or mins > 10):
            raise ValueError
    except ValueError:
        await update.message.reply_text("âŒ 0 á‹ˆá‹­áˆ 0.5 áŠ¥áˆµáŠ¨ 10 á‰¥á‰» áŒ»á!")
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
        return

    enabled = mins > 0
    update_countdown_settings(settings["id"], enabled, mins if enabled else 0)

    if enabled:
        await update.message.reply_text(f"âœ… Countdown {mins} á‹°á‰‚á‰ƒ á‰°á‰€áˆáŒ§áˆ!")
    else:
        await update.message.reply_text("âœ… Countdown áŒ áá‰·áˆ!")


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
            await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await update.message.reply_text(
            "âŒ áˆáˆ³áˆŒ: /showslots on\n"
            "       /showslots off\n"
            "sub-slots áˆ‹á‹­ áˆµáˆ á‹«áˆ³á‹«áˆ / á‹«áŒ á‹áˆ"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
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

    status = "âœ… On" if enabled else "âŒ Off"
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
            "âŒ áˆáˆ³áˆŒ: /nekay 5 10+ 15 21\n"
            "+ = áŒáˆ›áˆ½ (áˆˆáˆáˆ³áˆŒ 10+)\n"
            "5+1 = á‰áŒ¥áˆ­ 5 slot 1 á‰¥á‰»\n"
            "á‰€á‹µáˆž á‹¨áŠá‰ áˆ¨á‹áŠ• áŠá‰ƒá‹­ áˆáˆ‰ á‹­á‰°áŠ«áˆ"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
        return

    game_id = settings["id"]
    per_person = settings["numbers_per_person"]
    taken = get_taken_numbers(game_id)

    numbers = []   # (num, is_half, slot_only) â€” slot_only=None means all slots
    errors = []

    for part in parts[1:]:
        # NUM+SLOT pattern (áˆˆáˆáˆ³áˆŒ 5+1 á‹ˆá‹­áˆ 5+2)
        import re as _re
        slot_match = _re.match(r'^(\d+)\+(\d+)$', part)
        if slot_match:
            num = int(slot_match.group(1))
            slot = int(slot_match.group(2))
            # âœ… FIX: 1-5 á‰¡á‹µáŠ• á‰¢áˆ†áŠ• (numbers_per_person>1)á£ áˆ›áŠ•áŠ›á‹áˆ á‰áŒ¥áˆ­
            # á‰ á‹šá‹« á‰¡á‹µáŠ• á‹áˆµáŒ¥ (áˆˆáˆáˆ³áˆŒ 4) â†’ group's first number (1) á‹­áˆ†áŠ“áˆá£
            # áˆáŠ­áŠ•á‹«á‰±áˆ DB áˆ‹á‹­ á‹¨á‰°áˆ˜á‹˜áŒˆá‰ á‹ á‰  group start á‰¥á‰» áŠá‹
            actual_num = get_group_start(num, per_person) if per_person > 1 else num
            if actual_num < 1 or actual_num > settings["total_numbers"]:
                errors.append(part)
                continue
            # á‹« slot exist á‹«áˆ¨áŒ‹áŒáŒ¥
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
        # âœ… FIX: áŠ¥á‹šáˆ…áˆ á‰°áˆ˜áˆ³áˆ³á‹­ group-start mapping
        actual_num = get_group_start(num, per_person) if per_person > 1 else num
        if actual_num < 1 or actual_num > settings["total_numbers"]:
            errors.append(part)
            continue

        # NUM+ áˆ²áˆ†áŠ• 2 slots áŠ«áˆˆ áŠ á‹­áˆ°áˆ«áˆ
        if is_half:
            slots_for_num = taken.get(actual_num, [])
            if len(slots_for_num) > 1:
                errors.append(part + " (2 slots áŠ áˆˆ â€” 5+1 á‹ˆá‹­áˆ 5+2 áŒ á‰€áˆµ)")
                continue

        numbers.append((actual_num, is_half, None))

    if not numbers:
        await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‰áŒ¥áˆ­ áŠ áˆá‰°áŒˆáŠ˜áˆ!")
        return

    # DB áˆ‹á‹­ nekay á‹«á‹°áˆ­áŒ‹áˆ â€” slot_only áŠ«áˆˆ á‹« slot á‰¥á‰»
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE registrations SET is_nekay=FALSE WHERE game_id=%s AND is_nekay=TRUE", (game_id,))

    snap = {}
    for num, is_half, slot_only in numbers:
        if slot_only is not None:
            # slot á‰¥á‰»
            cur.execute("""
                UPDATE registrations SET is_nekay=TRUE
                WHERE game_id=%s AND number=%s AND slot=%s
            """, (game_id, num, slot_only))
            # FIX: á‹¨á‰µáŠ›á‹ slot áŠ¥áŠ•á‹°áˆ†áŠ á‰°áˆˆá‹­á‰¶ á‹­á‰€áˆ˜áŒ¥ (-1 = slot 1, -2 = slot 2)
            # áˆµáˆˆá‹šáˆ… user áˆ²á‹­á‹ á‰µáŠ­áŠ­áˆˆáŠ›á‹ slot force-overwrite á‹­á‹°áˆ¨áŒáˆˆá‰³áˆ
            snap[num] = -1 if slot_only == 1 else -2
        else:
            # FIX: "NUM+" (á‹¨á‰µáŠ›á‹ slot áŠ¥áŠ•á‹³áˆá‰°áŒˆáˆˆáŒ¸) â€” á‹­áˆ… á‰¥á‹™ áŒŠá‹œ áˆ›áˆˆá‰µ á‹¨áˆšáˆáˆáŒˆá‹
            # "áŠ­áá‰µ (áŒˆáŠ“ á‹«áˆá‰°á‹«á‹˜á‹áŠ•) slot áŠ¥áŠ•á‹° nekay áŠ áˆ³á‹­/áŠ áˆµá‰°á‹‹á‹á‰…" áˆ›áˆˆá‰µ áŠá‹á£
            # "áŠá‰£áˆ©áŠ• registration nekay áŠ á‹µáˆ­áŒ" áˆ›áˆˆá‰µ áŠ á‹­á‹°áˆˆáˆá¢ áˆµáˆˆá‹šáˆ… á‹¨á‰µáŠ›á‹ slot
            # á‰ á‰µáŠ­áŠ­áˆ áŠ­áá‰µ áŠ¥áŠ•á‹°áˆ†áŠ áŠ áˆ¨áŒ‹áŒáŒ¦ á‹«áŠ•áŠ• á‰¥á‰» á‹­áŠáŠ«áˆ (placeholder INSERT)á£
            # áŠá‰£áˆ­ (á‹¨á‰°áŠ¨áˆáˆˆ) registration áˆáŒ½áˆž áŠ á‹­áŠáŠ«áˆá¢
            slots_for_num = taken.get(num, [])
            existing_slots = {s[2] for s in slots_for_num}

            if is_half:
                if existing_slots == {1}:
                    target_slot = 2
                elif existing_slots == {2}:
                    target_slot = 1
                elif not existing_slots:
                    target_slot = 1
                else:
                    errors.append(part + " (áˆ™áˆ‰ á‰°á‹­á‹Ÿáˆ)")
                    continue

                if target_slot in existing_slots:
                    # á‹« specific slot áˆ«áˆ± áŠá‰£áˆ­ registration áˆµáˆ‹áˆˆá‹ á‰¥á‰» â€”
                    # á‹«áŠ•áŠ• á‰¥á‰» nekay áŠ á‹µáˆ­áŒ (áŠá‰£áˆ­ áˆŽáŒ‚áŠ­)
                    cur.execute("""
                        UPDATE registrations SET is_nekay=TRUE
                        WHERE game_id=%s AND number=%s AND slot=%s
                    """, (game_id, num, target_slot))
                else:
                    # áŠ­áá‰µ slot â€” áˆ›áŠ•áˆ áŒˆáŠ“ á‹«áˆá‹«á‹˜á‹á£ placeholder INSERT
                    # (nekay list áˆ‹á‹­ áŠ¥áŠ•á‹²á‰³á‹­/ á‹ˆá‹°áŠá‰µ áˆ°á‹ áˆ²á‹­á‹˜á‹ á‰ á‰µáŠ­áŠ­áˆ force
                    # á‹­á‹°áˆ¨áŒáˆˆá‰µ á‹˜áŠ•á‹µ)
                    cur.execute("""
                        SELECT 1 FROM registrations
                        WHERE game_id=%s AND number=%s AND slot=%s
                    """, (game_id, num, target_slot))
                    if not cur.fetchone():
                        cur.execute("""
                            INSERT INTO registrations
                                (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                            VALUES (%s, 0, '', %s, TRUE, %s, FALSE, TRUE, FALSE)
                        """, (game_id, num, target_slot))
                    else:
                        cur.execute("""
                            UPDATE registrations SET is_nekay=TRUE
                            WHERE game_id=%s AND number=%s AND slot=%s
                        """, (game_id, num, target_slot))

                snap[num] = -1 if target_slot == 1 else -2
            else:
                cur.execute("""
                    UPDATE registrations SET is_nekay=TRUE
                    WHERE game_id=%s AND number=%s
                """, (game_id, num))
                snap[num] = 0

    conn.commit()
    cur.close()
    conn.close()

    nekay_numbers[_gk(group_id, game_id)] = snap
    nekay_active.add(_gk(group_id, game_id))
    admin_nekay_games.add(_gk(group_id, game_id))

    # FIX: admin's own "/nekay ..." message á‹ˆá‹²á‹«á‹áŠ‘ á‹­áŒ á‹ (áˆáŠ­ áŠ¥áŠ•á‹° #/ áŠ¥áŠ“ #name)
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
    msg = f"âœ… áŠá‰ƒá‹­ á‰°á‰€áˆáŒ§áˆ: {reg_list}"
    if errors:
        msg += f"\nâŒ á‹«áˆá‰°á‰€á‰ áˆˆ: {', '.join(errors)}"
    # FIX #4: admin confirmation message áŠ¨1.5-2 áˆ°áŠ¨áŠ•á‹µ á‰ áŠ‹áˆ‹ áˆ«áˆ± á‹­áŒ á‹áˆ
    await _send_temp_admin_message(ctx.bot, group_id, msg)


# ============================================================
# NEW â€” "ðŸ”¥NUM[+SLOT] ..." áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ áˆ›á‹áŒ« (admin text message)
#   ðŸ”¥16 21+   â†’ á‰áŒ¥áˆ­ 16 áŠ¥áŠ“ 21 áŠ¨áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ á‹­á‹ˆáŒ£áˆ‰ ("áŠá‰ƒá‹­ áŠ á‹­á‹°áˆˆáˆ")
#   ðŸ”¥5+1      â†’ á‰áŒ¥áˆ­ 5 slot 1 á‰¥á‰» áŠ¨áŠá‰ƒá‹­ á‹­á‹ˆáŒ£áˆ
# áŠ¨ DB áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ áˆ‹á‹­ á‰¥á‰» á‹«á‹ˆáŒ£áˆ (mode áŒˆá‰£áˆª áˆ˜áˆ†áŠ• áŠ á‹«áˆµáˆáˆáŒáˆ)á¢ á‰£áˆˆá‰¤á‰µ á‹«áˆˆá‹ (á‹¨á‰°áˆ˜á‹˜áŒˆá‰ ) á‰áŒ¥áˆ­ is_nekay=FALSE
# á‹­áˆ†áŠ“áˆá£ á‰£áˆˆá‰¤á‰µ á‹¨áˆŒáˆˆá‹ placeholder (/nekay 10+ á‹¨áˆáŒ áˆ¨á‹ á‰£á‹¶ slot) á‹­áˆ°áˆ¨á‹›áˆá¢
# ============================================================

async def handle_unnekay_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import re as _re_un
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    if not text.startswith("ðŸ”¥"):
        return

    body = text.replace("\ufe0f", "")[len("ðŸ”¥"):].strip()
    parts = [p for p in _re_un.split(r'[,\s]+', body) if p]
    # á‰áŒ¥áˆ­ á‹¨áˆšáˆ˜áˆµáˆ áŠ«áˆáˆ†áŠ (á‰°áˆ« ðŸ”¥ á‹ˆá‹­áˆ ðŸ”¥ áŒ½áˆá) á‹áˆ á‰¥áˆŽ á‹­áˆˆá
    if not parts or not _re_un.match(r'^\d+(\+\d*)?$', parts[0]):
        return

    group_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not is_admin(user_id, group_id):
        return
    if not is_group_enabled(group_id) or not is_group_active(group_id):
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return
    game_id = settings["id"]
    key = _gk(group_id, game_id)

    try:
        await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
    except Exception:
        pass

    per_person = settings["numbers_per_person"]
    targets = []   # (actual_num, slot_only, original_part)
    errors = []
    for part in parts:
        m = _re_un.match(r'^(\d+)\+(\d+)$', part)
        if m:
            num, slot = int(m.group(1)), int(m.group(2))
        elif _re_un.match(r'^\d+\+?$', part):
            num, slot = int(part.rstrip("+")), None
        else:
            errors.append(part)
            continue
        actual = get_group_start(num, per_person) if per_person > 1 else num
        if actual < 1 or actual > settings["total_numbers"]:
            errors.append(part)
            continue
        targets.append((actual, slot, part))

    removed = []
    conn = get_conn()
    cur = conn.cursor()
    try:
        for actual, slot, part in targets:
            if slot is None:
                cur.execute(
                    "SELECT slot, user_id FROM registrations WHERE game_id=%s AND number=%s AND is_nekay=TRUE",
                    (game_id, actual),
                )
            else:
                cur.execute(
                    "SELECT slot, user_id FROM registrations WHERE game_id=%s AND number=%s AND slot=%s AND is_nekay=TRUE",
                    (game_id, actual, slot),
                )
            rows = cur.fetchall()
            if not rows:
                errors.append(part + " (áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ áˆ‹á‹­ á‹¨áˆˆáˆ)")
                continue
            for r_slot, r_uid in rows:
                if not r_uid:
                    # á‰£áˆˆá‰¤á‰µ á‹¨áˆŒáˆˆá‹ placeholder â†’ á‹­áˆ°áˆ¨á‹›áˆ
                    cur.execute(
                        "DELETE FROM registrations WHERE game_id=%s AND number=%s AND slot=%s",
                        (game_id, actual, r_slot),
                    )
                else:
                    cur.execute(
                        "UPDATE registrations SET is_nekay=FALSE WHERE game_id=%s AND number=%s AND slot=%s",
                        (game_id, actual, r_slot),
                    )
            removed.append(part)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.warning(f"[UnNekay] DB error: {e}")
        await _send_temp_admin_message(ctx.bot, group_id, "âŒ áˆµáˆ…á‰°á‰µ á‰°áˆáŒ¥áˆ¯áˆá£ áŠ¥áŠ•á‹°áŒˆáŠ“ áˆžáŠ­áˆ­")
        return
    finally:
        cur.close()
        conn.close()

    if not removed:
        await _send_temp_admin_message(ctx.bot, group_id, f"âŒ á‹«áˆá‰°áŒˆáŠ˜: {', '.join(errors)}")
        return

    # áŠ¨ DB áˆ‹á‹­ á‰µáŠ­áŠ­áˆˆáŠ›á‹áŠ• áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ áŠ¥áŠ•á‹°áŒˆáŠ“ áˆ˜áŒˆáŠ•á‰£á‰µ
    snap = {}
    for number, slots, is_half in get_nekay_numbers(game_id):
        if is_half:
            snap[number] = -1 if slots == {1} else (-2 if slots == {2} else 0)
        else:
            snap[number] = 0
    nekay_numbers[key] = snap

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        await _refresh_board(ctx, fresh, group_id)
        rem_msg_id = fresh.get("remaining_message_id")
        if rem_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
            except Exception:
                pass
        if snap:
            nekay_text = build_nekay(_build_nekay_from_snap(snap))
            new_nekay = await ctx.bot.send_message(chat_id=group_id, text=nekay_text)
            update_remaining_message_id(game_id, new_nekay.message_id)
            nekay_active.add(key)
        else:
            # áŠá‰ƒá‹­ áˆ™áˆ‰ á‰ áˆ™áˆ‰ á‰£á‹¶ áˆ†áŠ â†’ áŠá‰ƒá‹­ mode á‹­áŒ á‹áˆ
            update_remaining_message_id(game_id, None)
            nekay_active.discard(key)
            nekay_numbers.pop(key, None)
            _stop_inactivity_tracker(game_id, group_id)

    out = f"âœ… áŠá‰ƒá‹­ áŠ á‹­á‹°áˆˆáˆ: {', '.join(removed)}"
    if errors:
        out += f"\nâŒ á‹«áˆá‰°á‰€á‰ áˆˆ: {', '.join(errors)}"
    await _send_temp_admin_message(ctx.bot, group_id, out)


# ============================================================
# COMPLETE STICKER COMMANDS
# ============================================================

async def handle_setcompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return
    ctx.user_data["awaiting_complete_sticker"] = True
    await update.message.reply_text("âœ… áŠ áˆáŠ• sticker á‹­áˆ‹áŠ© (áˆáˆ‰áˆ group áˆ‹á‹­ á‹­áˆ°áˆ«áˆ)")


async def handle_listcompletestickers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    stickers = get_complete_stickers()
    if not stickers:
        await update.message.reply_text("ðŸ“‹ Complete sticker á‹¨áˆˆáˆá¢")
        return
    lines = ["ðŸ“‹ Complete Stickers:\n"]
    for i, s in enumerate(stickers, 1):
        added = s["added_at"].strftime("%m/%d %H:%M") if s["added_at"] else "?"
        lines.append(f"{i}. file_id: {s['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removecompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /removecompletesticker 1")
        return
    try:
        index = int(parts[1])
        success = remove_complete_sticker_by_index(index)
        if success:
            await update.message.reply_text(f"âœ… Sticker #{index} áŒ á‹!")
        else:
            await update.message.reply_text(f"âŒ #{index} áŠ áˆá‰°áŒˆáŠ˜áˆ!")
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


async def handle_complete_sticker_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    if not ctx.user_data.get("awaiting_complete_sticker"):
        return
    msg = update.message
    if not msg.sticker:
        await msg.reply_text("âŒ Sticker á‰¥á‰» á‹­áˆ‹áŠ©!")
        return
    file_id = msg.sticker.file_id
    add_complete_sticker(file_id)
    ctx.user_data.pop("awaiting_complete_sticker", None)
    await msg.reply_text("âœ… Complete sticker á‰°á‰€áˆáŒ§áˆ!")


# ============================================================
# PRE-BOOKING MEDIA COMMANDS
# ============================================================

async def handle_setprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return
    ctx.user_data["awaiting_prebooking_media"] = True
    await update.message.reply_text(
        "âœ… áŠ áˆáŠ• photo/video/sticker á‹­áˆ‹áŠ© (pre-booking áˆ²áŒ€áˆáˆ­ group áˆ‹á‹­ á‹­áˆ‹áŠ«áˆ)\n"
        "á‰¥á‹™ áŒŠá‹œ áˆŠáŒ¨áˆáˆ© á‹­á‰½áˆ‹áˆ‰ â€” áˆáˆ‰áˆ á‰ á‰…á‹°áˆ á‰°áŠ¨á‰°áˆ á‹­áˆ‹áŠ«áˆ‰á¢"
    )


async def handle_listprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    medias = get_prebooking_media()
    if not medias:
        await update.message.reply_text("ðŸ“‹ Pre-booking media á‹¨áˆˆáˆá¢")
        return
    lines = ["ðŸ“‹ Pre-Booking Media:\n"]
    for i, m in enumerate(medias, 1):
        added = m["added_at"].strftime("%m/%d %H:%M") if m["added_at"] else "?"
        lines.append(f"{i}. {m['media_type']} â€” {m['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removeprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /removeprebookingmedia 1")
        return
    try:
        index = int(parts[1])
        success = remove_prebooking_media_by_index(index)
        if success:
            await update.message.reply_text(f"âœ… Pre-booking media #{index} áŒ á‹!")
        else:
            await update.message.reply_text(f"âŒ #{index} áŠ áˆá‰°áŒˆáŠ˜áˆ!")
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


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
        await msg.reply_text("âŒ Photo/Video/Sticker á‰¥á‰» á‹­áˆ‹áŠ©!")
        return

    add_prebooking_media(file_id, media_type)
    ctx.user_data.pop("awaiting_prebooking_media", None)
    await msg.reply_text(f"âœ… Pre-booking media á‰°á‰€áˆáŒ§áˆ! ({media_type})\ná‰°áŒ¨áˆ›áˆª áˆˆáˆ›áˆµá‰€áˆ˜áŒ¥ /setprebookingmedia á‹µáŒ‹áˆš áŒ¥á‰€áˆµá¢")


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

    # NEW: winner-ðŸ”¥-reaction feature â€” this message's sender á‰°áˆ˜á‹áŒá‰¦ á‹­á‰€áˆ˜áŒ£áˆ
    # (DB write áŠá‹á£ event loop áŠ¥áŠ•á‹³á‹­á‹˜áŒˆá‹­ background thread áˆ‹á‹­ fire-and-forget
    # áˆ†áŠ– á‹­áˆ°áˆ«áˆá£ áˆáŠ•áˆ áŠá‰£áˆ­ áˆŽáŒ‚áŠ­ áŠ á‹­áŠáŠ«áˆ)
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

    # âœ… áˆ›áŠ“á‰¸á‹áˆ URL â†’ fetch á‹­áˆžáŠ­áˆ«áˆ (domain check á‹¨áˆˆáˆ)
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
            await msg.reply_text("á‰áŒ¥áˆ© á‹¨áŠ¥áˆ­áˆµá‹Ž áŠ á‹­á‹°áˆˆáˆ ðŸ™")
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
                    if is_half:
                        rebuilt_snap[n] = -1 if slots == {1} else (-2 if slots == {2} else 0)
                    else:
                        rebuilt_snap[n] = 0
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
                await msg.reply_text(f"{actual_num:02d} á‹¨áŠ¥áˆ­áˆµá‹Ž á‰áŒ¥áˆ­ áŠ á‹­á‹°áˆˆáˆ ðŸ™")
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
            await msg.reply_text(f"{from_num:02d} á‹¨áŠ¥áˆ­áˆµá‹Ž á‰áŒ¥áˆ­ áŠ á‹­á‹°áˆˆáˆ ðŸ™")
            return
        if to_num in paid:
            await msg.reply_text(f"{to_num:02d} âœ… á‰°áŠ¨ááˆáˆ áˆ˜á‰€á‹¨áˆ­ áŠ á‹­á‰»áˆáˆ ðŸ™")
            return
        if to_num in taken:
            await msg.reply_text(f"{to_num:02d} á‰°á‹­á‹Ÿáˆ á‰¤á‰°áˆ°á‰¥ áˆŒáˆ‹ áˆáˆ¨áŒ¥ ðŸ™")
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
                await msg.reply_text(f"{to_num:02d} áŠ áˆá‰°á‰»áˆˆáˆ ðŸ™")
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
                line = f"{num} â€” áˆáŠ­áŠ•á‹«á‰µ á‰³á‹ˆá‰€ ðŸ™"
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
        # FIX: áˆ˜áŒ€áˆ˜áˆªá‹« áŠ¥áŠ•á‹°á‰°áŒ»áˆá‹ (as-typed â€” "+" á‹¨áˆŒáˆ‹á‰¸á‹ áˆ™áˆ‰á£ "+" á‹«áˆ‹á‰¸á‹ áŒáˆ›áˆ½)
        # á‹ˆá‹²á‹«á‹áŠ‘ á‹­áˆ˜á‹˜áŒˆá‰£áˆá¤ áŒ¥á‹«á‰„á‹ áŠ¨á‹šá‹« á‰ áŠ‹áˆ‹ á‰¥á‰» á‹­áŒ á‹¨á‰ƒáˆ (áŠ«áˆµáˆáˆˆáŒˆ áˆˆá‹áŒ¥ á‰¥á‰»
        # handle_ambiguous_reply áˆ‹á‹­ á‹­á‹°áˆ¨áŒ‹áˆ)á¢ á‰€á‹µáˆž áˆá‹áŒˆá‰£á‹ áŒ¥á‹«á‰„á‹ áŠ¥áˆµáŠªáˆ˜áˆˆáˆµ
        # á‹µáˆ¨áˆµ á‹­áŒ á‰¥á‰… áŠá‰ áˆ­á£ á‹­áˆ…áˆ áˆŒáˆ‹ action á‰¢áˆ˜áŒ£ áˆá‹áŒˆá‰£ áˆ³á‹­áˆáŒ¸áˆ á‹­á‰€áˆ­ áŠá‰ áˆ­á¢
        await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)
        if ambiguous == "all_half":
            await msg.reply_text("áˆáˆ‰áŠ•áˆ á‰ áŒáˆ›áˆ½ áŠá‹? (áŠ á‹Ž/áŠ á‹­á‹°áˆˆáˆ)")
        elif ambiguous == "last_half":
            await msg.reply_text(f"{format_number(ambiguous_number)} á‰¥á‰» á‰ áŒáˆ›áˆ½ áŠá‹? (áŠ á‹Ž/áŠ á‹­á‹°áˆˆáˆ)")
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
    yes = text_lower in ["áŠ á‹Ž", "awo", "yes", "aha", "áŠ á‹ŽáŠ•"]
    no = text_lower in ["áŠ á‹­á‹°áˆˆáˆ", "aydelem", "no", "á‹¨áˆˆáˆ"]
    if not yes and not no:
        no = True

    numbers = pending["numbers"]
    ambiguous = pending["ambiguous"]
    ambiguous_number = pending["ambiguous_number"]
    settings = pending["settings"]

    del pending_ambiguous[user_id]

    # FIX: áˆá‹áŒˆá‰£á‹ á‰€á‹µáˆž (as-typed) á‰°áˆ˜á‹áŒá‰§áˆ â€” áŠ¥á‹šáˆ… á‹°áŒáˆž á‹¨áˆšá‹«áˆµáˆáˆáŒˆá‹ áˆˆá‹áŒ¥ á‰¥á‰»
    # áŠá‹ á‹¨áˆšá‹°áˆ¨áŒˆá‹ (register_number's toggle/target logic á‰€á‹µáˆž á‹¨á‰°áˆ˜á‹˜áŒˆá‰¡á‰µáŠ•
    # á‹ˆá‹° áŠ á‹²áˆ± half/full á‹­á‰€á‹­áˆ«áˆ)á¢ áˆˆá‹áŒ¥ á‹¨áˆ›á‹«áˆµáˆáˆáŒ áŠ¨áˆ†áŠ áˆáŠ•áˆ áŠ á‹­á‹°áˆ¨áŒáˆá¢
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

    # FIX #3: admin "#name <name>" override áŠ«áˆˆ (highest priority) â€”
    # parsed_name/telegram username áˆáŠ•áˆ á‹­áˆáŠ‘ áˆáˆŒáˆ override áˆµáˆ áŒ¥á‰…áˆ áˆ‹á‹­ á‹­á‹áˆ‹áˆá¢
    name_override = get_name_override(group_id, user_id)

    for num, is_half, parsed_name in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        nekay_snap_value = None
        if _gk(group_id, game_id) in nekay_numbers and actual_num in nekay_numbers.get(_gk(group_id, game_id), {}):
            nekay_snap_value = nekay_numbers[_gk(group_id, game_id)][actual_num]

        is_nekay = (nekay_snap_value is not None)
        # FIX: -1/-2 (06+1 / 06+2 slot-specific nekay) á‹°áŒáˆž force áŠ“á‰¸á‹ â€”
        # á‰€á‹°áˆ á‰¥áˆŽ 0 á‰¥á‰» áŠá‰ áˆ­ force á‰°á‰¥áˆŽ á‹¨áˆšá‰³á‹¨á‹á£ áˆµáˆˆá‹šáˆ… +1/+2 slot-specific
        # nekay áˆ‹á‹­ force overwrite áˆáŒ½áˆž áŠ á‹­áˆ°áˆ«áˆ áŠá‰ áˆ­á¢
        is_nekay_force = nekay_snap_value in (0, -1, -2)
        force_slot = None
        if nekay_snap_value == -1:
            force_slot = 1
        elif nekay_snap_value == -2:
            force_slot = 2

        # FIX: parsed_name (á‰°áŒ á‰ƒáˆšá‹ á‰ áŒ½áˆá á‹«áˆµáŒˆá‰£á‹ áˆµáˆ) áŠ¨ #name override á‹¨á‰ áˆˆáŒ 
        # á‰…á‹µáˆšá‹« á‹«áŒˆáŠ›áˆá¢ Override á‹¨áˆšáˆ°áˆ«á‹ á‰°áŒ á‰ƒáˆšá‹ áˆáŠ•áˆ áˆµáˆ áŠ«áˆáŒ»áˆ á‰¥á‰» áŠá‹
        # (default/fallback)á¢
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
                # FIX: á‰µáŠ­áŠ­áˆˆáŠ›á‹áŠ• slot á‹«áŒáŠ (is_paid áˆ›áˆ¨áŒ‹áŒˆáŒ« á‰µáŠ­áŠ­áˆˆáŠ›á‹áŠ• slot áŠ¥áŠ•á‹²áˆá‰µáˆ½)
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
            # FIX: is_half áŠ¥áŠ“ slot á‰µáŠ­áŠ­áˆˆáŠ›á‹áŠ• á‹áŒ¤á‰µ á‹«áŠ•á€á‰£áˆ­á‰ â€” á‰€á‹µáˆž "registered_half"
            # (áŠ á‹²áˆµ áˆ°á‹ á‰€á‹µáˆž á‰ áŒáˆ›áˆ½ á‹ˆá‹°á‰°á‹«á‹˜ á‰áŒ¥áˆ­ áˆ‹á‹­ "+" áˆ³á‹­áŒ á‰€áˆ áˆ²á‰€áˆ‹á‰€áˆ) is_half=False
            # á‰°á‰¥áˆŽ á‰ áˆµáˆ…á‰°á‰µ á‹­áˆ˜á‹˜áŒˆá‰¥ áŠá‰ áˆ­á£ á‹­áˆ…áˆ is_paid áˆ›áˆ¨áŒ‹áŒˆáŒ« á‹¨á‰°áˆ³áˆ³á‰° slot áŠ¥áŠ•á‹²áˆá‰µáˆ½
            # á‹«á‹°áˆ­áŒ áŠá‰ áˆ­ (á‹¨á‰°áˆ³áˆ³á‰° "still needs payment" áˆ˜áˆáŠ¥áŠ­á‰µ á‹«áˆ˜áŒ£ áŠá‰ áˆ­)á¢
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

    # FIX: board edit delay â€” get_taken_numbers/get_paid_numbers (psycopg2,
    # blocking) event loop áŠ• áŠ¥áŠ•á‹³á‹«áŒá‹µ asyncio.to_thread á‹áˆµáŒ¥ á‹­áˆ®áŒ£áˆ‰á¢ register_number
    # (áŠ¨áˆ‹á‹­ á‰£áˆˆá‹ loop á‹áˆµáŒ¥) áˆ†áŠ• á‰°á‰¥áˆŽ áŠ áˆá‰°áŠáŠ«áˆ â€” race condition áŠ¥áŠ•á‹³á‹­áˆáŒ áˆ­á¢
    taken = await asyncio.to_thread(get_taken_numbers, game_id)
    paid = await asyncio.to_thread(get_paid_numbers, game_id)
    remaining_count = count_remaining(settings, taken)
    snap = nekay_numbers.get(_gk(group_id, game_id), {})
    nekay_list = _build_nekay_from_snap(snap)

    if not registered and not all_taken and no_change_reply:
        await msg.reply_text("áŠ¥áˆº ðŸ™")
        return

    reg_result = "registered" if registered else ("taken" if all_taken else None)

    # FIX #2: áˆáˆ‰áˆ á‰áŒ¥áˆ®á‰½ âœ… (áˆáˆ‰áˆ á‰°áŠ¨ááˆˆá‹) áŠ«áˆˆá‰ á‰ áŠ‹áˆ‹ (á‹áŒ¤á‰µ áŒˆáŠ“ áŠ«áˆá‰³á‹ˆá‰€/pre-booking
    # áŒˆáŠ“ áŠ«áˆáŒ€áˆ˜áˆ¨)á£ áˆ°á‹ á‰áŒ¥áˆ­ áˆˆáˆ˜á‹«á‹ á‰¢áˆžáŠ­áˆ­ "á‰°á‰€á‹°áˆáŠ­" áŠ¨áˆ˜áˆ˜áˆˆáˆµ á‹­áˆá‰… "áŠ áˆáŠ• á‹¨á‹áŒ¤á‰µ áˆ°á‹“á‰µ
    # áŠá‹" á‹­áˆ˜áˆˆáˆµá¢
    if reg_result == "taken" and all_numbers_paid(game_id, settings):
        await msg.reply_text("áŠ áˆáŠ• á‹¨á‹áŒ¤á‰µ áˆ°á‹“á‰µ áŠá‹ á‰¤á‰°áˆ°á‰¥ á‰µáŠ•áˆ½ á‹­áŒ á‰¥á‰ ðŸ™")
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

    # FIX #1 + #6: pre-booking áˆ°á‹“á‰µ (á‹áŒ¤á‰µ/board áŒˆáŠ“ áˆµáˆ‹áˆá‰³á‹ˆá‰€ áŒˆáŠ•á‹˜á‰¡ áˆ›áŠ•
    # áŠ¥áŠ•á‹°áˆšá‹­á‹˜á‹ áŒˆáŠ“ áˆµáˆˆáˆ›á‹­á‰³á‹ˆá‰…) á‹¨á‰°áˆ³áŠ« áˆá‹áŒˆá‰£ áˆ‹á‹­ á‹¨áŒ½áˆá reply áˆ³á‹­áˆ†áŠ• ðŸ‘ reaction
    # á‰¥á‰» á‹­áˆ‹áŠ­á¢ á‹°áŒáˆžáˆ reply/reaction Telegram API call áŠ• fire-and-forget
    # (asyncio.create_task) áŠ á‹µáˆ­áŒˆáŠ• áŠ¥áŠ•áˆáŠ«áˆˆáŠ•á£ áˆµáˆˆá‹šáˆ… áŠ¨á‰³á‰½ á‹«áˆˆá‹ board edit
    # á‹­áˆ…áŠ• call áŠ¥áˆµáŠªáˆ˜áˆˆáˆµ á‹µáˆ¨áˆµ áˆ˜áŒ á‰ á‰… áŠ á‹«áˆµáˆáˆáŒˆá‹áˆ (á‰€á‹µáˆž sequential áˆµáˆˆáŠá‰ áˆ­ board
    # edit á‹­á‹˜áŒˆá‹­ áŠá‰ áˆ­)á¢
    if reg_result == "registered" and (group_id in prebooking_groups or group_id in winner_pending_groups):
        asyncio.create_task(_safe_set_reaction(ctx.bot, group_id, msg.message_id))
    elif resp["reply"]:
        if reg_result == "taken":
            # NEW: "áŠ¥áˆº/eshi" replacement feature á‹­áˆ…áŠ• rejection reply message_id
            # áŠ¥áŠ•á‹²á‹«áŒˆáŠ˜á‹ (á‹ˆá‹°áŠá‰µ admin á‰¢á‰°áŠ«á‹ áŠ¥áŠ•á‹²áŒ á‹) á‰°áˆ˜á‹áŒá‰¦ á‹­á‰€áˆ˜áŒ£áˆ
            asyncio.create_task(_safe_reply_text_and_track(msg, resp["reply"], group_id))
        else:
            asyncio.create_task(_safe_reply_text(msg, resp["reply"]))

    if not registered:
        return

    if skip_board_update:
        return

    # pre-booking mode (á‹ˆá‹­áˆ winner photo 30s áŠ­áá‰°á‰µ) â€” registration á‰°áˆ°áˆ­á‰·áˆ
    # áŒáŠ• board áŠ á‹­á‰³á‹­áˆ
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

        # FIX: intermittent nekay-list corruption â€” áŠ¨áˆ‹á‹­ snap áŠ¨á‰°áŠá‰ á‰  áŒ€áˆáˆ®
        # (áˆ˜áˆµáˆ˜áˆ­ ~1968) áŠ¥áˆµáŠ¨á‹šáˆ… á‹µáˆ¨áˆµ á‰¥á‹™ awaits (board/nekay message edits)
        # áˆµáˆ‹áˆ‰á£ 2 áˆ°á‹Žá‰½ á‰ á‰°áˆ˜áˆ³áˆ³á‹­ áˆ°á‹“á‰µ á‹¨á‰°áˆˆá‹«á‹¨ á‰áŒ¥áˆ­ á‰¢á‹­á‹™ (interleaved coroutines)
        # á‰ áŠ áŠ•á‹µ shared dict áˆ‹á‹­ á‰°á‹°áˆ«áˆ­á‰ á‹ áˆŠáŒ£áˆ¨áˆ± á‹­á‰½áˆ‹áˆ‰ (áˆŒáˆ‹á‹áŠ• entry áˆŠá‹«áŒ á‰
        # á‹­á‰½áˆ‹áˆ‰)á¢ áˆµáˆˆá‹šáˆ… áˆáŠ­ áŠ¨áˆ˜áŠ•áŠ«á‰± á‰ áŠá‰µ á‹¨á‰…áˆ­á‰¥ áŒŠá‹œá‹áŠ• nekay_numbers á‹°áŒáˆž
        # áŠ¥áŠ“áŠá‰¥á‰ á‹‹áˆˆáŠ• (race window áˆˆáˆ˜á‰€áŠáˆµ)á¢
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
    âœ…/? marker parsing â€” á‰°áŒ á‰ƒáˆšá‹ áŠ¥á‹áŠá‰°áŠ› áˆµáˆ áˆ«áˆ± "?" á‰¢á‹­á‹ (áˆˆáˆáˆ³áˆŒ áˆµáˆ™ á‰ á‰µáŠ­áŠ­áˆ
    "??" á‰¢áˆ†áŠ•) stripping áˆµáˆ™áŠ• áˆ™áˆ‰ áˆˆáˆ™áˆ‰ á‰£á‹¶ áŠ¥áŠ•á‹³á‹«á‹°áˆ­áŒˆá‹ á‹­áŒ á‰¥á‰ƒáˆá¦ stripping "?"
    áˆµáˆ™áŠ• á‰£á‹¶ á‹¨áˆšá‹«á‹°áˆ­áŒˆá‹ áŠ¨áˆ†áŠ (áŠ¥áŠ“ stripping áŠ¨áˆ˜á‹°áˆ¨áŒ‰ á‰ áŠá‰µ á‹­á‹˜á‰µ áŠá‰ áˆ¨) á‹« "?" áŠ¥áŠ•á‹°
    pending marker áˆ³á‹­áˆ†áŠ• á‹¨áˆµáˆ™ áŠ áŠ«áˆ á‰°á‹°áˆ­áŒŽ á‹­á‹«á‹›áˆá¢
    """
    paid = "âœ…" in raw
    no_check = raw.replace("âœ…", "").strip()
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
# NEW â€” WINNER "ðŸ”¥ REACTION" BALANCE-CLEAR FEATURE
# Admin puts a native ðŸ”¥ reaction on any message previously sent BY a
# recent winner (1áŠ›/2áŠ›/3áŠ›) in the group â†’ that winner's balance ONLY
# gets cleared (exactly like /clearbalance @username, by telegram_id).
# Board/registrations/paid status áŠ“á‰¸á‹ untouched â€” user_balance á‰¥á‰» áŠá‹
# á‹¨áˆšáŒ¸á‹³á‹á¢ Confirmation message ("âœ… ... áŒ¸á‹µá‰·áˆ") á‹­áˆ‹áŠ«áˆ áŠ¥áŠ“ 1.5 áˆ°áŠ¨áŠ•á‹µ á‰†á‹­á‰¶
# áˆ«áˆ± á‹­áŒ á‹áˆ (_send_temp_admin_message helper á‰°áŒ á‰…áˆž)á¢
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

    if "ðŸ”¥" not in new_emojis:
        return

    old_emojis = set()
    for r in (reaction.old_reaction or []):
        emoji = getattr(r, "emoji", None)
        if emoji:
            old_emojis.add(emoji)

    if "ðŸ”¥" in old_emojis:
        # á‰€á‹µáˆžá‹áŠ‘ ðŸ”¥ áŠá‰ áˆ¨á‹ (áŠ á‹²áˆµ addition áŠ á‹­á‹°áˆˆáˆ) â€” á‹µáŒ‹áˆš balance áˆ›áŒ½á‹³á‰µ áŠ á‹«áˆµáˆáˆáŒáˆ
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

    # âœ… "cleared" áˆ›áˆ¨áŒ‹áŒˆáŒ« message á‹­áˆ‹áŠ«áˆá£ áˆáŠ­ áŠ¥áŠ•á‹° nekay 1.5 áˆ°áŠ¨áŠ•á‹µ á‰†á‹­á‰¶ áˆ«áˆ± á‹­áŒ á‹áˆ
    await _send_temp_admin_message(
        ctx.bot, group_id, f"âœ… {target_name} á‰£áˆ‹áŠ•áˆµ áŒ¸á‹µá‰·áˆ", delay=1.5,
    )


async def handle_winner_correction_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group áˆ‹á‹­ bot winner announcement áˆ‹á‹­ '#/ 10 20 31' reply áˆ²á‹«á‹°áˆ­áŒ
    handle_winner_correction á‹­áŒ áˆ«á¢
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

    # reply to bot message á‰¥á‰» á‹­áˆ°áˆ«
    if not msg.reply_to_message:
        return
    if not msg.reply_to_message.from_user:
        return
    if not msg.reply_to_message.from_user.is_bot:
        return

    # 'Winners!' á‹ˆá‹­áˆ 'Winners (á‰°áˆµá‰°áŠ«áŠ¨áˆˆ)' announcement áˆ‹á‹­ á‰¥á‰»
    replied_text = msg.reply_to_message.text or ""
    if "ðŸ†" not in replied_text and "Winners" not in replied_text:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    from handlers import handle_winner_correction, parse_winner_correction
    numbers = parse_winner_correction(text)
    if not numbers:
        await msg.reply_text("âŒ áˆáˆ³áˆŒ: #/ 10  á‹ˆá‹­áˆ  #/ 10 20  á‹ˆá‹­áˆ  #/ 10 20 31")
        return

    # DB áˆ‹á‹­ á‹«áˆ‰ current winners á‹«áˆáŒ£ (áˆˆ reverse á‹«áˆµáˆáˆáŒ‹áˆ‰)
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

    # previous_winners format áˆˆ handle_winner_correction
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
                SELECT slot, user_id, user_name, is_paid, is_half FROM registrations
                WHERE game_id=%s AND number=%s
            """, (game_id, number))
            existing_rows = cur_check.fetchall()
            cur_check.close()
            conn_check.close()
            uid_map = {row[0]: row[1] for row in existing_rows}
            name_map = {row[0]: row[2] for row in existing_rows}
            paid_map = {row[0]: row[3] for row in existing_rows}
            half_map = {row[0]: row[4] for row in existing_rows}
            was_paid1 = bool(paid_map.get(1, False))

            # FIX: admin á‰¥á‹™ áŒŠá‹œ áˆ™áˆ‰á‹áŠ• board áŒ½áˆá áŠ®á’ áŠ á‹µáˆ­áŒŽ (á‹¨áˆáˆˆáŒˆá‹áŠ• 1 áˆ˜áˆµáˆ˜áˆ­
            # á‰¥á‰» á‰€á‹­áˆ®) reply á‹«á‹°áˆ­áŒ‹áˆ â€” áˆµáˆˆá‹šáˆ… _parse_board_text() á‹«áˆá‰°áŠáŠ©á‰µáŠ•áˆ
            # áˆ˜áˆµáˆ˜áˆ®á‰½ (áˆáˆ‰áŠ•áˆ á‰áŒ¥áˆ®á‰½) áŒ­áˆáˆ­ á‹­áˆ˜áˆáˆ³áˆá¢ á‹­áˆ… line áŠ¨ DB á‹áˆµáŒ¥ áŠ«áˆˆá‹ áŒ‹áˆ­
            # ááŒ¹áˆ á‰°áˆ˜áˆ³áˆ³á‹­ (áˆáŠ•áˆ á‹«áˆá‰°á‰€á‹¨áˆ¨) áŠ¨áˆ†áŠ áŒ¨áˆ­áˆ¶ áŠ áŠ•áŠ•áŠ«á‹áˆ â€” áŠ áˆˆá‰ áˆˆá‹šá‹«
            # admin_remove_player+register_number (is_nekay áˆáˆáŒŠá‹œ FALSE
            # áŠ á‹µáˆ­áŒŽ áˆµáˆˆáˆšá‹«áˆµáŒˆá‰£) á‹«áˆá‰°áŠáŠ© á‰áŒ¥áˆ®á‰½ áˆ‹á‹­ á‹«áˆˆá‹áŠ• is_nekay áˆáŠ”á‰³ á‹«áŒ á‹á‹‹áˆ
            # (á‹­áˆ… áŠá‹ áŠá‰ƒá‹­ list áˆ™áˆ‰ áˆˆáˆ™áˆ‰ á‹µáŠ•áŒˆá‰µ á‹­áŒ á‹ á‹¨áŠá‰ áˆ¨á‹ á‰µáŠ­áŠ­áˆˆáŠ› áˆáŠ­áŠ•á‹«á‰µ)á¢
            #
            # FIX #2: is_half á‹°áŒáˆž áˆ›áŠáŒ»áŒ¸áˆ­ áŠ áˆˆá‰ á‰µ â€” áŠ¨á‹šáˆ… á‰ áŠá‰µ áˆµáˆ/paid á‰¥á‰» áŠá‰ áˆ­
            # á‹¨áˆšáŠáŒ»áŒ¸áˆ¨á‹á£ áˆµáˆˆá‹šáˆ… "á‰ áˆ™áˆ‰ á‹¨áŠá‰ áˆ¨ á‰áŒ¥áˆ­ á‹ˆá‹° áŒáˆ›áˆ½ áˆ˜á‰€á‹¨áˆ­" (áˆµáˆ/paid
            # á‰°áˆ˜áˆ³áˆ³á‹­ áˆ†áŠ– is_half á‰¥á‰» áˆ²á‰€á‹¨áˆ­) áŒ¨áˆ­áˆ¶ "áˆáŠ•áˆ áŠ áˆá‰°á‰€á‹¨áˆ¨áˆ" á‰°á‰¥áˆŽ á‹­á‰³áˆˆá
            # áŠá‰ áˆ­ â€” admin áˆ˜áŒ€áˆ˜áˆªá‹« á‰£á‹¶ áŠ á‹µáˆ­áŒŽ áŠ¨á‹šá‹« áŠ¥áŠ•á‹°áŒˆáŠ“ áˆ²áŒ½á á‰¥á‰» á‹­áˆ°áˆ« á‹¨áŠá‰ áˆ¨á‹
            # áˆˆá‹šáˆ… áŠá‹á¢
            current_name1 = name_map.get(1)
            current_paid1 = bool(paid_map.get(1, False))
            current_is_half1 = bool(half_map.get(1, False))
            current_name2 = name_map.get(2)
            current_paid2 = bool(paid_map.get(2, False))
            if (name1 == current_name1 and paid1 == current_paid1
                    and is_half1 == current_is_half1
                    and name2 == current_name2 and paid2 == current_paid2):
                continue

            # FIX: slot1/slot2 áŠ• á‰°áŠáŒ£áŒ¥áˆŽ áˆ›áŠáŒ»áŒ¸áˆ­ (áŠ¨á‹šáˆ… á‰ áŠá‰µ áˆáˆˆá‰±áˆ slots
            # áˆ‹á‹­ á‰µáŠ•áˆ½ áˆˆá‹áŒ¥ áŠ¥áŠ•áŠ³ á‰¢áŠ–áˆ­ áˆáˆˆá‰±áˆ á‹­áˆ°áˆ¨á‹™ áŠá‰ áˆ­ â€” áˆµáˆˆá‹šáˆ… á‹«áˆá‰°áŠáŠ«á‹ slot
            # (áˆˆáˆáˆ³áˆŒ nekay/unpaid á‹¨áˆ†áŠ) áŒ­áˆáˆ­ á‹­áŒ á‹ áŠá‰ áˆ­)
            slot1_changed = not (name1 == current_name1 and paid1 == current_paid1
                                 and is_half1 == current_is_half1)
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
                if is_half:
                    snap[number] = -1 if slots == {1} else (-2 if slots == {2} else 0)
                else:
                    snap[number] = 0
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
# OWNER REASSIGNMENT â€” admin replies to a REAL USER's message with
# "#/ 01 21 31+1" to attach that user's telegram_id to numbers that
# were registered manually (board edit / /register) without a real
# telegram user_id. Only fixes ownership (user_id) â€” user_name and
# paid status entered by the admin are left untouched.
#   #/ 01        â†’ number 1, all slots â†’ this user
#   #/ 31+1      â†’ number 31, slot 1 only â†’ this user
#   #/ 11        â†’ if number 11 already belongs to someone else,
#                   ownership is transferred to this user
# ============================================================

async def handle_owner_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # âœ… FIX: 2 áˆ™áˆ‰ á‰ áˆ™áˆ‰ á‹¨á‰°áˆˆá‹«á‹© syntax â€” áŠ¥áŠ•á‹³á‹­áˆá‰³á‰± (á‹­áˆ… áá‰°áˆ» á‰€á‹µáˆž áŠ¥áŠ•á‹²á‹°áˆ¨áŒ
    # á‰°áŠ•á‰€áˆ³á‰…áˆ·áˆá£ áˆµáˆˆá‹šáˆ… "#" á‰£áˆáŒ€áˆ˜áˆ¨ message áˆ‹á‹­ á‹‹áŒ‹ á‹¨áˆŒáˆˆá‹ DB call áŠ á‹­á‹°áˆ¨áŒáˆ)
    #   (#<amount> winner áŠ­áá‹« á‰°á‹ˆáŒá‹·áˆ â€” áˆˆá‹šá‹« ðŸ”¥ reaction á‹­áŒ á‰€áˆ™)
    #   "#/ NUM ..."  (áˆµáˆ‹áˆ½ áŠ áˆˆá‹)  â†’ Owner reassignment á‰¥á‰», áˆˆáˆáˆ³áˆŒ #/ 01 21 31+1
    #   "#name <áˆµáˆ>"  â†’ FIX #3: name override, áˆˆáˆáˆ³áˆŒ #name áŠ á‰ á‰  á‹ˆá‹­áˆ #name áŠ á‰ á‰  áŠ¨á‰ á‹°
    #                    "#name" á‰¥á‰» (áˆµáˆ áˆ³á‹­áŠ¨á‰°áˆ) â†’ override reset
    #   "##cancel"    â†’ payment-fingerprint feature: á‹« user's fingerprint á‹«áŒ á‹áˆ
    #   "##<SMS text>" â†’ payment-fingerprint feature: admin áˆ«áˆ± á‹¨á‹°áˆ¨áˆ°á‹áŠ• SMS
    #                    áŒ½áˆá áŠ®á’ áŠ á‹µáˆ­áŒŽ reply á‹«á‹°áˆ­áŒ‹áˆ â†’ AI parse â†’ confirm_payment
    #                    + fingerprint learn (á‹ˆá‹°áŠá‰µ "áˆáŠ¬á‹«áˆˆá‹" áˆ«áˆµ-áˆ°áˆ­ áŠ¥áŠ•á‹²áˆ†áŠ•)
    #   "# NUM[+SLOT][âœ…] ..." â†’ reply-to-user (á‰°á‹­á‹žá‰¥áˆƒáˆ á‹«áˆˆá‰ á‰µ
    #                    áŠ¦áˆ­áŒ…áŠ“áˆ message áˆ‹á‹­ reply) á‰£áˆˆá‰¤á‰µ+áˆµáˆ á‹­á‰°áŠ«áˆá£ âœ… áŠ«áˆˆ paid
    #                    á‰°á‰¥áˆŽ á‹­áˆ˜á‹˜áŒˆá‰£áˆá£ á‰€á‹°áˆ á‹«áˆˆá‹ bot rejection message á‹­áŒ á‹áˆá£
    #                    "NUM á‰°á‹­á‹žáˆáˆƒáˆ ðŸ™" áŠ á‹²áˆµ message á‹­áˆ‹áŠ«áˆá¢ "#" prefix áŒá‹µ
    #                    áŠá‹á¢
    is_sms_cancel_form = text.lower().startswith("##cancel")
    is_sms_paste_form = text.startswith("##") and not is_sms_cancel_form
    is_name_form = text.lower().startswith("#name")
    is_owner_form = text.startswith("#/")
    # "# NUM[+SLOT][âœ…] ..." â€” á‰£áˆˆá‰¤á‰µ+áˆµáˆ áˆ˜á‰°áŠªá‹« (á‹¨á‰€á‹µáˆžá‹ #eshi/#áŠ¥áˆº áˆµáˆ« áŠ áˆáŠ• á‰  "#" á‰¥á‰»)
    is_eshi_form = (
        text.startswith("#") and not text.startswith("#/")
        and not text.startswith("##") and not is_name_form
    )
    if not (is_owner_form or is_name_form or is_sms_cancel_form or is_sms_paste_form or is_eshi_form):
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
        if is_eshi_form:
            await msg.reply_text("âŒ áŠ•á‰ áŒ¨á‹‹á‰³ á‹¨áˆˆáˆ (active game required)")
        return

    # winner-correction replies (reply to the BOT's Winners announcement)
    # are handled by handle_winner_correction_reply â€” this handler is only
    # for replies to a REAL USER's message (ownership fix / payment).
    if not msg.reply_to_message:
        logging.info("[OwnerReply] Rejected: not a reply to any message")
        if is_eshi_form:
            await msg.reply_text("âŒ # á‹¨á‰°áŒ á‰ƒáˆšá‹áŠ• message áˆ‹á‹­ reply á‰°á‹°áˆ­áŒŽ áˆ˜áŒ»á áŠ áˆˆá‰ á‰µ")
        return
    if not msg.reply_to_message.from_user:
        logging.info("[OwnerReply] Rejected: reply_to_message has no from_user")
        if is_eshi_form:
            await msg.reply_text("âŒ á‹­áˆ… message áˆ‹á‹­ reply áˆ›á‹µáˆ¨áŒ áŠ á‹­á‰»áˆáˆ")
        return
    if msg.reply_to_message.from_user.is_bot:
        logging.info("[OwnerReply] Rejected: replied-to message is from the bot (handled elsewhere)")
        if is_eshi_form:
            await msg.reply_text("âŒ # á‹¨ bot message áˆ‹á‹­ áˆ³á‹­áˆ†áŠ• á‹¨á‰°áŒ á‰ƒáˆšá‹áŠ• áŠ¦áˆ­áŒ…áŠ“áˆ message áˆ‹á‹­ reply áˆ˜á‹°áˆ¨áŒ áŠ áˆˆá‰ á‰µ")
        return

    owner = msg.reply_to_message.from_user
    owner_id = owner.id

    import re as _re_owner

    # ============================================================
    # FIX #3: "#name <name>" â€” name override reply-to-user command
    # "#name" á‰¥á‰» (áˆµáˆ áˆ³á‹­áŠ¨á‰°áˆ) â†’ override á‹­áŒ á‹áˆá£ á‹ˆá‹° original áˆµáˆ-áˆ˜áˆˆá‹« logic
    # á‹­áˆ˜áˆˆáˆ³áˆ (parsed_name áˆ«áˆ± áŠ áˆá‰°áŠáŠ«áˆ)á¢ admin á‹°áŒ‹áŒáˆž áˆŠá‰€á‹­áˆ¨á‹ á‹­á‰½áˆ‹áˆ â€” áˆáˆáŒŠá‹œ
    # á‹¨áˆ˜áŒ¨áˆ¨áˆ»á‹ á‰µá‹•á‹›á‹ á‹­áˆ°áˆ«áˆá¢ admin's own "#name ..." message á‹ˆá‹²á‹«á‹áŠ‘ á‹­áŒ á‹áˆ
    # (áˆáŠ­ áŠ¥áŠ•á‹° #/ áŠ¥áŠ“ # á‰µá‹•á‹›á‹žá‰½)á¢
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
    # "##cancel" â€” admin á‹¨á‰°áˆ³áˆ³á‰° fingerprint (áˆµáˆ/last4) áŠ«áˆµá‰€áˆ˜áŒ  áˆˆá‹šáˆ… user
    # (reply-to-user) á‹«áˆˆá‹áŠ• fingerprint áˆ™áˆ‰ á‰ áˆ™áˆ‰ á‹«áŒ á‹áˆá¢
    # ============================================================
    if is_sms_cancel_form:
        delete_user_fingerprint(group_id, owner_id)
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        winner_name = owner.first_name or owner.username or "Unknown"
        await _send_temp_admin_message(ctx.bot, group_id, f"âœ… {winner_name} fingerprint áŒ á‹")
        return

    # ============================================================
    # "##<SMS text>" â€” admin á‹¨á‹°áˆ¨áˆ°á‹áŠ• á‰µáŠ­áŠ­áˆˆáŠ› SMS áŒ½áˆá áŠ®á’ áŠ á‹µáˆ­áŒŽ user's
    # message áˆ‹á‹­ reply á‹«á‹°áˆ­áŒ‹áˆá¢ AI (Groq) parse á‹«á‹°áˆ­áŒˆá‹‹áˆá£ áˆµáˆ/last4
    # áŠ«áŒ£ á‰¥á‰» (URL áŠ«áˆˆ) Jina+Groq áˆ™áˆ‰ receipt á‹«áˆ˜áŒ£áˆá£ áŠ¨á‹› reply-to á‹«áˆˆá‹
    # owner_id áˆ‹á‹­ á‰ á‰€áŒ¥á‰³ confirm_payment() á‰°áŒ áˆ­á‰¶ fingerprint á‹­áˆ›áˆ«áˆá¢
    # ============================================================
    if is_sms_paste_form:
        sms_text = text[2:].strip()
        if not sms_text:
            await msg.reply_text("âŒ áˆáˆ³áˆŒ: ##<SMS áŒ½áˆá áŠ®á’ áŠ á‹µáˆ­áŒˆáˆ… áˆˆáŒ¥á>")
            return

        settings_for_sms = get_active_settings(group_id=group_id)
        result = await handle_admin_sms_paste(ctx.bot, msg, sms_text, owner_id, group_id)

        if not result.get("success"):
            await msg.reply_text("âŒ SMS áˆŠá‰°áŠá‰°áŠ• áŠ áˆá‰»áˆˆáˆ â€” áŒ½áˆá‰áŠ• áŠ¥áŠ•á‹°áŒˆáŠ“ áŠ®á’ áŠ á‹µáˆ­áŒˆáˆ… áˆ‹áŠ­")
            return

        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        winner_name = owner.first_name or owner.username or "Unknown"
        amount = result.get("amount")
        await _send_temp_admin_message(
            ctx.bot, group_id, f"âœ… {winner_name} â†’ ETB {amount} á‰°áˆ¨áŒ‹áŒáŒ§áˆ (SMS)"
        )

        if settings_for_sms:
            await _refresh_board(ctx, settings_for_sms, group_id)
        return

    # ============================================================
    # NEW â€” "# NUM[+SLOT][âœ…] ..." REPLACEMENT (reply-to-user's own
    # "01" attempt message, áˆáŠ­ áŠ«áˆˆáˆá‹ á‹ˆá‹­áˆ áŒˆáŠ“ áŠ«áˆˆá‹ rejection ("á‰°á‹­á‹žá‰¥áˆƒáˆ") áŒ‹áˆ­)á¢
    # á‰£áˆˆá‰¤á‰µ+áˆµáˆ á‹­á‰°áŠ«áˆá£ âœ… áŠ«áˆˆ á‹« á‰áŒ¥áˆ­ paid á‰°á‰¥áˆŽ á‹­áˆ˜á‹˜áŒˆá‰£áˆ (áŠ«áˆáˆ†áŠ unpaid á‹­áˆ†áŠ“áˆ)á£
    # á‰€á‹°áˆ á‹«áˆˆá‹ bot rejection message á‹­áŒ á‹áˆá£ "NUM á‰°á‹­á‹žáˆáˆƒáˆ ðŸ™" áŠ á‹²áˆµ message
    # áˆˆ user á‹­áˆ‹áŠ«áˆá£ board áˆ‹á‹­ áˆµáˆ á‹­á‰€á‹¨áˆ«áˆá¢
    # ============================================================
    if is_eshi_form:
        settings_eshi = get_active_settings(group_id=group_id)
        if not settings_eshi:
            return
        game_id_eshi = settings_eshi["id"]

        eshi_body = text[1:].strip()

        eshi_parts = [p for p in _re_owner.split(r'[,\s]+', eshi_body.strip()) if p]
        if not eshi_parts:
            await msg.reply_text("âŒ áˆáˆ³áˆŒ: # 01 á‹ˆá‹­áˆ # 01+2 06âœ…")
            return

        target_name = owner.first_name or owner.username or "Unknown"

        assigned = []
        errors = []
        for part in eshi_parts:
            mark_paid = "âœ…" in part
            clean_part = part.replace("âœ…", "")
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

            if not is_half:
                # FIX: áˆ™áˆ‰ (full) áŠ¨áˆ†áŠ â€” áŠá‰£áˆ­ slot(s) (á‰£á‹¶á£ áŒáˆ›áˆ½á£ á‹ˆá‹­áˆ áˆ™áˆ‰
                # á‹­áˆáŠ‘) áˆáŠ•áˆ á‹­áˆáŠ‘ áŠ•ááˆ… á‰ áŠ áŠ•á‹µ full row á‹­á‰°áŠ«áˆá¢ admin_replace_owner
                # á‰¥á‰» á‰¢áŒ á‰€áˆ (UPDATE á‰¥á‰») is_half áŠ á‹­áŠáŠ«áˆ/ á‰°áŒ¨áˆ›áˆª slot2 row
                # áŠ á‹­áŒ á‹áˆ áŠá‰ áˆ­ â€” áˆµáˆˆá‹šáˆ… áŒáˆ›áˆ½â†’áˆ™áˆ‰ change áˆáŒ½áˆž áŠ á‹­áˆ°áˆ«áˆ áŠá‰ áˆ­á¢
                found = False
                try:
                    conn_full = get_conn()
                    cur_full = conn_full.cursor()
                    cur_full.execute(
                        "DELETE FROM registrations WHERE game_id=%s AND number=%s",
                        (game_id_eshi, number),
                    )
                    cur_full.execute("""
                        INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                        VALUES (%s, %s, %s, %s, FALSE, 1, %s, FALSE, FALSE)
                    """, (game_id_eshi, owner_id, target_name, number, mark_paid))
                    conn_full.commit()
                    cur_full.close()
                    conn_full.close()
                    found = True
                except Exception as e:
                    logging.warning(f"[Eshi] full-conversion error: {e}")

                if found:
                    assigned.append(f"{number:02d}")
                else:
                    errors.append(part)
                continue

            if slot is None and is_half:
                # FIX: "01+" (á‹¨á‰µáŠ›á‹ slot áŠ¥áŠ•á‹³áˆáŒˆáˆˆáŒ½áŠ­) áˆ²á‰£áˆ â€” áŠá‰£áˆ­ registration
                # áŠ«áˆˆ (áˆˆáˆáˆ³áˆŒ slot1=áŠ á‰ á‰ )á£ áŠ­áá‰µ slot áŠ• (slot2) á‰¥á‰» áŠá‹ áˆ˜á‹«á‹
                # á‹«áˆˆá‰ á‰µ â€” áŠá‰£áˆ©áŠ• (áŠ á‰ á‰ áŠ•) áŒ¨áˆ­áˆ¶ áˆ˜á‰°áŠ«á‰µ á‹¨áˆˆá‰ á‰µáˆá¢ á‹¨á‰µáŠ›á‹ slot áŠ­áá‰µ
                # áŠ¥áŠ•á‹°áˆ†áŠ áŠ áˆ¨áŒ‹áŒáŒ¦ á‰¥á‰» á‹­áŠáŠ«áˆá¢
                try:
                    conn_chk = get_conn()
                    cur_chk = conn_chk.cursor()
                    cur_chk.execute("""
                        SELECT slot FROM registrations WHERE game_id=%s AND number=%s
                    """, (game_id_eshi, number))
                    existing_slots_eshi = {r[0] for r in cur_chk.fetchall()}
                    cur_chk.close()
                    conn_chk.close()
                except Exception as e:
                    logging.warning(f"[Eshi] slot lookup error: {e}")
                    existing_slots_eshi = set()

                if existing_slots_eshi == {1}:
                    slot = 2
                elif existing_slots_eshi == {2}:
                    slot = 1
                elif not existing_slots_eshi:
                    slot = 1
                else:
                    errors.append(part + " (áˆ™áˆ‰ á‰°á‹­á‹Ÿáˆ)")
                    continue

            found = admin_replace_owner(
                game_id_eshi, number, owner_id, target_name,
                slot=slot, mark_paid=mark_paid,
            )

            if not found:
                # NEW: á‰áŒ¥áˆ© á‰£á‹¶ (áˆáŠ•áˆ registration áˆµáˆ‹áˆáŠá‰ áˆ¨ replace á‹«áˆá‰°áˆ³áŠ«)
                # áŠ¨áˆ†áŠ â€” replace á‰¥á‰» áˆ³á‹­áˆ†áŠ• áŠ á‹²áˆµ registration á‹°áŒáˆž á‹­ááŒ áˆ­
                # (register_number()'s force_slot path is_nekay=TRUE á‹¨áˆšáŒ á‹­á‰…
                # áˆµáˆˆáˆ†áŠ áŠ¥áŠ“ áˆŒáˆ‹áŠ›á‹ slot áŠá‰£áˆ­ á‰¢áˆ†áŠ• á‰µáŠ­áŠ­áˆ áˆµáˆˆáˆ›á‹­áˆ°áˆ«á£ á‰ á‰€áŒ¥á‰³ INSERT
                # áŠ¥áŠ•áŒ á‰€áˆ›áˆˆáŠ• â€” admin override áˆµáˆˆáˆ†áŠ balance áŠ á‹­áŠáŠ«áˆ)
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
                await msg.reply_text(f"âŒ á‹«áˆá‰°áŒˆáŠ˜: {', '.join(errors)}")
            return

        # á‰€á‹°áˆ á‹«áˆˆá‹ bot "á‰°á‹­á‹žá‰¥áˆƒáˆ" rejection message áŠ«áˆˆ á‹­áŒ á‹
        rejection_key = (group_id, msg.reply_to_message.message_id)
        old_rejection_msg_id = _taken_rejection_msgs.pop(rejection_key, None)
        if old_rejection_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=old_rejection_msg_id)
            except Exception:
                pass

        # admin's own "# ..." command message á‹­áŒ á‹
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        # áŠ á‹²áˆµ "NUM á‰°á‹­á‹žáˆáˆƒáˆ ðŸ™" confirmation áˆˆ user (reply-to áŠ¦áˆ­áŒ…áŠ“áˆ message)
        numbers_label = " ".join(assigned)
        try:
            await msg.reply_to_message.reply_text(f"{numbers_label} á‰°á‹­á‹žáˆáˆƒáˆ ðŸ™")
        except Exception as e:
            logging.warning(f"[Eshi] confirmation reply error: {e}")

        if errors:
            await _send_temp_admin_message(ctx.bot, group_id, f"âŒ á‹«áˆá‰°áŒˆáŠ˜: {', '.join(errors)}")

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _refresh_board(ctx, fresh, group_id)
        return

    # ============================================================
    # OWNER REASSIGNMENT â€” "#/ NUM NUM+SLOT" á‰¥á‰» (áˆµáˆ‹áˆ½ áŠ áˆˆá‹)á£ active
    # game á‹«áˆµáˆáˆáŒˆá‹‹áˆ (total_numbers áˆ›áˆ¨áŒ‹áŒˆáŒ¥ áˆµáˆ‹áˆˆá‰ á‰µ)
    # ============================================================
    settings = get_active_settings(group_id=group_id)
    if not settings:
        return
    game_id = settings["id"]

    parts = text[2:].strip().split()
    if not parts:
        await msg.reply_text("âŒ áˆáˆ³áˆŒ: #/ 01 21 31+1")
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
        reply_lines.append(f"âœ… {', '.join(assigned)} â†’ á‰£áˆˆá‰¤á‰µ á‰°áˆµá‰°áŠ«áŠ­áˆáˆ!")
    if errors:
        reply_lines.append(f"âŒ á‹«áˆá‰°áŒˆáŠ˜: {', '.join(errors)}")

    if assigned:
        # âœ… á‰°á‰€á‰£á‹­áŠá‰µ áˆµáˆ‹áŒˆáŠ˜ (á‰¢á‹«áŠ•áˆµ áŠ áŠ•á‹µ á‰áŒ¥áˆ­ áˆµáˆˆá‰°áˆµá‰°áŠ«áŠ¨áˆˆ) admin's own
        # "#/ ..." message á‹­áŒ á‹áˆ â€” áˆáŠ­ áŠ¥áŠ•á‹° board reply
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        if reply_lines:
            # FIX #4: admin confirmation message áŠ¨1.5-2 áˆ°áŠ¨áŠ•á‹µ á‰ áŠ‹áˆ‹ áˆ«áˆ± á‹­áŒ á‹áˆ
            await _send_temp_admin_message(ctx.bot, group_id, "\n".join(reply_lines))
    elif reply_lines:
        # áˆáŠ•áˆ áŠ«áˆá‰°áˆµá‰°áŠ«áŠ¨áˆˆ message áŠ¥áŠ•á‹³áˆˆ á‹­á‰†á‹«áˆ (admin áˆáŠ• áŠ¥áŠ•á‹°áŒ»áˆ áŠ¥áŠ•á‹²á‹«á‹­)
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
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /remove 5  á‹ˆá‹­áˆ  /remove 5:1 10 15:2  á‹ˆá‹­áˆ  5+1 15+2")
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
                # âœ… FIX: NUM+SLOT (áˆˆáˆáˆ³áˆŒ 5+1 á‹ˆá‹­áˆ 5+2) â€” áˆáŠ­ áŠ¥áŠ•á‹° /nekay slot áˆ˜áˆˆá‹«
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = None
            # âœ… FIX: 1-5 á‰¡á‹µáŠ• á‰¢áˆ†áŠ• (numbers_per_person>1)á£ group start á‹­áˆ†áŠ“áˆ
            actual_num = get_group_start(number, per_person) if per_person > 1 else number
            admin_remove_player(settings["id"], actual_num, slot)
            label = f"{format_number(actual_num)}:{slot}" if slot else format_number(actual_num)
            removed.append(label)
        except ValueError:
            errors.append(part)

    # âœ… FIX: duplicate board â€” _check_all_paid_and_resend áŠ¥á‹šáˆ… áˆ˜áŒ áˆ«á‰µ
    # á‹¨áˆˆá‰ á‰µáˆ áŠá‰ áˆ­ (áˆ›áˆµá‹ˆáŒˆá‹µ á‹áŒ¤á‰µ "áˆáˆ‰áˆ á‰°áŠ¨ááˆáˆ" áˆáŒ½áˆž áˆ›áˆáŒ£á‰µ áˆµáˆˆáˆ›á‹­á‰½áˆá£ á‹«áŠ•áŠ•
    # á‹­áˆ… function áˆ«áˆ± áŠ«áˆµáˆáˆˆáŒˆ resend áˆµáˆˆáˆšá‹«á‹°áˆ­áŒ áŠ¨ _refresh_board's edit áŒ‹áˆ­
    # áŒáŒ­á‰µ á‹áˆµáŒ¥ áŒˆá‰¥á‰¶ 2 board messages á‹­áˆáŒ¥áˆ­ áŠá‰ áˆ­)
    await _refresh_board(ctx, settings, group_id)

    msg = ""
    if removed:
        msg += f"âœ… {', '.join(removed)} á‰°á‹ˆáŒ£!"
    if errors:
        msg += f"\nâŒ á‹«áˆá‰°á‰€á‰ áˆˆ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_paid_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /paid 5 10 15  á‹ˆá‹­áˆ  /paid 5:2  á‹ˆá‹­áˆ  5+2")
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
                # âœ… FIX: NUM+SLOT (áˆˆáˆáˆ³áˆŒ 5+1 á‹ˆá‹­áˆ 5+2) â€” áˆáŠ­ áŠ¥áŠ•á‹° /nekay slot áˆ˜áˆˆá‹«
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = 1
            # âœ… FIX: 1-5 á‰¡á‹µáŠ• á‰¢áˆ†áŠ• (numbers_per_person>1)á£ group start á‹­áˆ†áŠ“áˆ
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

    mark = "âœ…" if is_paid else "âŒ"
    updated_str = ", ".join(f"{format_number(n)}:{s}" for n, s in updated)
    msg = f"{mark} {updated_str} updated!"
    if errors:
        msg += f"\nâŒ á‹«áˆá‰°á‰€á‰ áˆˆ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
        return

    # pre-booking mode â€” registrations á‰€á‹µáˆž áŠ áˆ‰á£ board á‰¥á‰» á‹­áˆ‹áŠ­
    if group_id in prebooking_groups:
        prebooking_groups.discard(group_id)
        clear_prize_balance(group_id)

        # balance áŠ«áˆˆá‹ pre-booked registrations âœ… á‹«á‹°áˆ­áŒ‹á‰¸á‹‹áˆ
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
        await update.message.reply_text("âœ… áŠ á‹²áˆµ áŒ¨á‹‹á‰³ á‰°áŒ€áˆáˆ¯áˆ!")
        return

    clear_prize_balance(group_id)
    clear_carry_balance(group_id)
    clear_game(settings["id"])
    nekay_active.discard(_gk(group_id, settings["id"]))
    admin_nekay_games.discard(_gk(group_id, settings["id"]))
    active_countdowns.pop(_gk(group_id, settings["id"]), None)
    nekay_numbers.pop(_gk(group_id, settings["id"]), None)
    profit_counted_games.discard(_gk(group_id, settings["id"]))
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

    await update.message.reply_text("âœ… áŠ á‹²áˆµ áŒ¨á‹‹á‰³ á‰°áŒ€áˆáˆ¯áˆ!")


async def handle_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 3:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /register 5 áŠ á‰ á‰   á‹ˆá‹­áˆ  /register 5 10 15+ áŠ á‰ á‰ ")
        return

    user_name = parts[-1]
    number_parts = parts[1:-1]

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
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
            await update.message.reply_text(f"âŒ {', '.join(failed)} á‰€á‹µáˆž á‰°á‹ˆáˆµá‹·áˆ!")
        return

    await _refresh_board(ctx, settings, group_id)

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)

    reg_list = ", ".join(format_number(n) + ("+" if h else "") for n, h in registered)
    msg = f"âœ… {reg_list} â†’ {user_name} á‰°áˆ˜á‹˜áŒˆá‰ !"
    if failed:
        msg += f"\nâŒ {', '.join(failed)} á‰€á‹µáˆž á‰°á‹ˆáˆµá‹·áˆ!"
    await update.message.reply_text(msg)


# ============================================================
# MULTI-GROUP COMMANDS
# ============================================================

async def handle_enable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            gname = update.effective_chat.title or str(gid)
            enable_group(gid, gname)
            await update.message.reply_text(f"âœ… Group {gname} enabled!")
            return
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /enable -100123456789")
        return

    try:
        gid = int(parts[1])
        enable_group(gid)
        await update.message.reply_text(f"âœ… Group {gid} enabled!")
    except ValueError:
        await update.message.reply_text("âŒ Group ID á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


async def handle_disable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            disable_group(gid)
            await update.message.reply_text(f"âœ… Group {gid} disabled!")
            return
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /disable -100123456789")
        return

    try:
        gid = int(parts[1])
        disable_group(gid)
        await update.message.reply_text(f"âœ… Group {gid} disabled!")
    except ValueError:
        await update.message.reply_text("âŒ Group ID á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


async def handle_enablelist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    groups = get_enabled_groups()
    if not groups:
        await update.message.reply_text("ðŸ“‹ Enabled group á‹¨áˆˆáˆá¢")
        return

    lines = ["ðŸ“‹ Enabled Groups:\n"]
    for i, g in enumerate(groups, 1):
        name = g["group_name"] or "Unknown"
        enabled_at = g["enabled_at"].strftime("%Y-%m-%d %H:%M") if g["enabled_at"] else "?"
        lines.append(f"{i}. {name}\n   ID: {g['group_id']}\n   Enabled: {enabled_at}")

    await update.message.reply_text("\n\n".join(lines))


async def handle_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /addadmin 123456789")
        return

    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("âŒ Group ID á‹«áˆµáˆáˆáŒ‹áˆ: /addadmin USER_ID GROUP_ID")
            return
        add_group_admin(gid, admin_id)
        await update.message.reply_text(f"âœ… {admin_id} group admin áˆ†áŠ—áˆ!")
    except (ValueError, IndexError):
        await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› ID áŒ»á!")


async def handle_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /removeadmin 123456789")
        return
    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("âŒ Group ID á‹«áˆµáˆáˆáŒ‹áˆ")
            return
        remove_group_admin(gid, admin_id)
        await update.message.reply_text(f"âœ… {admin_id} admin á‰°á‹ˆáŒ£!")
    except ValueError:
        await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› ID áŒ»á!")


async def handle_userlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return

    if not group_id:
        await update.message.reply_text("âŒ Group á‹áˆµáŒ¥ á‰¥á‰» á‹­áˆ°áˆ«áˆ!")
        return

    users = get_usernames(group_id)
    if not users:
        await update.message.reply_text("ðŸ“‹ Username á‹¨áˆˆáˆá¢")
        return

    lines = [f"ðŸ‘¥ Members ({len(users)} total):\n"]
    for u in users:
        badge = "ðŸ†•" if not u["is_read"] else "  "
        lines.append(f"{badge} @{u['username']}")

    await update.message.reply_text("\n".join(lines))
    mark_usernames_read(group_id)


async def handle_clearusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return
    if not group_id:
        await update.message.reply_text("âŒ Group á‹áˆµáŒ¥ á‰¥á‰» á‹­áˆ°áˆ«áˆ!")
        return
    clear_usernames(group_id)
    await update.message.reply_text("âœ… Username list áŒ¸á‹³!")


async def handle_activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    activities = get_activity()
    if not activities:
        await update.message.reply_text("ðŸ“Š Activity data á‹¨áˆˆáˆá¢")
        return

    lines = ["ðŸ“Š Group Activity:\n"]
    for a in activities:
        name = a.get("group_name") or str(a["group_id"])
        last = a["last_active"].strftime("%m/%d %H:%M") if a["last_active"] else "?"
        lines.append(
            f"ðŸ“Œ {name}\n"
            f"   ðŸ’¬ Messages: {a['messages'] or 0}\n"
            f"   ðŸ“ Registrations: {a['registrations'] or 0}\n"
            f"   ðŸ’° Payments: {a['payments'] or 0}\n"
            f"   ðŸ• Last active: {last}"
        )

    await update.message.reply_text("\n\n".join(lines))


async def handle_dbstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    statuses = get_db_status()
    lines = ["ðŸ—„ï¸ Database Status:\n"]
    for s in statuses:
        if s.get("error"):
            lines.append(f"DB{s['index']}: âŒ Error")
            continue
        active = "ðŸŸ¢ ACTIVE" if s["is_active"] else ("ðŸ”´ FULL" if s["is_full"] else "âšª Standby")
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
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /dbclear 2  (DB2 á‹«áŒ¸á‹³áˆ)")
        return

    try:
        db_num = int(parts[1])
        clear_db_data(db_num)
        await update.message.reply_text(f"âœ… DB{db_num} áŒ¸á‹³! (usernames á‹­á‰€áˆ«áˆ‰)")
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


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
            await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
            return

    winners = get_recent_winners(group_id, hours=24)

    if not winners:
        await update.message.reply_text("ðŸ† Last 24hr winners á‹¨áˆ‰áˆá¢")
        return

    medals = {1: "ðŸ¥‡", 2: "ðŸ¥ˆ", 3: "ðŸ¥‰"}
    lines = ["ðŸ† Last 24hr Winners:\n"]
    for w in winners:
        medal = medals.get(w["place"], "ðŸŽ–ï¸")
        balance = w["balance"]
        sent_mark = "âœ…" if w["sent"] else "âš ï¸ á‹«áˆá‰°áˆ‹áŠ¨"
        time_str = w["created_at"].strftime("%H:%M") if w["created_at"] else "?"
        line = f"{medal} {w['place']}áŠ›: {w['user_name']} â€” ETB {w['prize']} {sent_mark}"
        if balance > 0:
            line += f"\n   ðŸ’³ á‰€áˆª balance: ETB {balance}"
        line += f"\n   ðŸ• {time_str}"
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
    await update.message.reply_text("âœ… Bot on áˆ†áŠ—áˆ!")


async def handle_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    set_group_active(group_id, False)
    await update.message.reply_text("ðŸ”´ Bot off áˆ†áŠ—áˆ!")


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
            await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
            return

    parts = update.message.text.strip().split()

    if len(parts) == 1:
        clear_balance_all(group_id)
        await update.message.reply_text("âœ… áˆáˆ‰áˆ balance áŒ¸á‹³!")
    else:
        username = parts[1].lstrip("@")
        success = clear_balance_by_username(group_id, username)
        if success:
            await update.message.reply_text(f"âœ… @{username} balance áŒ¸á‹³!")
        else:
            await update.message.reply_text(f"âŒ @{username} áŠ áˆá‰°áŒˆáŠ˜áˆ!")


async def handle_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
        return

    report = get_report(group_id)
    lines = ["ðŸ“Š Report (Last 24hr)\n"]

    if report["games_count"] > 0:
        lines.append(
            f"ðŸŽ® áŒ¨á‹‹á‰³á‹Žá‰½: {report['games_count']}\n"
            f"ðŸ’° Total bet: ETB {report['total_bet']:,.0f}\n"
            f"ðŸ† Prize total: ETB {report['prize_total']:,.0f}\n"
            f"ðŸ“ˆ Profit: ETB {report['profit']:,.0f}"
        )
    else:
        lines.append("ðŸŽ® á‹›áˆ¬ áŒ¨á‹‹á‰³ áŠ áˆá‰°áŒ«á‹ˆá‰°áˆ")

    active = report.get("active")
    if active:
        lines.append("\nâš¡ Active Game (Real-time)")
        lines.append(f"ðŸ“ Registered: {active['total_slots']}")
        if active["counted"]:
            lines.append(
                f"ðŸ’° Total bet: ETB {active['total_bet']:,.0f}\n"
                f"ðŸ† Prize: ETB {active['prize_total']:,.0f}\n"
                f"ðŸ“ˆ Profit: ETB {active['profit']:,.0f}"
            )
        else:
            lines.append(f"âš ï¸ 15+ áˆ²áˆ†áŠ• profit á‹­á‰³á‹«áˆ ({active['total_slots']}/15)")

    await update.message.reply_text("\n".join(lines))

    try:
        cleanup_old_reports()
    except Exception:
        pass


async def handle_setwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Main admin á‰¥á‰» áŠá‹!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "âŒ áˆáˆ³áˆŒ: /setwarnmedia 2\n"
            "áŠ¨á‹› photo/video/sticker á‹­áˆ‹áŠ©\n"
            "Available: 0.5, 1, 2, 3, 5, 10 á‹°á‰‚á‰ƒ"
        )
        return

    try:
        mins = float(parts[1])
        if mins < 0.5 or mins > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("âŒ 0.5 áŠ¥áˆµáŠ¨ 10 á‰¥á‰»!")
        return

    ctx.user_data["setwarn_minutes"] = mins
    await update.message.reply_text(
        f"âœ… {mins} á‹°á‰‚á‰ƒ á‰°á‹˜áŒ‹áŒ…á‰·áˆ!\n"
        f"áŠ áˆáŠ• photo/video/sticker/gif á‹­áˆ‹áŠ©"
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
    await msg.reply_text(f"âœ… {mins} á‹°á‰‚á‰ƒ warning media á‰°á‰€áˆáŒ§áˆ! ({media_type})")


async def handle_listwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    medias = get_all_warning_media()
    if not medias:
        await update.message.reply_text("ðŸ“‹ Warning media á‹¨áˆˆáˆá¢")
        return

    lines = ["ðŸ“‹ Warning Media:\n"]
    for m in medias:
        lines.append(f"â±ï¸ {m['minutes']} á‹°á‰‚á‰ƒ â€” {m['media_type']}")

    await update.message.reply_text("\n".join(lines))


async def handle_deletewarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("âŒ áˆáˆ³áˆŒ: /deletewarnmedia 2")
        return

    try:
        mins = float(parts[1])
        delete_warning_media(mins)
        await update.message.reply_text(f"âœ… {mins} á‹°á‰‚á‰ƒ warning media áŒ á‹!")
    except ValueError:
        await update.message.reply_text("âŒ á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")


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
            # âœ… used áŽá‰¶ áŠ¨áˆ†áŠ (á‰€á‹µáˆž real winner áŠ áˆáŒ¥á‰¶ á‹¨áŠá‰ áˆ¨) AI áŒ¨áˆ­áˆ¶ áŠ áŠ•áŒ áˆ«áˆ
            if photo_uid in handled_winner_photos or is_winner_photo_used(photo_uid):
                return

            winner_found = await handle_winner_photo(ctx.bot, update.message, settings, group_id=group_id)
            if winner_found:
                # âœ… winner áˆ²áŒˆáŠ á‰¥á‰» áŠá‹ "used" á‹¨áˆšá‹°áˆ¨áŒˆá‹ â€” not-lottery/failed áŽá‰¶
                # á‹µáŒ‹áˆš áˆ˜áˆ‹áŠ­ á‰¢á‰»áˆ (retry) áŠ¥áŠ•á‹²áŠ–áˆ­ used áŠ á‹­á‹°áˆ¨áŒáˆ
                handled_winner_photos.add(photo_uid)
                save_winner_photo(photo_uid, group_id=group_id)
                # announcement á‹ˆá‹²á‹«á‹áŠ‘ á‰°áˆ‹áŠ¨ â€” board 30 seconds á‰†á‹­á‰¶ á‹­áˆáŒ£
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
                # FIX: áˆ˜áŒ€áˆ˜áˆªá‹« áŠ¥áŠ•á‹°á‰°áŒ»áˆá‹ á‹ˆá‹²á‹«á‹áŠ‘ á‹­áˆ˜á‹˜áŒˆá‰£áˆá£ áŒ¥á‹«á‰„á‹ áŠ¨á‹šá‹« á‰ áŠ‹áˆ‹ á‰¥á‰»
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)
                if ambiguous == "all_half":
                    await q_msg.reply_text("áˆáˆ‰áŠ•áˆ á‰ áŒáˆ›áˆ½ áŠá‹? (áŠ á‹Ž/áŠ á‹­á‹°áˆˆáˆ)")
                elif ambiguous == "last_half":
                    await q_msg.reply_text(f"{format_number(ambiguous_number)} á‰¥á‰» á‰ áŒáˆ›áˆ½ áŠá‹? (áŠ á‹Ž/áŠ á‹­á‹°áˆˆáˆ)")
            else:
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _check_all_paid_and_resend(ctx.bot, fresh, group_id)


# ============================================================
# DAILY PROFIT: áŒ¨á‹‹á‰³á‹ áŠ«áˆˆá‰€ (áˆáˆ‰áˆ âœ… áˆ†áŠá‹) á‰ áŠ‹áˆ‹ admin á‰  /setgame áˆ‹á‹­
# áŠ«áˆµáŒˆá‰£á‹ profit_per_game (á‰‹áˆš á‰áŒ¥áˆ­) á‹áŒª áˆáŠ•áˆ áˆµáˆŒá‰µ áŠ á‹­á‹°áˆ¨áŒáˆá¢ 1 áŒ¨á‹‹á‰³ = 1 áŒŠá‹œ
# profit_per_game á‹­á‹°áˆ˜áˆ«áˆá¢ á‰µáˆªáŒˆáˆ­ áˆáˆˆá‰µ á‰¦á‰³ áŠá‹ (á‹¨á‰µáŠ›á‹áˆ áˆ˜áŒ€áˆ˜áˆªá‹« á‰¢á‹°áˆ­áˆµ)á¦
#   1) áˆáˆ‰áˆ âœ… áˆ†áŠá‹ live/pre-booking áˆ²áŒ€áˆáˆ­ (handle_video_chat_started)
#   2) Live áŠ«áˆá‰°áŒ á‰€áˆ™á£ áˆáˆ‰áˆ âœ… áˆ†áŠá‹ á‹áŒ¤á‰µ (winner photo) áˆ²áˆ‹áŠ­ (_auto_newgame)
# profit_counted_games (in-memory set) á‰°áˆ˜áˆ³áˆ³á‹­ game_id á‹µáŒ‹áˆš áŠ¥áŠ•á‹³á‹­á‰†áŒ áˆ­ á‹­áŒ á‰¥á‰ƒáˆá¢
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

    # pre-booking mode â€” registrations á‰€á‹µáˆž áŠ áˆ‰á£ board á‰¥á‰» á‹­áˆ‹áŠ­
    if _group_id in prebooking_groups:
        prebooking_groups.discard(_group_id)
        clear_prize_balance(_group_id)

        # balance áŠ«áˆˆá‹ pre-booked registrations âœ… á‹«á‹°áˆ­áŒ‹á‰¸á‹‹áˆ
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
    profit_counted_games.discard(_gk(_group_id, game_id))
    board_text = build_board(settings, {}, {})
    new_msg = await bot.send_message(chat_id=_group_id, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    update_remaining_message_id(game_id, None)


# ============================================================
# /send CONVERSATION
# ============================================================

async def send_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("âŒ Private chat á‰¥á‰» áŠá‹!")
        return ConversationHandler.END

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
        return ConversationHandler.END

    ctx.user_data["send_group_id"] = group_id
    return await _send_show_places(update, ctx, group_id)


async def _send_show_places(update, ctx, group_id: int):
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("âŒ Active game á‹¨áˆˆáˆ!")
        return ConversationHandler.END

    ctx.user_data["send_settings"] = settings

    prize_1st = settings.get("prize_1st", 0)
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")

    lines = ["ðŸ’¸ áˆˆáˆ›áŠ• á‰¥áˆ­ á‰µáˆáŠ«áˆˆáˆ…?"]
    lines.append(f"1 â€” 1áŠ› winner (prize: {prize_1st} á‰¥áˆ­)")
    if prize_2nd:
        lines.append(f"2 â€” 2áŠ› winner (prize: {prize_2nd} á‰¥áˆ­)")
    if prize_3rd:
        lines.append(f"3 â€” 3áŠ› winner (prize: {prize_3rd} á‰¥áˆ­)")
    lines.append("\n(1, 2, á‹ˆá‹­áˆ 3 áŒ»á)")

    await update.message.reply_text("\n".join(lines))
    return ASK_SEND_PLACE


async def send_ask_place(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text not in ("1", "2", "3"):
        await update.message.reply_text("âŒ 1, 2, á‹ˆá‹­áˆ 3 á‰¥á‰» áŒ»á!")
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
        await update.message.reply_text(f"âŒ {place}áŠ› winner áŠ áˆá‰°áˆ˜á‹˜áŒˆá‰ áˆ!")
        return ConversationHandler.END

    ctx.user_data["send_place"] = place
    ctx.user_data["send_game_id"] = settings["id"]

    if len(winners) == 1:
        winner = winners[0]
        ctx.user_data["send_telegram_id"] = winner["telegram_id"]
        ctx.user_data["send_user_name"] = winner["user_name"]

        balance = winner.get("balance", 0)
        await update.message.reply_text(
            f"ðŸ‘¤ {place}áŠ›: {winner['user_name']}\n"
            f"ðŸ’³ áŠ áˆáŠ• balance: ETB {balance}\n\n"
            f"ðŸ’¸ áˆµáŠ•á‰µ á‰¥áˆ­ áˆ‹áŠ«áˆ…? (á‰áŒ¥áˆ­ áŒ»á)"
        )
        return ASK_SEND_AMOUNT

    ctx.user_data["send_winners_list"] = winners
    lines = [f"âš ï¸ {place}áŠ› á‰¦á‰³ áˆ‹á‹­ {len(winners)} áˆ°á‹ áŠ áˆˆ (tie)á¦\n"]
    for i, w in enumerate(winners, 1):
        bal = w.get("balance", 0)
        lines.append(f"{i}. {w['user_name']} (balance: ETB {bal})")
    lines.append("\náˆ›áŠ•áŠ• á‰µáˆáŠ«áˆˆáˆ…? á‰áŒ¥áˆ­ áŒ»á (1, 2, ...)")
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
        await update.message.reply_text(f"âŒ 1 áŠ¥áˆµáŠ¨ {len(winners)} á‰áŒ¥áˆ­ á‰¥á‰» áŒ»á!")
        return ASK_SEND_WINNER

    winner = winners[idx - 1]
    place = ctx.user_data.get("send_place")
    ctx.user_data["send_telegram_id"] = winner["telegram_id"]
    ctx.user_data["send_user_name"] = winner["user_name"]

    balance = winner.get("balance", 0)
    await update.message.reply_text(
        f"ðŸ‘¤ {place}áŠ›: {winner['user_name']}\n"
        f"ðŸ’³ áŠ áˆáŠ• balance: ETB {balance}\n\n"
        f"ðŸ’¸ áˆµáŠ•á‰µ á‰¥áˆ­ áˆ‹áŠ«áˆ…? (á‰áŒ¥áˆ­ áŒ»á)"
    )
    return ASK_SEND_AMOUNT


async def send_ask_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("âŒ á‰µáŠ­áŠ­áˆˆáŠ› á‰áŒ¥áˆ­ áŒ»á!")
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

    place_label = {1: "1áŠ›", 2: "2áŠ›", 3: "3áŠ›"}.get(place, f"{place}áŠ›")

    lines = [
        f"âœ… {place_label} winner: {user_name}",
        f"ðŸ’¸ á‹¨áˆ‹áŠ«áˆ…: ETB {amount}",
        f"ðŸ’³ á‰€áˆª balance: ETB {new_balance}",
    ]
    await update.message.reply_text("\n".join(lines))

    if group_id:
        try:
            announcement = (
                f"ðŸ’¸ {place_label} winner á‰¥áˆ­ á‰°áˆ‹áŠ¨!\n"
                f"ðŸ‘¤ {user_name}\n"
                f"ðŸ’° ETB {amount}"
            )
            await ctx.bot.send_message(chat_id=group_id, text=announcement)
        except Exception:
            pass

    settings = ctx.user_data.get("send_settings")
    if settings:
        await _refresh_board(ctx, settings, group_id)

    return ConversationHandler.END


async def cancel_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("âŒ /send á‰°áˆ°áˆ­á‹Ÿáˆá¢")
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
            await update.message.reply_text("âŒ Admin á‹¨áˆ†áŠ•áŠ­á‰ á‰µ group á‹¨áˆˆáˆ!")
            return

    is_main = is_main_admin(user_id)

    text = (
        "ðŸ¤– Commands:\n\n"
        "ðŸŽ® *Game*\n"
        "/setgame â€” áŠ á‹²áˆµ game settings á‹«á‰€áŠ“á‰¥áˆ«áˆ\n"
        "/newgame â€” á‰áŒ¥áˆ®á‰½áŠ• áŒ áˆ­áŒŽ áŠ á‹²áˆµ áŒ¨á‹‹á‰³ á‹­áŒ€áˆáˆ«áˆ\n"
        "/setcountdown 2 â€” countdown á‹°á‰‚á‰ƒ á‹­á‰€á‹­áˆ«áˆ (0=áŠ áŒ¥á‹)\n"
        "/showslots on/off â€” sub-slots áˆ‹á‹­ áˆµáˆ á‹«áˆ³á‹«áˆ/á‹«áŒ á‹áˆ\n"
        "/nekay 5 10+ 15 â€” manually áŠá‰ƒá‹­ á‹«á‹°áˆ­áŒ‹áˆ\n"
        "/status â€” áˆáˆ‰áŠ•áˆ commands á‹«áˆ³á‹«áˆ\n\n"
        "ðŸ‘¤ *áˆá‹áŒˆá‰£*\n"
        "/register 5 10+ áŠ á‰ á‰  â€” á‰áŒ¥áˆ­ manually á‹­áˆ˜á‹˜áŒá‰£áˆ\n"
        "  â€¢ + = áŒáˆ›áˆ½ (áˆˆáˆáˆ³áˆŒ 5+)\n\n"
        "ðŸ’° *áŠ­áá‹«*\n"
        "/paid 5 10 15 â€” á‰¥á‹™ á‰áŒ¥áˆ®á‰½ paid á‹«á‹°áˆ­áŒ‹áˆ\n"
        "/paid 5:2 â€” slot 2 paid á‹«á‹°áˆ­áŒ‹áˆ\n"
        "/unpaid 5 10 â€” á‰¥á‹™ á‰áŒ¥áˆ®á‰½ unpaid á‹«á‹°áˆ­áŒ‹áˆ\n\n"
        "ðŸ—‘ï¸ *áŠ áˆµá‰°á‹³á‹°áˆ­*\n"
        "/remove 5 â€” á‰áŒ¥áˆ­ áŠ¨ board á‹«áˆµá‹ˆáŒ£áˆ\n"
        "/remove 5:1 â€” slot 1 á‰¥á‰» á‹«áˆµá‹ˆáŒ£áˆ\n"
        "/on â€” Bot á‹«áˆµáŠáˆ³áˆ\n"
        "/off â€” Bot á‹«á‰†áˆ›áˆ\n"
        "/clearbalance â€” áˆáˆ‰áˆ balance á‹«áŒ¸á‹³áˆ\n"
        "/clearbalance @username â€” áŠ áŠ•á‹µ user balance á‹«áŒ¸á‹³áˆ\n\n"
        "ðŸ‘¥ *Members*\n"
        "/userlist â€” username á‹áˆ­á‹áˆ­\n"
        "/clearusers â€” username list á‹«áŒ¸á‹³áˆ\n\n"
        "ðŸ“Š *Report*\n"
        "/report â€” real-time profit + games (last 24hr)\n\n"
        "ðŸ† *Winner*\n"
        "/winners â€” last 24hr winners\n"
        "/send â€” winner á‰¥áˆ­ á‹­áˆ‹áŠ«áˆ (private chat á‰¥á‰»)\n\n"
        "ðŸ’¸ *Winner Auto-Sender (userbot2)*\n"
        "/setwinnerapi api_id api_hash â€” winner API á‹«áˆµá‰€áˆáŒ£áˆ (main admin)\n"
        "/startsession2 +phone â€” winner session á‹­áŒ€áˆáˆ«áˆ (private chat)\n"
        "/verifycode2 +phone code â€” session á‹«áˆ¨áŒ‹áŒáŒ£áˆ\n"
        "/verify2fa2 +phone password â€” 2FA áŠ«áˆˆ\n"
        "/listsessions2 â€” group á‹­áˆ… sessions á‹áˆ­á‹áˆ­\n"
        "/removesession2 +phone â€” session á‹«áˆµá‹ˆáŒá‹³áˆ\n\n"
        "âœï¸ *Manual Board Edit*\n"
        "Board copy áŠ áˆ­áŒŽ edit áŠ áˆ­áŒŽ bot message áˆ‹á‹­ reply áŠ áˆ­áŒ\n"
        "Bot automatically á‹­á‰€á‹­áˆ¨á‹‹áˆ!\n"
    )

    if is_main:
        text += (
            "\nðŸ”§ *Main Admin*\n"
            "/enable â€” group á‹«áˆµáŠáˆ³áˆ\n"
            "/disable â€” group á‹«áŒ á‹áˆ\n"
            "/enablelist â€” enabled groups á‹áˆ­á‹áˆ­\n"
            "/addadmin USER_ID â€” group admin á‹­áŒ¨áˆáˆ«áˆ\n"
            "/removeadmin USER_ID â€” group admin á‹«áˆµá‹ˆáŒ£áˆ\n"
            "/activity â€” group activity á‹«áˆ³á‹«áˆ\n"
            "/dbstatus â€” DB status á‹«áˆ³á‹«áˆ\n"
            "/dbclear N â€” DBN á‹«áŒ¸á‹³áˆ (username áˆ³á‹­áŠáŠ«)\n"
            "/setwarnmedia 2 â€” warning media á‹«áˆµá‰€áˆáŒ£áˆ\n"
            "/listwarnmedia â€” warning media á‹áˆ­á‹áˆ­\n"
            "/deletewarnmedia 2 â€” warning media á‹«áŒ¸á‹³áˆ\n"
            "/setcompletesticker â€” áˆáˆ‰áˆ âœ… áˆ²áˆ†áŠ• sticker á‹«áˆµá‰€áˆáŒ£áˆ\n"
            "/listcompletestickers â€” complete stickers á‹áˆ­á‹áˆ­\n"
            "/removecompletesticker N â€” sticker #N á‹«áˆµá‹ˆáŒ£áˆ\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

async def handle_admin_group_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group áˆ‹á‹­ 30+ seconds video áˆ²áˆáŠ­ â†’ á‰€á‹°áˆ á‹«áˆˆá‹áŠ• board á‹­áˆ°áˆ­á‹›áˆá£
    áŠ á‹²áˆ±áŠ• board áŠ¨á‰³á‰½ á‹­áˆ‹áŠ«áˆ (áŠ áŠ•á‹µ áŒŠá‹œ á‰¥á‰» per game)
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

    # duration check â€” 30 seconds+
    duration = getattr(video, "duration", None)
    if not duration or duration < 30:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    game_id = settings["id"]

    # áŠ áŠ•á‹µ áŒŠá‹œ á‰¥á‰» per game
    if _gk(group_id, game_id) in handled_video_boards:
        return
    handled_video_boards.add(_gk(group_id, game_id))

    # á‰€á‹°áˆ á‹«áˆˆá‹áŠ• board á‹­áˆ°áˆ­á‹
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
        except Exception:
            pass

    # áŠ á‹²áˆ±áŠ• board áŠ¨á‰³á‰½ á‹­áˆ‹áŠ­
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    logging.info(f"[VideoBoard] Group {group_id} game {game_id} board replaced after 30s+ video")


async def handle_video_chat_started(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin live áˆ²áŒ€áˆáˆ­ + áˆáˆ‰áˆ á‰áŒ¥áˆ®á‰½ âœ… áŠ¨áˆ†áŠ‘ â†’ silent pre-booking mode á‹­áŒ€áˆáˆ­á¢
    Board áŠ á‹­áˆ‹áŠ­áˆá£ áˆ°á‹Žá‰½ á‰áŒ¥áˆ­ áˆ˜á‹«á‹ á‹­á‰½áˆ‹áˆ‰á£ /newgame áˆ²áˆ board á‹­á‰³á‹«áˆá¢
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

    # FIX: daily profit â€” áˆáˆ‰áˆ âœ… áˆ†áŠá‹ live áˆ²áŒ€áˆáˆ­ 1 áŒ¨á‹‹á‰³ á‰°á‰¥áˆŽ profit_per_game
    # á‹­áˆ˜á‹˜áŒˆá‰£áˆ (registrations áŠ¨áˆ˜áŒ¥á‹á‰³á‰¸á‹ á‰ áŠá‰µ)
    _maybe_record_game_profit(group_id, game_id, settings)

    # âœ… FIX: registrations áŠ¨áˆ˜áŒ¥á‹á‰± á‰ áŠá‰µ snapshot á‹«á‹µáˆ­áŒ â€” winner photo
    # áŒˆáŠ“ á‹áŒ¤á‰± áŠ«áˆá‰³á‹ˆá‰€ (áŒˆáŠ“ admin áŠ«áˆáˆ‹áŠ¨á‹) á‰ áŠá‰µ pre-booking á‰¢áŒ€áˆáˆ­á£ winner
    # lookup snapshot áˆ‹á‹­ á‰°áˆ˜áˆáŠ­á‰¶ á‰µáŠ­áŠ­áˆˆáŠ›á‹áŠ• á‰£áˆˆá‰¤á‰µ áˆ›áŒáŠ˜á‰µ á‹­á‰½áˆ‹áˆ
    save_registrations_snapshot(game_id)

    # silently clear registrations only (game_settings row á‹­á‰€áˆ«áˆ)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations WHERE game_id=%s", (game_id,))
    cur.execute("DELETE FROM sms_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    cur.execute("DELETE FROM screenshot_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

    # âœ… á‹«áˆˆá‰€á‹ áŒ¨á‹‹á‰³ carry_balance áŠ¥á‹šáˆ… áŒ‹áˆ­ á‹­áŒ¸á‹³áˆ (áŠ¥á‹áŠá‰°áŠ›á‹ áŒ¨á‹‹á‰³ á‹«áˆˆá‰€á‰ á‰µ á‰¦á‰³) â€”
    # pre-booking round áˆ«áˆ± áŒˆáŠ“ áˆµáˆ‹áˆáŒ€áˆ˜áˆ¨á£ áŠ¨á‹šáˆ… á‰ áŠ‹áˆ‹ á‹¨áˆšáŒˆá‰£ áŒˆáŠ•á‹˜á‰¥ áˆáˆ‰ áˆˆáŠ á‹²áˆ± á‹™áˆ­
    # áŠ•ááˆ… (áŠ«áˆˆáˆá‹ áŒ¨á‹‹á‰³ á‰€áˆª áˆ³á‹­á‰€áˆ‹á‰€áˆ) á‹­áˆ†áŠ“áˆ
    clear_carry_balance(group_id)

    # in-memory state reset
    nekay_active.discard(_gk(group_id, game_id))
    admin_nekay_games.discard(_gk(group_id, game_id))
    active_countdowns.pop(_gk(group_id, game_id), None)
    nekay_numbers.pop(_gk(group_id, game_id), None)
    countdown_done.discard(_gk(group_id, game_id))
    _stop_inactivity_tracker(game_id, group_id)

    # pre-booking mode á‹­áŒ€áˆáˆ­
    prebooking_groups.add(group_id)
    logging.info(f"[PreBooking] Group {group_id} entered pre-booking mode (live started, all paid)")

    # pre-booking media á‹­áˆ‹áŠ« (sticker/photo/video announcement)
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

        # bot off áˆ²áˆ†áŠ• SMS áˆáŠ•áˆ áŠ á‹«áˆµáŠ¬á‹µ
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
    return web.Response(text=f"ðŸ¤– Bot is running!\nðŸ• Server time: {now}")


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
    print("ðŸŒ SMS Server started on port 8080")
    print("ðŸ“± SMS endpoint: /sms/{group_id}")


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
    # NEW: winner "ðŸ”¥ reaction" balance-clear feature
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

    # âœ… FIX: á‹¨áˆ«áˆ± group (-2) áˆ‹á‹­ áˆ˜áˆ˜á‹áŒˆá‰¥ áŠ áˆˆá‰ á‰µ! python-telegram-bot á‰ áŠ áŠ•á‹µ
    # group á‹áˆµáŒ¥ á‹¨áˆ˜áŒ€áˆ˜áˆªá‹«á‹áŠ• filter-matching handler á‰¥á‰» á‹­áŒ áˆ«áˆ â€” á‹­áˆ…
    # áŠ¨ handle_winner_correction_reply áŒ‹áˆ­ á‰°áˆ˜áˆ³áˆ³á‹­ group (-1) áŠ¥áŠ“ á‰°áˆ˜áˆ³áˆ³á‹­
    # filter áˆµáˆˆáŠá‰ áˆ¨á‹á£ áˆáŒ½áˆž áŠ á‹­áŒ áˆ«áˆ áŠá‰ áˆ­ (dead code)á¢
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_owner_reply
    ), group=-2)

    # NEW: "ðŸ”¥16 21+" â†’ áŠá‰ƒá‹­ á‹áˆ­á‹áˆ­ áˆ›á‹áŒ« (á‹¨áˆ«áˆ± group á‹«áˆµáˆáˆáŒˆá‹‹áˆ â€” áŠ¨áˆ‹á‹­ á‹«áˆ‰á‰µ
    # handlers áˆáˆ‰áŠ•áˆ text áˆµáˆˆáˆšá‹­á‹™)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & filters.Regex(r'^\s*ðŸ”¥'),
        handle_unnekay_text
    ), group=-3)

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
                    lines = ["ðŸ“Š á‹¨á‹›áˆ¬ Daily Report\n"]
                    if report["games_count"] > 0:
                        lines.append(
                            f"ðŸŽ® áŒ¨á‹‹á‰³á‹Žá‰½: {report['games_count']}\n"
                            f"ðŸ’° Total bet: ETB {report['total_bet']:,.0f}\n"
                            f"ðŸ† Prize: ETB {report['prize_total']:,.0f}\n"
                            f"ðŸ“ˆ Profit: ETB {report['profit']:,.0f}"
                        )
                    else:
                        lines.append("ðŸŽ® á‹›áˆ¬ áŒ¨á‹‹á‰³ áŠ áˆá‰°áŒ«á‹ˆá‰°áˆ")
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
                # NEW: winner-ðŸ”¥-reaction feature â€” message_senders áˆ‹á‹­ á‹°áŒáˆž
                # á‹°áˆ…áŠ•áŠá‰µ (safety-net) periodic cleanup (clear_game áˆ«áˆ± áŠ á‹²áˆµ
                # game áˆ²áŒ€áˆ˜áˆ­ á‹« group's records á‰¢á‹«áŒ¸á‹³áˆá£ á‹­áˆ„ á‰°áŒ¨áˆ›áˆª áŒ¥áŠ•á‰ƒá‰„ áŠá‹)
                try:
                    cleanup_old_message_senders()
                except Exception:
                    pass
            except Exception as e:
                logging.warning(f"[Daily Report] Error: {e}")

    loop.create_task(_daily_report_scheduler())

    print("ðŸ¤– Bot started!")
    # NEW: allowed_updates áŒáˆáŒ½ á‰°á‰¥áˆŽ áŠ«áˆá‰°áˆ°áŒ  Telegram á‹¨á‹µáˆ®á‹áŠ• cached setting
    # á‰¥á‰» á‹­áŒ á‰€áˆ›áˆ (message_reaction áˆ‹á‹­áŠ«á‰°á‰µ á‹­á‰½áˆ‹áˆ) â€” áˆµáˆˆá‹šáˆ… winner-ðŸ”¥-reaction
    # feature áŠ¥áŠ•á‹²áˆ°áˆ« Update.ALL_TYPES áŒáˆáŒ½ á‰°á‰¥áˆŽ á‰°áˆ°áŒ¥á‰·áˆá¢
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
