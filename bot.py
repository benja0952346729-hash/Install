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

# \u1328\u12cb\u1273 \u12ab\u1208\u1240 \u1260\u128b\u120b (\u1201\u1209\u121d \u2705 \u1206\u1290\u12cd live/pre-booking \u1232\u1300\u121d\u122d \u12c8\u12ed\u121d \u12cd\u1324\u1275 \u1232\u120b\u12ad) daily
# profit \u12f5\u130b\u121a \u12a5\u1295\u12f3\u12ed\u1246\u1320\u122d \u12e8\u121a\u12a8\u1273\u1270\u120d set \u2014 game_id-based guard
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

# FIX: winner photo \u12a8\u1270\u120b\u12a8 \u12a5\u1235\u12a8 _auto_newgame \u12f5\u1228\u1235 \u12eb\u1208\u12cd 30 \u1230\u12a8\u1295\u12f5 \u12ad\u134d\u1270\u1275 \u2014
# board/\u1240\u1323\u12ed \u12d9\u122d \u1308\u1293 \u1235\u120b\u120d\u1270\u1320\u1293\u1240\u1240\u1363 \u1260\u12da\u1205 \u130a\u12dc \u12cd\u1235\u1325 registration \u1262\u1233\u12ab \u120d\u12ad \u12a5\u1295\u12f0
# prebooking_groups reaction-only (\U0001f44d) \u1265\u127b \u12ed\u1206\u1295 (text reply \u12a0\u12ed\u120b\u12ad\u121d)
winner_pending_groups = set()
handled_video_boards = set()  # game_ids where 30s+ video board replace already done

# ============================================================
# FIX: cross-group data leak \u2014 \u1266\u1271 4 \u12e8\u1270\u1208\u12eb\u12e9 databases \u1235\u120b\u1209\u1275
# (DATABASE_URLS rotation)\u1363 \u12a5\u12eb\u1295\u12f3\u1295\u12f1 DB \u12e8\u122b\u1231 \u12e8\u1270\u1208\u12e8 game_settings.id
# (SERIAL) \u12a0\u1246\u1323\u1320\u122d \u12a0\u1208\u12cd\u1362 \u1235\u1208\u12da\u1205 \u1201\u1208\u1275 \u12e8\u1270\u1208\u12eb\u12e9 groups \u1260\u12a0\u130b\u1323\u121a \u1270\u1218\u1233\u1233\u12ed game_id
# \u1241\u1325\u122d \u120a\u1296\u122b\u1278\u12cd \u12ed\u127d\u120b\u120d (\u1208\u121d\u1233\u120c Group A game_id=12 \u1260 DB#1\u1363 Group B
# game_id=12 \u1260 DB#2)\u1362 \u12a8\u120b\u12ed \u12eb\u1209\u1275 global trackers (nekay_numbers,
# nekay_active, \u12c8\u12d8\u1270) \u1260 game_id \u1265\u127b \u1235\u1208\u121a\u1240\u1218\u1321 \u1290\u1260\u122d\u1363 \u12ed\u1205 \u121b\u1208\u1275 Group A's
# /nekay \u12cd\u1202\u1265 \u1260 Group B's board \u120b\u12ed \u12ed\u1273\u12ed \u1290\u1260\u122d (\u12c8\u12ed\u121d \u1260\u1270\u1243\u122b\u1292\u12cd)\u1362
# FIX: \u1201\u1209\u121d \u12a5\u1290\u12da\u1205 trackers \u1260 (group_id, game_id) combo \u1241\u120d\u134d \u1265\u127b
# \u12a5\u1295\u12f2\u1240\u1218\u1321 \u1270\u1240\u12ed\u1228\u12cb\u120d \u2014 _gk() helper \u12ed\u1205\u1295 combo \u1241\u120d\u134d \u12ed\u1308\u1290\u1263\u120d\u1362
# ============================================================

def _gk(group_id, game_id):
    """Group-scoped key \u1208 in-memory trackers (cross-group game_id collision \u12a5\u1295\u12f3\u12ed\u1348\u1320\u122d)"""
    return (group_id, game_id)

URGENCY_MESSAGES = [
    "\u1264\u1270\u1230\u1265 \u1308\u1263 \u1308\u1263 \u1260\u1209\U0001f64f",
    "\u1264\u1270\u1230\u1265 \u132b\u12c8\u1273\u12cd\u1295 \u12a0\u1293\u12f5\u121d\u1245 \U0001f64f",
    "\u1264\u1270\u1230\u1265 \u1240\u122a \u1241\u1325\u122e\u127d \u1265\u127b \u12a0\u1209 \u1308\u1263 \u1308\u1263 \u1260\u1209 \U0001f64f",
]

NEKAY_COUNTDOWN_MESSAGE = "\u1264\u1270\u1230\u1265 \u1275\u1295\u123d \u12ed\u1320\u1265\u1241 \u1290\u1243\u12ed \u120b\u12c8\u1323 \u1290\u12cd \U0001f64f"


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
# NEW \u2014 DEBOUNCED REMAINING/NEKAY RESEND (payment confirm \u2192 5-second
# debounce \u2192 resend \u1240\u122a/\u1290\u1243\u12ed list \u12a8\u1273\u127d, no duplicates ever)
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
    Payment (photo/SMS) confirm \u2192 "\u1218\u120d\u12ab\u121d \u12d5\u12f5\u120d" \u12ab\u1208 \u1260\u128b\u120b 5 \u1230\u12a8\u1295\u12f5 \u121d\u1295\u121d \u1270\u1328\u121b\u122a
    \u12ad\u134d\u12eb/\u12a5\u1295\u1245\u1235\u1243\u1234 \u12a8\u120c\u1208 \u1240\u122a (\u12c8\u12ed\u121d \u1290\u1243\u12ed mode \u1308\u1263\u122a \u12a8\u1206\u1290 \u1290\u1243\u12ed) \u12dd\u122d\u12dd\u122d \u12a8\u1273\u127d resend
    \u12ed\u1201\u1295 \u2014 \u1290\u1263\u1229\u1295 \u12a0\u1325\u134d\u1276 \u12a0\u12f2\u1235 \u1265\u127b (duplicate \u1260\u134d\u1339\u121d \u12a5\u1295\u12f3\u12ed\u1348\u1320\u122d)\u1362 5 \u1230\u12a8\u1295\u12f5 \u12cd\u1235\u1325
    \u120c\u120b \u12ad\u134d\u12eb \u1262\u1218\u1323 (_schedule_remaining_resend \u1270\u1320\u122d\u1276) \u12ed\u1205 task \u12ed\u1230\u1228\u12db\u120d
    (cancel) \u12a0\u12f2\u1235 5 \u1230\u12a8\u1295\u12f5 \u12ed\u1300\u121d\u122b\u120d\u1362
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
        # NEW: \u1290\u1243\u12ed mode \u1263\u12ed\u1206\u1295\u121d \u12a5\u1295\u12b3 (\u1270\u122b \u1328\u12cb\u1273)\u1363 \u12ad\u134d\u12eb \u12a8\u1270\u1228\u130b\u1308\u1320 \u1260\u128b\u120b \u1240\u122a \u12dd\u122d\u12dd\u122d
        # 5 \u1230\u12a8\u1295\u12f5 debounce \u1246\u12ed\u1276 resend \u12ed\u1201\u1295 (\u12a8\u12da\u1205 \u1260\u134a\u1275 \u121d\u1295\u121d \u12a0\u120d\u1290\u1260\u1228\u121d \u2014 \u12ed\u1204
        # \u12ad\u134d\u1270\u1275 \u1290\u1260\u122d)
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

    # NEW: \u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u12c8\u12f2\u12eb\u12cd\u1291 \u1233\u12ed\u1206\u1295 5 \u1230\u12a8\u1295\u12f5 debounce \u1246\u12ed\u1276 resend \u12ed\u1201\u1295 (\u120c\u120b
    # \u12ad\u134d\u12eb/\u12a5\u1295\u1245\u1235\u1243\u1234 \u1260\u12da\u12eb 5 \u1230\u12a8\u1295\u12f5 \u12cd\u1235\u1325 \u1262\u1218\u1323 timer \u12ed\u1273\u12f0\u1233\u120d)
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
# FIX #6: fire-and-forget helpers \u2014 reply/reaction Telegram API
# call \u1295 board edit \u12a8\u1218\u1300\u1218\u1229 \u1260\u134a\u1275 \u12a5\u1295\u12f2\u1320\u1265\u1245 \u120b\u1208\u121b\u12f5\u1228\u130d (\u1240\u12f5\u121e sequential \u1235\u1208\u1290\u1260\u122d
# board edit \u12ed\u12d8\u1308\u12ed \u1290\u1260\u122d)\u1362 \u12cd\u1324\u1271\u1295 \u12a0\u1295\u1320\u1265\u1245\u121d\u1363 \u1235\u1205\u1270\u1275 \u1262\u1348\u1320\u122d log \u1265\u127b \u12a5\u1293\u12f0\u122d\u130b\u1208\u1295\u1362
# ============================================================

async def _safe_reply_text(msg, text: str):
    try:
        await msg.reply_text(text)
    except Exception as e:
        logging.warning(f"[SafeReply] Error: {e}")


async def _safe_set_reaction(bot, chat_id: int, message_id: int, emoji: str = "\U0001f44d"):
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
# FIX #4: admin confirmation messages ("\u2705 ...") \u12a8\u1270\u120b\u12a9 \u12a81.5-2 \u1230\u12a8\u1295\u12f5
# \u1260\u128b\u120b \u1260\u122b\u1233\u1278\u12cd \u12ed\u1320\u1349 (admin \u12ab\u12e8 \u1260\u1242 \u1290\u12cd)\u1362
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
# NEW \u2014 winner "\U0001f525 reaction" balance-clear feature: admin puts a native
# \U0001f525 reaction on any message previously sent BY a recent winner (in the
# group) \u2192 that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched \u2014 this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message \u2014 only who reacted and which
# chat/message_id. So we keep a small bounded in-memory cache mapping
# (chat_id, message_id) -> (telegram_id, user_name) for recent group
# text messages, populated (read-only/additive) inside
# handle_group_message. This does not alter any existing behavior.
# ============================================================
# ============================================================
# NEW \u2014 winner "\U0001f525 reaction" balance-clear feature: admin puts a native
# \U0001f525 reaction on any message previously sent BY a recent winner (in the
# group) \u2192 that winner's balance ONLY gets cleared (exactly like
# /clearbalance @username, but by telegram_id directly). Board/paid
# status is untouched \u2014 this only zeroes user_balance.
#
# Telegram's message_reaction_updated update does not include who wrote
# the original (reacted-to) message \u2014 only who reacted and which
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
# NEW \u2014 "# NUM[+SLOT][\u2705] ..." admin replacement feature: bot's
# earlier "\u1270\u12ed\u12de\u1265\u1203\u120d"/booking_taken rejection reply message_id \u1270\u1218\u12dd\u130d\u1266
# \u12ed\u1240\u1218\u1323\u120d\u1363 \u1235\u1208\u12da\u1205 admin \u1270\u1320\u1243\u121a\u12cd \u12a6\u122d\u1305\u1293\u120d message \u120b\u12ed reply \u12a0\u12f5\u122d\u130e "# ..." \u1232\u120d
# \u12eb\u1295\u1295 \u1290\u1263\u122d rejection message \u121b\u1325\u134b\u1275 \u12ed\u127b\u120b\u120d\u1362
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
        # 0 = \u1219\u1209 nekay (full)\u1363 2/-1/-2 \u1201\u1209\u121d half/slot-specific nekay \u1293\u1278\u12cd
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
    await update.message.reply_text("\U0001f916 Bot \u1270\u1230\u1293\u12f5\u1277\u120d!")


# ============================================================
# SETGAME CONVERSATION
# ============================================================

async def setgame_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        await update.message.reply_text("\u274c Admin \u1265\u127b \u1290\u12cd!")
        return ConversationHandler.END
    ctx.user_data["setup_group_id"] = group_id
    await update.message.reply_text("\U0001f3ae \u1235\u1295\u1275 \u1241\u1325\u122e\u127d \u12a0\u1209? (\u1208\u121d\u1233\u120c: 100)")
    return ASK_TOTAL


async def ask_total(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["total_numbers"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")
        return ASK_TOTAL
    await update.message.reply_text("\U0001f465 \u12081 \u1230\u12cd \u1235\u1295\u1275 \u1241\u1325\u122e\u127d? (\u1208\u121d\u1233\u120c: 5)")
    return ASK_PER_PERSON


async def ask_per_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["numbers_per_person"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")
        return ASK_PER_PERSON
    await update.message.reply_text("\U0001f4b0 \u1219\u1209 \u12cb\u130b \u1235\u1295\u1275 \u1265\u122d?")
    return ASK_PRICE_FULL


async def ask_price_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["price_full"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")
        return ASK_PRICE_FULL
    await update.message.reply_text("\U0001f4b3 \u130d\u121b\u123d \u12cb\u130b \u12a0\u1208? (\u1241\u1325\u122d \u133b\u134d \u12c8\u12ed\u121d '\u12a0\u12ed\u12f0\u1208\u121d')")
    return ASK_PRICE_HALF


async def ask_price_half(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["\u12a0\u12ed\u12f0\u1208\u121d", "aydelem", "no", "\u12e8\u1208\u121d"]:
        ctx.user_data["price_half"] = None
    else:
        try:
            ctx.user_data["price_half"] = int(text)
        except ValueError:
            await update.message.reply_text("\u274c \u1241\u1325\u122d \u12c8\u12ed\u121d '\u12a0\u12ed\u12f0\u1208\u121d' \u133b\u134d!")
            return ASK_PRICE_HALF
    await update.message.reply_text("\U0001f947 1\u129b \u123d\u120d\u121b\u1275 \u1235\u1295\u1275 \u1265\u122d?")
    return ASK_PRIZE_1


async def ask_prize_1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["prize_1st"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")
        return ASK_PRIZE_1
    await update.message.reply_text("\U0001f948 2\u129b \u123d\u120d\u121b\u1275? (\u12a8\u120c\u1208 '\u12a0\u12ed\u12f0\u1208\u121d')")
    return ASK_PRIZE_2


async def ask_prize_2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["\u12a0\u12ed\u12f0\u1208\u121d", "aydelem", "no", "\u12e8\u1208\u121d"]:
        ctx.user_data["prize_2nd"] = None
    else:
        try:
            ctx.user_data["prize_2nd"] = int(text)
        except ValueError:
            await update.message.reply_text("\u274c \u1241\u1325\u122d \u12c8\u12ed\u121d '\u12a0\u12ed\u12f0\u1208\u121d' \u133b\u134d!")
            return ASK_PRIZE_2
    await update.message.reply_text("\U0001f949 3\u129b \u123d\u120d\u121b\u1275? (\u12a8\u120c\u1208 '\u12a0\u12ed\u12f0\u1208\u121d')")
    return ASK_PRIZE_3


async def ask_prize_3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ["\u12a0\u12ed\u12f0\u1208\u121d", "aydelem", "no", "\u12e8\u1208\u121d"]:
        ctx.user_data["prize_3rd"] = None
    else:
        try:
            ctx.user_data["prize_3rd"] = int(text)
        except ValueError:
            await update.message.reply_text("\u274c \u1241\u1325\u122d \u12c8\u12ed\u121d '\u12a0\u12ed\u12f0\u1208\u121d' \u133b\u134d!")
            return ASK_PRIZE_3
    await update.message.reply_text("\U0001f4b3 Payment info \u133b\u134d (CBE, Telebirr...):")
    return ASK_PAYMENT


async def ask_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["payment_info"] = update.message.text.strip()
    await update.message.reply_text(
        "\U0001f4cc Game rule \u133b\u134d (board \u120b\u12ed \u12a8\u120b\u12ed \u12ed\u1273\u12eb\u120d)\n"
        "\u12c8\u12ed\u121d 'skip' \u12ab\u120d\u1348\u1208\u130b\u1278\u1205"
    )
    return ASK_GAME_RULE


async def ask_game_rule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "\u12a0\u12ed\u12f0\u1208\u121d", "no", "\u12e8\u1208\u121d"]:
        ctx.user_data["game_rule"] = None
    else:
        ctx.user_data["game_rule"] = text
    await update.message.reply_text(
        "\U0001f523 Slot symbol \u121d\u1228\u1325\n"
        "\u1208\u121d\u1233\u120c: # \u2b50 \U0001f3af \U0001f525 \u12c8\u12ed\u121d \u1263\u12f6 (skip)\n"
        "Default: #"
    )
    return ASK_SLOT_SYMBOL


async def ask_slot_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() in ["skip", "default", "#"]:
        ctx.user_data["slot_symbol"] = "#"
    elif text.lower() in ["\u1263\u12f6", "none", "empty", ""]:
        ctx.user_data["slot_symbol"] = ""
    else:
        ctx.user_data["slot_symbol"] = text
    await update.message.reply_text(
        "\u23f3 \u1270\u1290\u1243\u12ed countdown \u12a0\u1208?\n"
        "(\u12a0\u12ce / \u12a0\u12ed\u12f0\u1208\u121d)"
    )
    return ASK_COUNTDOWN_ENABLED


async def ask_countdown_enabled(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    yes = text in ["\u12a0\u12ce", "awo", "yes", "aha", "\u12a0\u12ce\u1295"]
    ctx.user_data["countdown_enabled"] = yes

    if yes:
        await update.message.reply_text(
            "\u23f1\ufe0f \u1235\u1295\u1275 \u12f0\u1242\u1243?\n"
            "0.5 = 30 \u1230\u12a8\u1295\u12f5\n"
            "1 = 1 \u12f0\u1242\u1243\n"
            "2 = 2 \u12f0\u1242\u1243\n"
            "5 = 5 \u12f0\u1242\u1243\n"
            "10 = 10 \u12f0\u1242\u1243\n"
            "(0.5 \u12a5\u1235\u12a8 10)"
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
        await update.message.reply_text("\u274c 0.5 \u12a5\u1235\u12a8 10 \u1265\u127b \u133b\u134d!")
        return ASK_COUNTDOWN_MINUTES
    return await ask_profit_per_game_prompt(update, ctx)


async def ask_profit_per_game_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f4c8 \u12a81 \u1328\u12cb\u1273 \u1235\u1295\u1275 \u1265\u122d profit \u12eb\u1308\u129b\u1209? (\u1208\u121d\u1233\u120c: 300)"
    )
    return ASK_PROFIT_PER_GAME


async def ask_profit_per_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["profit_per_game"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d! (\u1208\u121d\u1233\u120c: 300)")
        return ASK_PROFIT_PER_GAME
    return await _finish_setgame(update, ctx)


async def _finish_setgame(update, ctx):
    setup_group_id = ctx.user_data.get("setup_group_id")

    # NEW: /newgame \u122b\u1231 \u12a8\u12da\u1205 \u1260\u134a\u1275 game switch \u1232\u12eb\u12f0\u122d\u130d (clear_game + in-memory
    # nekay/countdown state \u121b\u133d\u12f3\u1275) \u12e8\u121a\u12eb\u12f0\u122d\u1308\u12cd\u1295 \u1270\u1218\u1233\u1233\u12ed cleanup \u2014 /setgame \u130d\u1295
    # \u12a8\u12da\u1205 \u1260\u134a\u1275 \u12ed\u1205\u1295 \u12a0\u12eb\u12f0\u122d\u130d\u121d \u1290\u1260\u122d (\u12c8\u1325\u1290\u1275 \u121b\u1323\u1275\u1363 stale winners/nekay state
    # \u12a5\u1295\u12f2\u1240\u1325\u120d \u121d\u12ad\u1295\u12eb\u1275 \u1206\u1296 \u1290\u1260\u122d)\u1362 \u12a0\u12f2\u1231\u1295 game_id \u12a8\u1218\u134d\u1320\u1229 \u1260\u134a\u1275 \u12e8\u1246\u12e8\u12cd\u1295 \u12eb\u1338\u12f3\u120d\u1362
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

    countdown_status = "\u2705 On" if ctx.user_data.get("countdown_enabled") else "\u274c Off"
    mins = ctx.user_data.get("countdown_minutes", 0)
    await update.message.reply_text(
        f"\u2705 Settings \u1270\u1240\u121d\u1327\u120d!\n"
        f"Game ID: {game_id}\n"
        f"\u23f3 Countdown: {countdown_status}"
        + (f" ({mins} \u12f0\u1242\u1243)" if ctx.user_data.get("countdown_enabled") else "")
    )
    return ConversationHandler.END


async def cancel_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\u274c Setup \u1270\u1230\u122d\u12df\u120d\u1362")
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
            await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "\u274c \u121d\u1233\u120c: /setcountdown 2\n"
            "0 = countdown \u12a0\u1325\u134b\n"
            "0.5, 1, 2, 5, 10 = \u12f0\u1242\u1243"
        )
        return

    try:
        mins = float(parts[1])
        if mins != 0 and (mins < 0.5 or mins > 10):
            raise ValueError
    except ValueError:
        await update.message.reply_text("\u274c 0 \u12c8\u12ed\u121d 0.5 \u12a5\u1235\u12a8 10 \u1265\u127b \u133b\u134d!")
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
        return

    enabled = mins > 0
    update_countdown_settings(settings["id"], enabled, mins if enabled else 0)

    if enabled:
        await update.message.reply_text(f"\u2705 Countdown {mins} \u12f0\u1242\u1243 \u1270\u1240\u121d\u1327\u120d!")
    else:
        await update.message.reply_text("\u2705 Countdown \u1320\u134d\u1277\u120d!")


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
            await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
            return

    parts = update.message.text.strip().split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await update.message.reply_text(
            "\u274c \u121d\u1233\u120c: /showslots on\n"
            "       /showslots off\n"
            "sub-slots \u120b\u12ed \u1235\u121d \u12eb\u1233\u12eb\u120d / \u12eb\u1320\u134b\u120d"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
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

    status = "\u2705 On" if enabled else "\u274c Off"
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
            "\u274c \u121d\u1233\u120c: /nekay 5 10+ 15 21\n"
            "+ = \u130d\u121b\u123d (\u1208\u121d\u1233\u120c 10+)\n"
            "5+1 = \u1241\u1325\u122d 5 slot 1 \u1265\u127b\n"
            "\u1240\u12f5\u121e \u12e8\u1290\u1260\u1228\u12cd\u1295 \u1290\u1243\u12ed \u1201\u1209 \u12ed\u1270\u12ab\u120d"
        )
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
        return

    game_id = settings["id"]
    per_person = settings["numbers_per_person"]
    taken = get_taken_numbers(game_id)

    numbers = []   # (num, is_half, slot_only) \u2014 slot_only=None means all slots
    errors = []

    for part in parts[1:]:
        # NUM+SLOT pattern (\u1208\u121d\u1233\u120c 5+1 \u12c8\u12ed\u121d 5+2)
        import re as _re
        slot_match = _re.match(r'^(\d+)\+(\d+)$', part)
        if slot_match:
            num = int(slot_match.group(1))
            slot = int(slot_match.group(2))
            # \u2705 FIX: 1-5 \u1261\u12f5\u1295 \u1262\u1206\u1295 (numbers_per_person>1)\u1363 \u121b\u1295\u129b\u12cd\u121d \u1241\u1325\u122d
            # \u1260\u12da\u12eb \u1261\u12f5\u1295 \u12cd\u1235\u1325 (\u1208\u121d\u1233\u120c 4) \u2192 group's first number (1) \u12ed\u1206\u1293\u120d\u1363
            # \u121d\u12ad\u1295\u12eb\u1271\u121d DB \u120b\u12ed \u12e8\u1270\u1218\u12d8\u1308\u1260\u12cd \u1260 group start \u1265\u127b \u1290\u12cd
            actual_num = get_group_start(num, per_person) if per_person > 1 else num
            if actual_num < 1 or actual_num > settings["total_numbers"]:
                errors.append(part)
                continue
            # \u12eb slot exist \u12eb\u1228\u130b\u130d\u1325
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
        # \u2705 FIX: \u12a5\u12da\u1205\u121d \u1270\u1218\u1233\u1233\u12ed group-start mapping
        actual_num = get_group_start(num, per_person) if per_person > 1 else num
        if actual_num < 1 or actual_num > settings["total_numbers"]:
            errors.append(part)
            continue

        # NUM+ \u1232\u1206\u1295 2 slots \u12ab\u1208 \u12a0\u12ed\u1230\u122b\u121d
        if is_half:
            slots_for_num = taken.get(actual_num, [])
            if len(slots_for_num) > 1:
                errors.append(part + " (2 slots \u12a0\u1208 \u2014 5+1 \u12c8\u12ed\u121d 5+2 \u1320\u1240\u1235)")
                continue

        numbers.append((actual_num, is_half, None))

    if not numbers:
        await update.message.reply_text("\u274c \u1275\u12ad\u12ad\u1208\u129b \u1241\u1325\u122d \u12a0\u120d\u1270\u1308\u1298\u121d!")
        return

    # DB \u120b\u12ed nekay \u12eb\u12f0\u122d\u130b\u120d \u2014 slot_only \u12ab\u1208 \u12eb slot \u1265\u127b
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE registrations SET is_nekay=FALSE WHERE game_id=%s AND is_nekay=TRUE", (game_id,))

    snap = {}
    for num, is_half, slot_only in numbers:
        if slot_only is not None:
            # slot \u1265\u127b
            cur.execute("""
                UPDATE registrations SET is_nekay=TRUE
                WHERE game_id=%s AND number=%s AND slot=%s
            """, (game_id, num, slot_only))
            # FIX: \u12e8\u1275\u129b\u12cd slot \u12a5\u1295\u12f0\u1206\u1290 \u1270\u1208\u12ed\u1276 \u12ed\u1240\u1218\u1325 (-1 = slot 1, -2 = slot 2)
            # \u1235\u1208\u12da\u1205 user \u1232\u12ed\u12dd \u1275\u12ad\u12ad\u1208\u129b\u12cd slot force-overwrite \u12ed\u12f0\u1228\u130d\u1208\u1273\u120d
            snap[num] = -1 if slot_only == 1 else -2
        else:
            # FIX: "NUM+" (\u12e8\u1275\u129b\u12cd slot \u12a5\u1295\u12f3\u120d\u1270\u1308\u1208\u1338) \u2014 \u12ed\u1205 \u1265\u12d9 \u130a\u12dc \u121b\u1208\u1275 \u12e8\u121a\u1348\u120d\u1308\u12cd
            # "\u12ad\u134d\u1275 (\u1308\u1293 \u12eb\u120d\u1270\u12eb\u12d8\u12cd\u1295) slot \u12a5\u1295\u12f0 nekay \u12a0\u1233\u12ed/\u12a0\u1235\u1270\u12cb\u12cd\u1245" \u121b\u1208\u1275 \u1290\u12cd\u1363
            # "\u1290\u1263\u1229\u1295 registration nekay \u12a0\u12f5\u122d\u130d" \u121b\u1208\u1275 \u12a0\u12ed\u12f0\u1208\u121d\u1362 \u1235\u1208\u12da\u1205 \u12e8\u1275\u129b\u12cd slot
            # \u1260\u1275\u12ad\u12ad\u120d \u12ad\u134d\u1275 \u12a5\u1295\u12f0\u1206\u1290 \u12a0\u1228\u130b\u130d\u1326 \u12eb\u1295\u1295 \u1265\u127b \u12ed\u1290\u12ab\u120d (placeholder INSERT)\u1363
            # \u1290\u1263\u122d (\u12e8\u1270\u12a8\u1348\u1208) registration \u1348\u133d\u121e \u12a0\u12ed\u1290\u12ab\u121d\u1362
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
                    errors.append(part + " (\u1219\u1209 \u1270\u12ed\u12df\u120d)")
                    continue

                if target_slot in existing_slots:
                    # \u12eb specific slot \u122b\u1231 \u1290\u1263\u122d registration \u1235\u120b\u1208\u12cd \u1265\u127b \u2014
                    # \u12eb\u1295\u1295 \u1265\u127b nekay \u12a0\u12f5\u122d\u130d (\u1290\u1263\u122d \u120e\u1302\u12ad)
                    cur.execute("""
                        UPDATE registrations SET is_nekay=TRUE
                        WHERE game_id=%s AND number=%s AND slot=%s
                    """, (game_id, num, target_slot))
                else:
                    # \u12ad\u134d\u1275 slot \u2014 \u121b\u1295\u121d \u1308\u1293 \u12eb\u120d\u12eb\u12d8\u12cd\u1363 placeholder INSERT
                    # (nekay list \u120b\u12ed \u12a5\u1295\u12f2\u1273\u12ed/ \u12c8\u12f0\u134a\u1275 \u1230\u12cd \u1232\u12ed\u12d8\u12cd \u1260\u1275\u12ad\u12ad\u120d force
                    # \u12ed\u12f0\u1228\u130d\u1208\u1275 \u12d8\u1295\u12f5)
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

    # FIX: admin's own "/nekay ..." message \u12c8\u12f2\u12eb\u12cd\u1291 \u12ed\u1320\u134b (\u120d\u12ad \u12a5\u1295\u12f0 #/ \u12a5\u1293 #name)
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
    msg = f"\u2705 \u1290\u1243\u12ed \u1270\u1240\u121d\u1327\u120d: {reg_list}"
    if errors:
        msg += f"\n\u274c \u12eb\u120d\u1270\u1240\u1260\u1208: {', '.join(errors)}"
    # FIX #4: admin confirmation message \u12a81.5-2 \u1230\u12a8\u1295\u12f5 \u1260\u128b\u120b \u122b\u1231 \u12ed\u1320\u134b\u120d
    await _send_temp_admin_message(ctx.bot, group_id, msg)


# ============================================================
# NEW \u2014 "\U0001f525NUM[+SLOT] ..." \u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u121b\u12cd\u132b (admin text message)
#   \U0001f52516 21+   \u2192 \u1241\u1325\u122d 16 \u12a5\u1293 21 \u12a8\u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u12ed\u12c8\u1323\u1209 ("\u1290\u1243\u12ed \u12a0\u12ed\u12f0\u1208\u121d")
#   \U0001f5255+1      \u2192 \u1241\u1325\u122d 5 slot 1 \u1265\u127b \u12a8\u1290\u1243\u12ed \u12ed\u12c8\u1323\u120d
# \u12a8 DB \u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u120b\u12ed \u1265\u127b \u12eb\u12c8\u1323\u120d (mode \u1308\u1263\u122a \u1218\u1206\u1295 \u12a0\u12eb\u1235\u1348\u120d\u130d\u121d)\u1362 \u1263\u1208\u1264\u1275 \u12eb\u1208\u12cd (\u12e8\u1270\u1218\u12d8\u1308\u1260) \u1241\u1325\u122d is_nekay=FALSE
# \u12ed\u1206\u1293\u120d\u1363 \u1263\u1208\u1264\u1275 \u12e8\u120c\u1208\u12cd placeholder (/nekay 10+ \u12e8\u1348\u1320\u1228\u12cd \u1263\u12f6 slot) \u12ed\u1230\u1228\u12db\u120d\u1362
# ============================================================

async def handle_unnekay_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import re as _re_un
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    if not text.startswith("\U0001f525"):
        return

    body = text.replace("\ufe0f", "")[len("\U0001f525"):].strip()
    parts = [p for p in _re_un.split(r'[,\s]+', body) if p]
    # \u1241\u1325\u122d \u12e8\u121a\u1218\u1235\u120d \u12ab\u120d\u1206\u1290 (\u1270\u122b \U0001f525 \u12c8\u12ed\u121d \U0001f525 \u133d\u1201\u134d) \u12dd\u121d \u1265\u120e \u12ed\u1208\u134d
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
                errors.append(part + " (\u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u120b\u12ed \u12e8\u1208\u121d)")
                continue
            for r_slot, r_uid in rows:
                if not r_uid:
                    # \u1263\u1208\u1264\u1275 \u12e8\u120c\u1208\u12cd placeholder \u2192 \u12ed\u1230\u1228\u12db\u120d
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
        await _send_temp_admin_message(ctx.bot, group_id, "\u274c \u1235\u1205\u1270\u1275 \u1270\u1348\u1325\u122f\u120d\u1363 \u12a5\u1295\u12f0\u1308\u1293 \u121e\u12ad\u122d")
        return
    finally:
        cur.close()
        conn.close()

    if not removed:
        await _send_temp_admin_message(ctx.bot, group_id, f"\u274c \u12eb\u120d\u1270\u1308\u1298: {', '.join(errors)}")
        return

    # \u12a8 DB \u120b\u12ed \u1275\u12ad\u12ad\u1208\u129b\u12cd\u1295 \u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u12a5\u1295\u12f0\u1308\u1293 \u1218\u1308\u1295\u1263\u1275
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
            # \u1290\u1243\u12ed \u1219\u1209 \u1260\u1219\u1209 \u1263\u12f6 \u1206\u1290 \u2192 \u1290\u1243\u12ed mode \u12ed\u1320\u134b\u120d
            update_remaining_message_id(game_id, None)
            nekay_active.discard(key)
            nekay_numbers.pop(key, None)
            _stop_inactivity_tracker(game_id, group_id)

    out = f"\u2705 \u1290\u1243\u12ed \u12a0\u12ed\u12f0\u1208\u121d: {', '.join(removed)}"
    if errors:
        out += f"\n\u274c \u12eb\u120d\u1270\u1240\u1260\u1208: {', '.join(errors)}"
    await _send_temp_admin_message(ctx.bot, group_id, out)


# ============================================================
# COMPLETE STICKER COMMANDS
# ============================================================

async def handle_setcompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return
    ctx.user_data["awaiting_complete_sticker"] = True
    await update.message.reply_text("\u2705 \u12a0\u1201\u1295 sticker \u12ed\u120b\u12a9 (\u1201\u1209\u121d group \u120b\u12ed \u12ed\u1230\u122b\u120d)")


async def handle_listcompletestickers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    stickers = get_complete_stickers()
    if not stickers:
        await update.message.reply_text("\U0001f4cb Complete sticker \u12e8\u1208\u121d\u1362")
        return
    lines = ["\U0001f4cb Complete Stickers:\n"]
    for i, s in enumerate(stickers, 1):
        added = s["added_at"].strftime("%m/%d %H:%M") if s["added_at"] else "?"
        lines.append(f"{i}. file_id: {s['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removecompletesticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /removecompletesticker 1")
        return
    try:
        index = int(parts[1])
        success = remove_complete_sticker_by_index(index)
        if success:
            await update.message.reply_text(f"\u2705 Sticker #{index} \u1320\u134b!")
        else:
            await update.message.reply_text(f"\u274c #{index} \u12a0\u120d\u1270\u1308\u1298\u121d!")
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


async def handle_complete_sticker_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    if not ctx.user_data.get("awaiting_complete_sticker"):
        return
    msg = update.message
    if not msg.sticker:
        await msg.reply_text("\u274c Sticker \u1265\u127b \u12ed\u120b\u12a9!")
        return
    file_id = msg.sticker.file_id
    add_complete_sticker(file_id)
    ctx.user_data.pop("awaiting_complete_sticker", None)
    await msg.reply_text("\u2705 Complete sticker \u1270\u1240\u121d\u1327\u120d!")


# ============================================================
# PRE-BOOKING MEDIA COMMANDS
# ============================================================

async def handle_setprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return
    ctx.user_data["awaiting_prebooking_media"] = True
    await update.message.reply_text(
        "\u2705 \u12a0\u1201\u1295 photo/video/sticker \u12ed\u120b\u12a9 (pre-booking \u1232\u1300\u121d\u122d group \u120b\u12ed \u12ed\u120b\u12ab\u120d)\n"
        "\u1265\u12d9 \u130a\u12dc \u120a\u1328\u121d\u1229 \u12ed\u127d\u120b\u1209 \u2014 \u1201\u1209\u121d \u1260\u1245\u12f0\u121d \u1270\u12a8\u1270\u120d \u12ed\u120b\u12ab\u1209\u1362"
    )


async def handle_listprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    medias = get_prebooking_media()
    if not medias:
        await update.message.reply_text("\U0001f4cb Pre-booking media \u12e8\u1208\u121d\u1362")
        return
    lines = ["\U0001f4cb Pre-Booking Media:\n"]
    for i, m in enumerate(medias, 1):
        added = m["added_at"].strftime("%m/%d %H:%M") if m["added_at"] else "?"
        lines.append(f"{i}. {m['media_type']} \u2014 {m['file_id'][:20]}... ({added})")
    await update.message.reply_text("\n".join(lines))


async def handle_removeprebookingmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /removeprebookingmedia 1")
        return
    try:
        index = int(parts[1])
        success = remove_prebooking_media_by_index(index)
        if success:
            await update.message.reply_text(f"\u2705 Pre-booking media #{index} \u1320\u134b!")
        else:
            await update.message.reply_text(f"\u274c #{index} \u12a0\u120d\u1270\u1308\u1298\u121d!")
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


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
        await msg.reply_text("\u274c Photo/Video/Sticker \u1265\u127b \u12ed\u120b\u12a9!")
        return

    add_prebooking_media(file_id, media_type)
    ctx.user_data.pop("awaiting_prebooking_media", None)
    await msg.reply_text(f"\u2705 Pre-booking media \u1270\u1240\u121d\u1327\u120d! ({media_type})\n\u1270\u1328\u121b\u122a \u1208\u121b\u1235\u1240\u1218\u1325 /setprebookingmedia \u12f5\u130b\u121a \u1325\u1240\u1235\u1362")


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

    # NEW: winner-\U0001f525-reaction feature \u2014 this message's sender \u1270\u1218\u12dd\u130d\u1266 \u12ed\u1240\u1218\u1323\u120d
    # (DB write \u1290\u12cd\u1363 event loop \u12a5\u1295\u12f3\u12ed\u12d8\u1308\u12ed background thread \u120b\u12ed fire-and-forget
    # \u1206\u1296 \u12ed\u1230\u122b\u120d\u1363 \u121d\u1295\u121d \u1290\u1263\u122d \u120e\u1302\u12ad \u12a0\u12ed\u1290\u12ab\u121d)
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

    # \u2705 \u121b\u1293\u1278\u12cd\u121d URL \u2192 fetch \u12ed\u121e\u12ad\u122b\u120d (domain check \u12e8\u1208\u121d)
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
            await msg.reply_text("\u1241\u1325\u1229 \u12e8\u12a5\u122d\u1235\u12ce \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f")
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
                await msg.reply_text(f"{actual_num:02d} \u12e8\u12a5\u122d\u1235\u12ce \u1241\u1325\u122d \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f")
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
            await msg.reply_text(f"{from_num:02d} \u12e8\u12a5\u122d\u1235\u12ce \u1241\u1325\u122d \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f")
            return
        if to_num in paid:
            await msg.reply_text(f"{to_num:02d} \u2705 \u1270\u12a8\u134d\u120f\u120d \u1218\u1240\u12e8\u122d \u12a0\u12ed\u127b\u120d\u121d \U0001f64f")
            return
        if to_num in taken:
            await msg.reply_text(f"{to_num:02d} \u1270\u12ed\u12df\u120d \u1264\u1270\u1230\u1265 \u120c\u120b \u121d\u1228\u1325 \U0001f64f")
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
                await msg.reply_text(f"{to_num:02d} \u12a0\u120d\u1270\u127b\u1208\u121d \U0001f64f")
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
                line = f"{num} \u2014 \u121d\u12ad\u1295\u12eb\u1275 \u1273\u12c8\u1240 \U0001f64f"
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
        # FIX: \u1218\u1300\u1218\u122a\u12eb \u12a5\u1295\u12f0\u1270\u133b\u1348\u12cd (as-typed \u2014 "+" \u12e8\u120c\u120b\u1278\u12cd \u1219\u1209\u1363 "+" \u12eb\u120b\u1278\u12cd \u130d\u121b\u123d)
        # \u12c8\u12f2\u12eb\u12cd\u1291 \u12ed\u1218\u12d8\u1308\u1263\u120d\u1364 \u1325\u12eb\u1244\u12cd \u12a8\u12da\u12eb \u1260\u128b\u120b \u1265\u127b \u12ed\u1320\u12e8\u1243\u120d (\u12ab\u1235\u1348\u1208\u1308 \u1208\u12cd\u1325 \u1265\u127b
        # handle_ambiguous_reply \u120b\u12ed \u12ed\u12f0\u1228\u130b\u120d)\u1362 \u1240\u12f5\u121e \u121d\u12dd\u1308\u1263\u12cd \u1325\u12eb\u1244\u12cd \u12a5\u1235\u12aa\u1218\u1208\u1235
        # \u12f5\u1228\u1235 \u12ed\u1320\u1265\u1245 \u1290\u1260\u122d\u1363 \u12ed\u1205\u121d \u120c\u120b action \u1262\u1218\u1323 \u121d\u12dd\u1308\u1263 \u1233\u12ed\u1348\u1338\u121d \u12ed\u1240\u122d \u1290\u1260\u122d\u1362
        await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)
        if ambiguous == "all_half":
            await msg.reply_text("\u1201\u1209\u1295\u121d \u1260\u130d\u121b\u123d \u1290\u12cd? (\u12a0\u12ce/\u12a0\u12ed\u12f0\u1208\u121d)")
        elif ambiguous == "last_half":
            await msg.reply_text(f"{format_number(ambiguous_number)} \u1265\u127b \u1260\u130d\u121b\u123d \u1290\u12cd? (\u12a0\u12ce/\u12a0\u12ed\u12f0\u1208\u121d)")
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
    yes = text_lower in ["\u12a0\u12ce", "awo", "yes", "aha", "\u12a0\u12ce\u1295"]
    no = text_lower in ["\u12a0\u12ed\u12f0\u1208\u121d", "aydelem", "no", "\u12e8\u1208\u121d"]
    if not yes and not no:
        no = True

    numbers = pending["numbers"]
    ambiguous = pending["ambiguous"]
    ambiguous_number = pending["ambiguous_number"]
    settings = pending["settings"]

    del pending_ambiguous[user_id]

    # FIX: \u121d\u12dd\u1308\u1263\u12cd \u1240\u12f5\u121e (as-typed) \u1270\u1218\u12dd\u130d\u1267\u120d \u2014 \u12a5\u12da\u1205 \u12f0\u130d\u121e \u12e8\u121a\u12eb\u1235\u1348\u120d\u1308\u12cd \u1208\u12cd\u1325 \u1265\u127b
    # \u1290\u12cd \u12e8\u121a\u12f0\u1228\u1308\u12cd (register_number's toggle/target logic \u1240\u12f5\u121e \u12e8\u1270\u1218\u12d8\u1308\u1261\u1275\u1295
    # \u12c8\u12f0 \u12a0\u12f2\u1231 half/full \u12ed\u1240\u12ed\u122b\u120d)\u1362 \u1208\u12cd\u1325 \u12e8\u121b\u12eb\u1235\u1348\u120d\u130d \u12a8\u1206\u1290 \u121d\u1295\u121d \u12a0\u12ed\u12f0\u1228\u130d\u121d\u1362
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

    # FIX #3: admin "#name <name>" override \u12ab\u1208 (highest priority) \u2014
    # parsed_name/telegram username \u121d\u1295\u121d \u12ed\u1201\u1291 \u1201\u120c\u121d override \u1235\u121d \u1325\u1245\u121d \u120b\u12ed \u12ed\u12cd\u120b\u120d\u1362
    name_override = get_name_override(group_id, user_id)

    for num, is_half, parsed_name in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        nekay_snap_value = None
        if _gk(group_id, game_id) in nekay_numbers and actual_num in nekay_numbers.get(_gk(group_id, game_id), {}):
            nekay_snap_value = nekay_numbers[_gk(group_id, game_id)][actual_num]

        is_nekay = (nekay_snap_value is not None)
        # FIX: -1/-2 (06+1 / 06+2 slot-specific nekay) \u12f0\u130d\u121e force \u1293\u1278\u12cd \u2014
        # \u1240\u12f0\u121d \u1265\u120e 0 \u1265\u127b \u1290\u1260\u122d force \u1270\u1265\u120e \u12e8\u121a\u1273\u12e8\u12cd\u1363 \u1235\u1208\u12da\u1205 +1/+2 slot-specific
        # nekay \u120b\u12ed force overwrite \u1348\u133d\u121e \u12a0\u12ed\u1230\u122b\u121d \u1290\u1260\u122d\u1362
        is_nekay_force = nekay_snap_value in (0, -1, -2)
        force_slot = None
        if nekay_snap_value == -1:
            force_slot = 1
        elif nekay_snap_value == -2:
            force_slot = 2

        # FIX: parsed_name (\u1270\u1320\u1243\u121a\u12cd \u1260\u133d\u1201\u134d \u12eb\u1235\u1308\u1263\u12cd \u1235\u121d) \u12a8 #name override \u12e8\u1260\u1208\u1320
        # \u1245\u12f5\u121a\u12eb \u12eb\u1308\u129b\u120d\u1362 Override \u12e8\u121a\u1230\u122b\u12cd \u1270\u1320\u1243\u121a\u12cd \u121d\u1295\u121d \u1235\u121d \u12ab\u120d\u133b\u1348 \u1265\u127b \u1290\u12cd
        # (default/fallback)\u1362
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
                # FIX: \u1275\u12ad\u12ad\u1208\u129b\u12cd\u1295 slot \u12eb\u130d\u129d (is_paid \u121b\u1228\u130b\u1308\u132b \u1275\u12ad\u12ad\u1208\u129b\u12cd\u1295 slot \u12a5\u1295\u12f2\u1348\u1275\u123d)
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
            # FIX: is_half \u12a5\u1293 slot \u1275\u12ad\u12ad\u1208\u129b\u12cd\u1295 \u12cd\u1324\u1275 \u12eb\u1295\u1340\u1263\u122d\u1241 \u2014 \u1240\u12f5\u121e "registered_half"
            # (\u12a0\u12f2\u1235 \u1230\u12cd \u1240\u12f5\u121e \u1260\u130d\u121b\u123d \u12c8\u12f0\u1270\u12eb\u12d8 \u1241\u1325\u122d \u120b\u12ed "+" \u1233\u12ed\u1320\u1240\u121d \u1232\u1240\u120b\u1240\u120d) is_half=False
            # \u1270\u1265\u120e \u1260\u1235\u1205\u1270\u1275 \u12ed\u1218\u12d8\u1308\u1265 \u1290\u1260\u122d\u1363 \u12ed\u1205\u121d is_paid \u121b\u1228\u130b\u1308\u132b \u12e8\u1270\u1233\u1233\u1270 slot \u12a5\u1295\u12f2\u1348\u1275\u123d
            # \u12eb\u12f0\u122d\u130d \u1290\u1260\u122d (\u12e8\u1270\u1233\u1233\u1270 "still needs payment" \u1218\u120d\u12a5\u12ad\u1275 \u12eb\u1218\u1323 \u1290\u1260\u122d)\u1362
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

    # FIX: board edit delay \u2014 get_taken_numbers/get_paid_numbers (psycopg2,
    # blocking) event loop \u1295 \u12a5\u1295\u12f3\u12eb\u130d\u12f5 asyncio.to_thread \u12cd\u1235\u1325 \u12ed\u122e\u1323\u1209\u1362 register_number
    # (\u12a8\u120b\u12ed \u1263\u1208\u12cd loop \u12cd\u1235\u1325) \u1206\u1295 \u1270\u1265\u120e \u12a0\u120d\u1270\u1290\u12ab\u121d \u2014 race condition \u12a5\u1295\u12f3\u12ed\u1348\u1320\u122d\u1362
    taken = await asyncio.to_thread(get_taken_numbers, game_id)
    paid = await asyncio.to_thread(get_paid_numbers, game_id)
    remaining_count = count_remaining(settings, taken)
    snap = nekay_numbers.get(_gk(group_id, game_id), {})
    nekay_list = _build_nekay_from_snap(snap)

    if not registered and not all_taken and no_change_reply:
        await msg.reply_text("\u12a5\u123a \U0001f64f")
        return

    reg_result = "registered" if registered else ("taken" if all_taken else None)

    # FIX #2: \u1201\u1209\u121d \u1241\u1325\u122e\u127d \u2705 (\u1201\u1209\u121d \u1270\u12a8\u134d\u1208\u12cd) \u12ab\u1208\u1241 \u1260\u128b\u120b (\u12cd\u1324\u1275 \u1308\u1293 \u12ab\u120d\u1273\u12c8\u1240/pre-booking
    # \u1308\u1293 \u12ab\u120d\u1300\u1218\u1228)\u1363 \u1230\u12cd \u1241\u1325\u122d \u1208\u1218\u12eb\u12dd \u1262\u121e\u12ad\u122d "\u1270\u1240\u12f0\u121d\u12ad" \u12a8\u1218\u1218\u1208\u1235 \u12ed\u120d\u1245 "\u12a0\u1201\u1295 \u12e8\u12cd\u1324\u1275 \u1230\u12d3\u1275
    # \u1290\u12cd" \u12ed\u1218\u1208\u1235\u1362
    if reg_result == "taken" and all_numbers_paid(game_id, settings):
        await msg.reply_text("\u12a0\u1201\u1295 \u12e8\u12cd\u1324\u1275 \u1230\u12d3\u1275 \u1290\u12cd \u1264\u1270\u1230\u1265 \u1275\u1295\u123d \u12ed\u1320\u1265\u1241 \U0001f64f")
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

    # FIX #1 + #6: pre-booking \u1230\u12d3\u1275 (\u12cd\u1324\u1275/board \u1308\u1293 \u1235\u120b\u120d\u1273\u12c8\u1240 \u1308\u1295\u12d8\u1261 \u121b\u1295
    # \u12a5\u1295\u12f0\u121a\u12ed\u12d8\u12cd \u1308\u1293 \u1235\u1208\u121b\u12ed\u1273\u12c8\u1245) \u12e8\u1270\u1233\u12ab \u121d\u12dd\u1308\u1263 \u120b\u12ed \u12e8\u133d\u1201\u134d reply \u1233\u12ed\u1206\u1295 \U0001f44d reaction
    # \u1265\u127b \u12ed\u120b\u12ad\u1362 \u12f0\u130d\u121e\u121d reply/reaction Telegram API call \u1295 fire-and-forget
    # (asyncio.create_task) \u12a0\u12f5\u122d\u1308\u1295 \u12a5\u1295\u120d\u12ab\u1208\u1295\u1363 \u1235\u1208\u12da\u1205 \u12a8\u1273\u127d \u12eb\u1208\u12cd board edit
    # \u12ed\u1205\u1295 call \u12a5\u1235\u12aa\u1218\u1208\u1235 \u12f5\u1228\u1235 \u1218\u1320\u1260\u1245 \u12a0\u12eb\u1235\u1348\u120d\u1308\u12cd\u121d (\u1240\u12f5\u121e sequential \u1235\u1208\u1290\u1260\u122d board
    # edit \u12ed\u12d8\u1308\u12ed \u1290\u1260\u122d)\u1362
    if reg_result == "registered" and (group_id in prebooking_groups or group_id in winner_pending_groups):
        asyncio.create_task(_safe_set_reaction(ctx.bot, group_id, msg.message_id))
    elif resp["reply"]:
        if reg_result == "taken":
            # NEW: "\u12a5\u123a/eshi" replacement feature \u12ed\u1205\u1295 rejection reply message_id
            # \u12a5\u1295\u12f2\u12eb\u1308\u1298\u12cd (\u12c8\u12f0\u134a\u1275 admin \u1262\u1270\u12ab\u12cd \u12a5\u1295\u12f2\u1320\u134b) \u1270\u1218\u12dd\u130d\u1266 \u12ed\u1240\u1218\u1323\u120d
            asyncio.create_task(_safe_reply_text_and_track(msg, resp["reply"], group_id))
        else:
            asyncio.create_task(_safe_reply_text(msg, resp["reply"]))

    if not registered:
        return

    if skip_board_update:
        return

    # pre-booking mode (\u12c8\u12ed\u121d winner photo 30s \u12ad\u134d\u1270\u1275) \u2014 registration \u1270\u1230\u122d\u1277\u120d
    # \u130d\u1295 board \u12a0\u12ed\u1273\u12ed\u121d
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

        # FIX: intermittent nekay-list corruption \u2014 \u12a8\u120b\u12ed snap \u12a8\u1270\u1290\u1260\u1260 \u1300\u121d\u122e
        # (\u1218\u1235\u1218\u122d ~1968) \u12a5\u1235\u12a8\u12da\u1205 \u12f5\u1228\u1235 \u1265\u12d9 awaits (board/nekay message edits)
        # \u1235\u120b\u1209\u1363 2 \u1230\u12ce\u127d \u1260\u1270\u1218\u1233\u1233\u12ed \u1230\u12d3\u1275 \u12e8\u1270\u1208\u12eb\u12e8 \u1241\u1325\u122d \u1262\u12ed\u12d9 (interleaved coroutines)
        # \u1260\u12a0\u1295\u12f5 shared dict \u120b\u12ed \u1270\u12f0\u122b\u122d\u1260\u12cd \u120a\u1323\u1228\u1231 \u12ed\u127d\u120b\u1209 (\u120c\u120b\u12cd\u1295 entry \u120a\u12eb\u1320\u1349
        # \u12ed\u127d\u120b\u1209)\u1362 \u1235\u1208\u12da\u1205 \u120d\u12ad \u12a8\u1218\u1295\u12ab\u1271 \u1260\u134a\u1275 \u12e8\u1245\u122d\u1265 \u130a\u12dc\u12cd\u1295 nekay_numbers \u12f0\u130d\u121e
        # \u12a5\u1293\u1290\u1265\u1260\u12cb\u1208\u1295 (race window \u1208\u1218\u1240\u1290\u1235)\u1362
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
    \u2705/? marker parsing \u2014 \u1270\u1320\u1243\u121a\u12cd \u12a5\u12cd\u1290\u1270\u129b \u1235\u121d \u122b\u1231 "?" \u1262\u12ed\u12dd (\u1208\u121d\u1233\u120c \u1235\u1219 \u1260\u1275\u12ad\u12ad\u120d
    "??" \u1262\u1206\u1295) stripping \u1235\u1219\u1295 \u1219\u1209 \u1208\u1219\u1209 \u1263\u12f6 \u12a5\u1295\u12f3\u12eb\u12f0\u122d\u1308\u12cd \u12ed\u1320\u1265\u1243\u120d\u1366 stripping "?"
    \u1235\u1219\u1295 \u1263\u12f6 \u12e8\u121a\u12eb\u12f0\u122d\u1308\u12cd \u12a8\u1206\u1290 (\u12a5\u1293 stripping \u12a8\u1218\u12f0\u1228\u1309 \u1260\u134a\u1275 \u12ed\u12d8\u1275 \u1290\u1260\u1228) \u12eb "?" \u12a5\u1295\u12f0
    pending marker \u1233\u12ed\u1206\u1295 \u12e8\u1235\u1219 \u12a0\u12ab\u120d \u1270\u12f0\u122d\u130e \u12ed\u12eb\u12db\u120d\u1362
    """
    paid = "\u2705" in raw
    no_check = raw.replace("\u2705", "").strip()
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
# NEW \u2014 WINNER "\U0001f525 REACTION" BALANCE-CLEAR FEATURE
# Admin puts a native \U0001f525 reaction on any message previously sent BY a
# recent winner (1\u129b/2\u129b/3\u129b) in the group \u2192 that winner's balance ONLY
# gets cleared (exactly like /clearbalance @username, by telegram_id).
# Board/registrations/paid status \u1293\u1278\u12cd untouched \u2014 user_balance \u1265\u127b \u1290\u12cd
# \u12e8\u121a\u1338\u12f3\u12cd\u1362 Confirmation message ("\u2705 ... \u1338\u12f5\u1277\u120d") \u12ed\u120b\u12ab\u120d \u12a5\u1293 1.5 \u1230\u12a8\u1295\u12f5 \u1246\u12ed\u1276
# \u122b\u1231 \u12ed\u1320\u134b\u120d (_send_temp_admin_message helper \u1270\u1320\u1245\u121e)\u1362
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

    if "\U0001f525" not in new_emojis:
        return

    old_emojis = set()
    for r in (reaction.old_reaction or []):
        emoji = getattr(r, "emoji", None)
        if emoji:
            old_emojis.add(emoji)

    if "\U0001f525" in old_emojis:
        # \u1240\u12f5\u121e\u12cd\u1291 \U0001f525 \u1290\u1260\u1228\u12cd (\u12a0\u12f2\u1235 addition \u12a0\u12ed\u12f0\u1208\u121d) \u2014 \u12f5\u130b\u121a balance \u121b\u133d\u12f3\u1275 \u12a0\u12eb\u1235\u1348\u120d\u130d\u121d
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

    # \u2705 "cleared" \u121b\u1228\u130b\u1308\u132b message \u12ed\u120b\u12ab\u120d\u1363 \u120d\u12ad \u12a5\u1295\u12f0 nekay 1.5 \u1230\u12a8\u1295\u12f5 \u1246\u12ed\u1276 \u122b\u1231 \u12ed\u1320\u134b\u120d
    await _send_temp_admin_message(
        ctx.bot, group_id, f"\u2705 {target_name} \u1263\u120b\u1295\u1235 \u1338\u12f5\u1277\u120d", delay=1.5,
    )


async def handle_winner_correction_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group \u120b\u12ed bot winner announcement \u120b\u12ed '#/ 10 20 31' reply \u1232\u12eb\u12f0\u122d\u130d
    handle_winner_correction \u12ed\u1320\u122b\u1362
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

    # reply to bot message \u1265\u127b \u12ed\u1230\u122b
    if not msg.reply_to_message:
        return
    if not msg.reply_to_message.from_user:
        return
    if not msg.reply_to_message.from_user.is_bot:
        return

    # 'Winners!' \u12c8\u12ed\u121d 'Winners (\u1270\u1235\u1270\u12ab\u12a8\u1208)' announcement \u120b\u12ed \u1265\u127b
    replied_text = msg.reply_to_message.text or ""
    if "\U0001f3c6" not in replied_text and "Winners" not in replied_text:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    from handlers import handle_winner_correction, parse_winner_correction
    numbers = parse_winner_correction(text)
    if not numbers:
        await msg.reply_text("\u274c \u121d\u1233\u120c: #/ 10  \u12c8\u12ed\u121d  #/ 10 20  \u12c8\u12ed\u121d  #/ 10 20 31")
        return

    # DB \u120b\u12ed \u12eb\u1209 current winners \u12eb\u121d\u1323 (\u1208 reverse \u12eb\u1235\u1348\u120d\u130b\u1209)
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

    # previous_winners format \u1208 handle_winner_correction
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

            # FIX: admin \u1265\u12d9 \u130a\u12dc \u1219\u1209\u12cd\u1295 board \u133d\u1201\u134d \u12ae\u1352 \u12a0\u12f5\u122d\u130e (\u12e8\u1348\u1208\u1308\u12cd\u1295 1 \u1218\u1235\u1218\u122d
            # \u1265\u127b \u1240\u12ed\u122e) reply \u12eb\u12f0\u122d\u130b\u120d \u2014 \u1235\u1208\u12da\u1205 _parse_board_text() \u12eb\u120d\u1270\u1290\u12a9\u1275\u1295\u121d
            # \u1218\u1235\u1218\u122e\u127d (\u1201\u1209\u1295\u121d \u1241\u1325\u122e\u127d) \u132d\u121d\u122d \u12ed\u1218\u120d\u1233\u120d\u1362 \u12ed\u1205 line \u12a8 DB \u12cd\u1235\u1325 \u12ab\u1208\u12cd \u130b\u122d
            # \u134d\u1339\u121d \u1270\u1218\u1233\u1233\u12ed (\u121d\u1295\u121d \u12eb\u120d\u1270\u1240\u12e8\u1228) \u12a8\u1206\u1290 \u1328\u122d\u1236 \u12a0\u1295\u1295\u12ab\u12cd\u121d \u2014 \u12a0\u1208\u1260\u1208\u12da\u12eb
            # admin_remove_player+register_number (is_nekay \u1201\u120d\u130a\u12dc FALSE
            # \u12a0\u12f5\u122d\u130e \u1235\u1208\u121a\u12eb\u1235\u1308\u1263) \u12eb\u120d\u1270\u1290\u12a9 \u1241\u1325\u122e\u127d \u120b\u12ed \u12eb\u1208\u12cd\u1295 is_nekay \u1201\u1294\u1273 \u12eb\u1320\u134b\u12cb\u120d
            # (\u12ed\u1205 \u1290\u12cd \u1290\u1243\u12ed list \u1219\u1209 \u1208\u1219\u1209 \u12f5\u1295\u1308\u1275 \u12ed\u1320\u134b \u12e8\u1290\u1260\u1228\u12cd \u1275\u12ad\u12ad\u1208\u129b \u121d\u12ad\u1295\u12eb\u1275)\u1362
            #
            # FIX #2: is_half \u12f0\u130d\u121e \u121b\u1290\u133b\u1338\u122d \u12a0\u1208\u1260\u1275 \u2014 \u12a8\u12da\u1205 \u1260\u134a\u1275 \u1235\u121d/paid \u1265\u127b \u1290\u1260\u122d
            # \u12e8\u121a\u1290\u133b\u1338\u1228\u12cd\u1363 \u1235\u1208\u12da\u1205 "\u1260\u1219\u1209 \u12e8\u1290\u1260\u1228 \u1241\u1325\u122d \u12c8\u12f0 \u130d\u121b\u123d \u1218\u1240\u12e8\u122d" (\u1235\u121d/paid
            # \u1270\u1218\u1233\u1233\u12ed \u1206\u1296 is_half \u1265\u127b \u1232\u1240\u12e8\u122d) \u1328\u122d\u1236 "\u121d\u1295\u121d \u12a0\u120d\u1270\u1240\u12e8\u1228\u121d" \u1270\u1265\u120e \u12ed\u1273\u1208\u134d
            # \u1290\u1260\u122d \u2014 admin \u1218\u1300\u1218\u122a\u12eb \u1263\u12f6 \u12a0\u12f5\u122d\u130e \u12a8\u12da\u12eb \u12a5\u1295\u12f0\u1308\u1293 \u1232\u133d\u134d \u1265\u127b \u12ed\u1230\u122b \u12e8\u1290\u1260\u1228\u12cd
            # \u1208\u12da\u1205 \u1290\u12cd\u1362
            current_name1 = name_map.get(1)
            current_paid1 = bool(paid_map.get(1, False))
            current_is_half1 = bool(half_map.get(1, False))
            current_name2 = name_map.get(2)
            current_paid2 = bool(paid_map.get(2, False))
            if (name1 == current_name1 and paid1 == current_paid1
                    and is_half1 == current_is_half1
                    and name2 == current_name2 and paid2 == current_paid2):
                continue

            # FIX: slot1/slot2 \u1295 \u1270\u1290\u1323\u1325\u120e \u121b\u1290\u133b\u1338\u122d (\u12a8\u12da\u1205 \u1260\u134a\u1275 \u1201\u1208\u1271\u121d slots
            # \u120b\u12ed \u1275\u1295\u123d \u1208\u12cd\u1325 \u12a5\u1295\u12b3 \u1262\u1296\u122d \u1201\u1208\u1271\u121d \u12ed\u1230\u1228\u12d9 \u1290\u1260\u122d \u2014 \u1235\u1208\u12da\u1205 \u12eb\u120d\u1270\u1290\u12ab\u12cd slot
            # (\u1208\u121d\u1233\u120c nekay/unpaid \u12e8\u1206\u1290) \u132d\u121d\u122d \u12ed\u1320\u134b \u1290\u1260\u122d)
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
# OWNER REASSIGNMENT \u2014 admin replies to a REAL USER's message with
# "#/ 01 21 31+1" to attach that user's telegram_id to numbers that
# were registered manually (board edit / /register) without a real
# telegram user_id. Only fixes ownership (user_id) \u2014 user_name and
# paid status entered by the admin are left untouched.
#   #/ 01        \u2192 number 1, all slots \u2192 this user
#   #/ 31+1      \u2192 number 31, slot 1 only \u2192 this user
#   #/ 11        \u2192 if number 11 already belongs to someone else,
#                   ownership is transferred to this user
# ============================================================

async def handle_owner_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # \u2705 FIX: 2 \u1219\u1209 \u1260\u1219\u1209 \u12e8\u1270\u1208\u12eb\u12e9 syntax \u2014 \u12a5\u1295\u12f3\u12ed\u121d\u1273\u1271 (\u12ed\u1205 \u134d\u1270\u123b \u1240\u12f5\u121e \u12a5\u1295\u12f2\u12f0\u1228\u130d
    # \u1270\u1295\u1240\u1233\u1245\u1237\u120d\u1363 \u1235\u1208\u12da\u1205 "#" \u1263\u120d\u1300\u1218\u1228 message \u120b\u12ed \u12cb\u130b \u12e8\u120c\u1208\u12cd DB call \u12a0\u12ed\u12f0\u1228\u130d\u121d)
    #   (#<amount> winner \u12ad\u134d\u12eb \u1270\u12c8\u130d\u12f7\u120d \u2014 \u1208\u12da\u12eb \U0001f525 reaction \u12ed\u1320\u1240\u1219)
    #   "#/ NUM ..."  (\u1235\u120b\u123d \u12a0\u1208\u12cd)  \u2192 Owner reassignment \u1265\u127b, \u1208\u121d\u1233\u120c #/ 01 21 31+1
    #   "#name <\u1235\u121d>"  \u2192 FIX #3: name override, \u1208\u121d\u1233\u120c #name \u12a0\u1260\u1260 \u12c8\u12ed\u121d #name \u12a0\u1260\u1260 \u12a8\u1260\u12f0
    #                    "#name" \u1265\u127b (\u1235\u121d \u1233\u12ed\u12a8\u1270\u120d) \u2192 override reset
    #   "##cancel"    \u2192 payment-fingerprint feature: \u12eb user's fingerprint \u12eb\u1320\u134b\u120d
    #   "##<SMS text>" \u2192 payment-fingerprint feature: admin \u122b\u1231 \u12e8\u12f0\u1228\u1230\u12cd\u1295 SMS
    #                    \u133d\u1201\u134d \u12ae\u1352 \u12a0\u12f5\u122d\u130e reply \u12eb\u12f0\u122d\u130b\u120d \u2192 AI parse \u2192 confirm_payment
    #                    + fingerprint learn (\u12c8\u12f0\u134a\u1275 "\u120d\u12ac\u12eb\u1208\u12cd" \u122b\u1235-\u1230\u122d \u12a5\u1295\u12f2\u1206\u1295)
    #   "# NUM[+SLOT][\u2705] ..." \u2192 reply-to-user (\u1270\u12ed\u12de\u1265\u1203\u120d \u12eb\u1208\u1260\u1275
    #                    \u12a6\u122d\u1305\u1293\u120d message \u120b\u12ed reply) \u1263\u1208\u1264\u1275+\u1235\u121d \u12ed\u1270\u12ab\u120d\u1363 \u2705 \u12ab\u1208 paid
    #                    \u1270\u1265\u120e \u12ed\u1218\u12d8\u1308\u1263\u120d\u1363 \u1240\u12f0\u121d \u12eb\u1208\u12cd bot rejection message \u12ed\u1320\u134b\u120d\u1363
    #                    "NUM \u1270\u12ed\u12de\u120d\u1203\u120d \U0001f64f" \u12a0\u12f2\u1235 message \u12ed\u120b\u12ab\u120d\u1362 "#" prefix \u130d\u12f5
    #                    \u1290\u12cd\u1362
    is_sms_cancel_form = text.lower().startswith("##cancel")
    is_sms_paste_form = text.startswith("##") and not is_sms_cancel_form
    is_name_form = text.lower().startswith("#name")
    is_owner_form = text.startswith("#/")
    # "# NUM[+SLOT][\u2705] ..." \u2014 \u1263\u1208\u1264\u1275+\u1235\u121d \u1218\u1270\u12aa\u12eb (\u12e8\u1240\u12f5\u121e\u12cd #eshi/#\u12a5\u123a \u1235\u122b \u12a0\u1201\u1295 \u1260 "#" \u1265\u127b)
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
            await msg.reply_text("\u274c \u1295\u1241 \u1328\u12cb\u1273 \u12e8\u1208\u121d (active game required)")
        return

    # winner-correction replies (reply to the BOT's Winners announcement)
    # are handled by handle_winner_correction_reply \u2014 this handler is only
    # for replies to a REAL USER's message (ownership fix / payment).
    if not msg.reply_to_message:
        logging.info("[OwnerReply] Rejected: not a reply to any message")
        if is_eshi_form:
            await msg.reply_text("\u274c # \u12e8\u1270\u1320\u1243\u121a\u12cd\u1295 message \u120b\u12ed reply \u1270\u12f0\u122d\u130e \u1218\u133b\u134d \u12a0\u1208\u1260\u1275")
        return
    if not msg.reply_to_message.from_user:
        logging.info("[OwnerReply] Rejected: reply_to_message has no from_user")
        if is_eshi_form:
            await msg.reply_text("\u274c \u12ed\u1205 message \u120b\u12ed reply \u121b\u12f5\u1228\u130d \u12a0\u12ed\u127b\u120d\u121d")
        return
    if msg.reply_to_message.from_user.is_bot:
        logging.info("[OwnerReply] Rejected: replied-to message is from the bot (handled elsewhere)")
        if is_eshi_form:
            await msg.reply_text("\u274c # \u12e8 bot message \u120b\u12ed \u1233\u12ed\u1206\u1295 \u12e8\u1270\u1320\u1243\u121a\u12cd\u1295 \u12a6\u122d\u1305\u1293\u120d message \u120b\u12ed reply \u1218\u12f0\u1228\u130d \u12a0\u1208\u1260\u1275")
        return

    owner = msg.reply_to_message.from_user
    owner_id = owner.id

    import re as _re_owner

    # ============================================================
    # FIX #3: "#name <name>" \u2014 name override reply-to-user command
    # "#name" \u1265\u127b (\u1235\u121d \u1233\u12ed\u12a8\u1270\u120d) \u2192 override \u12ed\u1320\u134b\u120d\u1363 \u12c8\u12f0 original \u1235\u121d-\u1218\u1208\u12eb logic
    # \u12ed\u1218\u1208\u1233\u120d (parsed_name \u122b\u1231 \u12a0\u120d\u1270\u1290\u12ab\u121d)\u1362 admin \u12f0\u130b\u130d\u121e \u120a\u1240\u12ed\u1228\u12cd \u12ed\u127d\u120b\u120d \u2014 \u1201\u120d\u130a\u12dc
    # \u12e8\u1218\u1328\u1228\u123b\u12cd \u1275\u12d5\u12db\u12dd \u12ed\u1230\u122b\u120d\u1362 admin's own "#name ..." message \u12c8\u12f2\u12eb\u12cd\u1291 \u12ed\u1320\u134b\u120d
    # (\u120d\u12ad \u12a5\u1295\u12f0 #/ \u12a5\u1293 # \u1275\u12d5\u12db\u12de\u127d)\u1362
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
    # "##cancel" \u2014 admin \u12e8\u1270\u1233\u1233\u1270 fingerprint (\u1235\u121d/last4) \u12ab\u1235\u1240\u1218\u1320 \u1208\u12da\u1205 user
    # (reply-to-user) \u12eb\u1208\u12cd\u1295 fingerprint \u1219\u1209 \u1260\u1219\u1209 \u12eb\u1320\u134b\u120d\u1362
    # ============================================================
    if is_sms_cancel_form:
        delete_user_fingerprint(group_id, owner_id)
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        winner_name = owner.first_name or owner.username or "Unknown"
        await _send_temp_admin_message(ctx.bot, group_id, f"\u2705 {winner_name} fingerprint \u1320\u134b")
        return

    # ============================================================
    # "##<SMS text>" \u2014 admin \u12e8\u12f0\u1228\u1230\u12cd\u1295 \u1275\u12ad\u12ad\u1208\u129b SMS \u133d\u1201\u134d \u12ae\u1352 \u12a0\u12f5\u122d\u130e user's
    # message \u120b\u12ed reply \u12eb\u12f0\u122d\u130b\u120d\u1362 AI (Groq) parse \u12eb\u12f0\u122d\u1308\u12cb\u120d\u1363 \u1235\u121d/last4
    # \u12ab\u1323 \u1265\u127b (URL \u12ab\u1208) Jina+Groq \u1219\u1209 receipt \u12eb\u1218\u1323\u120d\u1363 \u12a8\u12db reply-to \u12eb\u1208\u12cd
    # owner_id \u120b\u12ed \u1260\u1240\u1325\u1273 confirm_payment() \u1270\u1320\u122d\u1276 fingerprint \u12ed\u121b\u122b\u120d\u1362
    # ============================================================
    if is_sms_paste_form:
        sms_text = text[2:].strip()
        if not sms_text:
            await msg.reply_text("\u274c \u121d\u1233\u120c: ##<SMS \u133d\u1201\u134d \u12ae\u1352 \u12a0\u12f5\u122d\u1308\u1205 \u1208\u1325\u134d>")
            return

        settings_for_sms = get_active_settings(group_id=group_id)
        result = await handle_admin_sms_paste(ctx.bot, msg, sms_text, owner_id, group_id)

        if not result.get("success"):
            await msg.reply_text("\u274c SMS \u120a\u1270\u1290\u1270\u1295 \u12a0\u120d\u127b\u1208\u121d \u2014 \u133d\u1201\u1349\u1295 \u12a5\u1295\u12f0\u1308\u1293 \u12ae\u1352 \u12a0\u12f5\u122d\u1308\u1205 \u120b\u12ad")
            return

        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        winner_name = owner.first_name or owner.username or "Unknown"
        amount = result.get("amount")
        await _send_temp_admin_message(
            ctx.bot, group_id, f"\u2705 {winner_name} \u2192 ETB {amount} \u1270\u1228\u130b\u130d\u1327\u120d (SMS)"
        )

        if settings_for_sms:
            await _refresh_board(ctx, settings_for_sms, group_id)
        return

    # ============================================================
    # NEW \u2014 "# NUM[+SLOT][\u2705] ..." REPLACEMENT (reply-to-user's own
    # "01" attempt message, \u120d\u12ad \u12ab\u1208\u1348\u12cd \u12c8\u12ed\u121d \u1308\u1293 \u12ab\u1208\u12cd rejection ("\u1270\u12ed\u12de\u1265\u1203\u120d") \u130b\u122d)\u1362
    # \u1263\u1208\u1264\u1275+\u1235\u121d \u12ed\u1270\u12ab\u120d\u1363 \u2705 \u12ab\u1208 \u12eb \u1241\u1325\u122d paid \u1270\u1265\u120e \u12ed\u1218\u12d8\u1308\u1263\u120d (\u12ab\u120d\u1206\u1290 unpaid \u12ed\u1206\u1293\u120d)\u1363
    # \u1240\u12f0\u121d \u12eb\u1208\u12cd bot rejection message \u12ed\u1320\u134b\u120d\u1363 "NUM \u1270\u12ed\u12de\u120d\u1203\u120d \U0001f64f" \u12a0\u12f2\u1235 message
    # \u1208 user \u12ed\u120b\u12ab\u120d\u1363 board \u120b\u12ed \u1235\u121d \u12ed\u1240\u12e8\u122b\u120d\u1362
    # ============================================================
    if is_eshi_form:
        settings_eshi = get_active_settings(group_id=group_id)
        if not settings_eshi:
            return
        game_id_eshi = settings_eshi["id"]

        eshi_body = text[1:].strip()

        eshi_parts = [p for p in _re_owner.split(r'[,\s]+', eshi_body.strip()) if p]
        if not eshi_parts:
            await msg.reply_text("\u274c \u121d\u1233\u120c: # 01 \u12c8\u12ed\u121d # 01+2 06\u2705")
            return

        target_name = owner.first_name or owner.username or "Unknown"

        assigned = []
        errors = []
        for part in eshi_parts:
            mark_paid = "\u2705" in part
            clean_part = part.replace("\u2705", "")
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
                # FIX: \u1219\u1209 (full) \u12a8\u1206\u1290 \u2014 \u1290\u1263\u122d slot(s) (\u1263\u12f6\u1363 \u130d\u121b\u123d\u1363 \u12c8\u12ed\u121d \u1219\u1209
                # \u12ed\u1201\u1291) \u121d\u1295\u121d \u12ed\u1201\u1291 \u1295\u1341\u1205 \u1260\u12a0\u1295\u12f5 full row \u12ed\u1270\u12ab\u120d\u1362 admin_replace_owner
                # \u1265\u127b \u1262\u1320\u1240\u121d (UPDATE \u1265\u127b) is_half \u12a0\u12ed\u1290\u12ab\u121d/ \u1270\u1328\u121b\u122a slot2 row
                # \u12a0\u12ed\u1320\u134b\u121d \u1290\u1260\u122d \u2014 \u1235\u1208\u12da\u1205 \u130d\u121b\u123d\u2192\u1219\u1209 change \u1348\u133d\u121e \u12a0\u12ed\u1230\u122b\u121d \u1290\u1260\u122d\u1362
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
                # FIX: "01+" (\u12e8\u1275\u129b\u12cd slot \u12a5\u1295\u12f3\u120d\u1308\u1208\u133d\u12ad) \u1232\u1263\u120d \u2014 \u1290\u1263\u122d registration
                # \u12ab\u1208 (\u1208\u121d\u1233\u120c slot1=\u12a0\u1260\u1260)\u1363 \u12ad\u134d\u1275 slot \u1295 (slot2) \u1265\u127b \u1290\u12cd \u1218\u12eb\u12dd
                # \u12eb\u1208\u1260\u1275 \u2014 \u1290\u1263\u1229\u1295 (\u12a0\u1260\u1260\u1295) \u1328\u122d\u1236 \u1218\u1270\u12ab\u1275 \u12e8\u1208\u1260\u1275\u121d\u1362 \u12e8\u1275\u129b\u12cd slot \u12ad\u134d\u1275
                # \u12a5\u1295\u12f0\u1206\u1290 \u12a0\u1228\u130b\u130d\u1326 \u1265\u127b \u12ed\u1290\u12ab\u120d\u1362
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
                    errors.append(part + " (\u1219\u1209 \u1270\u12ed\u12df\u120d)")
                    continue

            found = admin_replace_owner(
                game_id_eshi, number, owner_id, target_name,
                slot=slot, mark_paid=mark_paid,
            )

            if not found:
                # NEW: \u1241\u1325\u1229 \u1263\u12f6 (\u121d\u1295\u121d registration \u1235\u120b\u120d\u1290\u1260\u1228 replace \u12eb\u120d\u1270\u1233\u12ab)
                # \u12a8\u1206\u1290 \u2014 replace \u1265\u127b \u1233\u12ed\u1206\u1295 \u12a0\u12f2\u1235 registration \u12f0\u130d\u121e \u12ed\u134d\u1320\u122d
                # (register_number()'s force_slot path is_nekay=TRUE \u12e8\u121a\u1320\u12ed\u1245
                # \u1235\u1208\u1206\u1290 \u12a5\u1293 \u120c\u120b\u129b\u12cd slot \u1290\u1263\u122d \u1262\u1206\u1295 \u1275\u12ad\u12ad\u120d \u1235\u1208\u121b\u12ed\u1230\u122b\u1363 \u1260\u1240\u1325\u1273 INSERT
                # \u12a5\u1295\u1320\u1240\u121b\u1208\u1295 \u2014 admin override \u1235\u1208\u1206\u1290 balance \u12a0\u12ed\u1290\u12ab\u121d)
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
                await msg.reply_text(f"\u274c \u12eb\u120d\u1270\u1308\u1298: {', '.join(errors)}")
            return

        # \u1240\u12f0\u121d \u12eb\u1208\u12cd bot "\u1270\u12ed\u12de\u1265\u1203\u120d" rejection message \u12ab\u1208 \u12ed\u1320\u134b
        rejection_key = (group_id, msg.reply_to_message.message_id)
        old_rejection_msg_id = _taken_rejection_msgs.pop(rejection_key, None)
        if old_rejection_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=old_rejection_msg_id)
            except Exception:
                pass

        # admin's own "# ..." command message \u12ed\u1320\u134b
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass

        # \u12a0\u12f2\u1235 "NUM \u1270\u12ed\u12de\u120d\u1203\u120d \U0001f64f" confirmation \u1208 user (reply-to \u12a6\u122d\u1305\u1293\u120d message)
        numbers_label = " ".join(assigned)
        try:
            await msg.reply_to_message.reply_text(f"{numbers_label} \u1270\u12ed\u12de\u120d\u1203\u120d \U0001f64f")
        except Exception as e:
            logging.warning(f"[Eshi] confirmation reply error: {e}")

        if errors:
            await _send_temp_admin_message(ctx.bot, group_id, f"\u274c \u12eb\u120d\u1270\u1308\u1298: {', '.join(errors)}")

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _refresh_board(ctx, fresh, group_id)
        return

    # ============================================================
    # OWNER REASSIGNMENT \u2014 "#/ NUM NUM+SLOT" \u1265\u127b (\u1235\u120b\u123d \u12a0\u1208\u12cd)\u1363 active
    # game \u12eb\u1235\u1348\u120d\u1308\u12cb\u120d (total_numbers \u121b\u1228\u130b\u1308\u1325 \u1235\u120b\u1208\u1260\u1275)
    # ============================================================
    settings = get_active_settings(group_id=group_id)
    if not settings:
        return
    game_id = settings["id"]

    parts = text[2:].strip().split()
    if not parts:
        await msg.reply_text("\u274c \u121d\u1233\u120c: #/ 01 21 31+1")
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
        reply_lines.append(f"\u2705 {', '.join(assigned)} \u2192 \u1263\u1208\u1264\u1275 \u1270\u1235\u1270\u12ab\u12ad\u120f\u120d!")
    if errors:
        reply_lines.append(f"\u274c \u12eb\u120d\u1270\u1308\u1298: {', '.join(errors)}")

    if assigned:
        # \u2705 \u1270\u1240\u1263\u12ed\u1290\u1275 \u1235\u120b\u1308\u1298 (\u1262\u12eb\u1295\u1235 \u12a0\u1295\u12f5 \u1241\u1325\u122d \u1235\u1208\u1270\u1235\u1270\u12ab\u12a8\u1208) admin's own
        # "#/ ..." message \u12ed\u1320\u134b\u120d \u2014 \u120d\u12ad \u12a5\u1295\u12f0 board reply
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=msg.message_id)
        except Exception:
            pass
        if reply_lines:
            # FIX #4: admin confirmation message \u12a81.5-2 \u1230\u12a8\u1295\u12f5 \u1260\u128b\u120b \u122b\u1231 \u12ed\u1320\u134b\u120d
            await _send_temp_admin_message(ctx.bot, group_id, "\n".join(reply_lines))
    elif reply_lines:
        # \u121d\u1295\u121d \u12ab\u120d\u1270\u1235\u1270\u12ab\u12a8\u1208 message \u12a5\u1295\u12f3\u1208 \u12ed\u1246\u12eb\u120d (admin \u121d\u1295 \u12a5\u1295\u12f0\u133b\u1348 \u12a5\u1295\u12f2\u12eb\u12ed)
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
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /remove 5  \u12c8\u12ed\u121d  /remove 5:1 10 15:2  \u12c8\u12ed\u121d  5+1 15+2")
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
                # \u2705 FIX: NUM+SLOT (\u1208\u121d\u1233\u120c 5+1 \u12c8\u12ed\u121d 5+2) \u2014 \u120d\u12ad \u12a5\u1295\u12f0 /nekay slot \u1218\u1208\u12eb
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = None
            # \u2705 FIX: 1-5 \u1261\u12f5\u1295 \u1262\u1206\u1295 (numbers_per_person>1)\u1363 group start \u12ed\u1206\u1293\u120d
            actual_num = get_group_start(number, per_person) if per_person > 1 else number
            admin_remove_player(settings["id"], actual_num, slot)
            label = f"{format_number(actual_num)}:{slot}" if slot else format_number(actual_num)
            removed.append(label)
        except ValueError:
            errors.append(part)

    # \u2705 FIX: duplicate board \u2014 _check_all_paid_and_resend \u12a5\u12da\u1205 \u1218\u1320\u122b\u1275
    # \u12e8\u1208\u1260\u1275\u121d \u1290\u1260\u122d (\u121b\u1235\u12c8\u1308\u12f5 \u12cd\u1324\u1275 "\u1201\u1209\u121d \u1270\u12a8\u134d\u120f\u120d" \u1348\u133d\u121e \u121b\u121d\u1323\u1275 \u1235\u1208\u121b\u12ed\u127d\u120d\u1363 \u12eb\u1295\u1295
    # \u12ed\u1205 function \u122b\u1231 \u12ab\u1235\u1348\u1208\u1308 resend \u1235\u1208\u121a\u12eb\u12f0\u122d\u130d \u12a8 _refresh_board's edit \u130b\u122d
    # \u130d\u132d\u1275 \u12cd\u1235\u1325 \u1308\u1265\u1276 2 board messages \u12ed\u1348\u1325\u122d \u1290\u1260\u122d)
    await _refresh_board(ctx, settings, group_id)

    msg = ""
    if removed:
        msg += f"\u2705 {', '.join(removed)} \u1270\u12c8\u1323!"
    if errors:
        msg += f"\n\u274c \u12eb\u120d\u1270\u1240\u1260\u1208: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_paid_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /paid 5 10 15  \u12c8\u12ed\u121d  /paid 5:2  \u12c8\u12ed\u121d  5+2")
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
                # \u2705 FIX: NUM+SLOT (\u1208\u121d\u1233\u120c 5+1 \u12c8\u12ed\u121d 5+2) \u2014 \u120d\u12ad \u12a5\u1295\u12f0 /nekay slot \u1218\u1208\u12eb
                num_str, slot_str = part.split("+", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = 1
            # \u2705 FIX: 1-5 \u1261\u12f5\u1295 \u1262\u1206\u1295 (numbers_per_person>1)\u1363 group start \u12ed\u1206\u1293\u120d
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

    mark = "\u2705" if is_paid else "\u274c"
    updated_str = ", ".join(f"{format_number(n)}:{s}" for n, s in updated)
    msg = f"{mark} {updated_str} updated!"
    if errors:
        msg += f"\n\u274c \u12eb\u120d\u1270\u1240\u1260\u1208: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
        return

    # pre-booking mode \u2014 registrations \u1240\u12f5\u121e \u12a0\u1209\u1363 board \u1265\u127b \u12ed\u120b\u12ad
    if group_id in prebooking_groups:
        prebooking_groups.discard(group_id)
        clear_prize_balance(group_id)

        # balance \u12ab\u1208\u12cd pre-booked registrations \u2705 \u12eb\u12f0\u122d\u130b\u1278\u12cb\u120d
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
        await update.message.reply_text("\u2705 \u12a0\u12f2\u1235 \u1328\u12cb\u1273 \u1270\u1300\u121d\u122f\u120d!")
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

    await update.message.reply_text("\u2705 \u12a0\u12f2\u1235 \u1328\u12cb\u1273 \u1270\u1300\u121d\u122f\u120d!")


async def handle_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 3:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /register 5 \u12a0\u1260\u1260  \u12c8\u12ed\u121d  /register 5 10 15+ \u12a0\u1260\u1260")
        return

    user_name = parts[-1]
    number_parts = parts[1:-1]

    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
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
            await update.message.reply_text(f"\u274c {', '.join(failed)} \u1240\u12f5\u121e \u1270\u12c8\u1235\u12f7\u120d!")
        return

    await _refresh_board(ctx, settings, group_id)

    fresh = get_active_settings(group_id=group_id)
    if fresh:
        await _check_all_paid_and_resend(ctx.bot, fresh, group_id)

    reg_list = ", ".join(format_number(n) + ("+" if h else "") for n, h in registered)
    msg = f"\u2705 {reg_list} \u2192 {user_name} \u1270\u1218\u12d8\u1308\u1260!"
    if failed:
        msg += f"\n\u274c {', '.join(failed)} \u1240\u12f5\u121e \u1270\u12c8\u1235\u12f7\u120d!"
    await update.message.reply_text(msg)


# ============================================================
# MULTI-GROUP COMMANDS
# ============================================================

async def handle_enable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            gname = update.effective_chat.title or str(gid)
            enable_group(gid, gname)
            await update.message.reply_text(f"\u2705 Group {gname} enabled!")
            return
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /enable -100123456789")
        return

    try:
        gid = int(parts[1])
        enable_group(gid)
        await update.message.reply_text(f"\u2705 Group {gid} enabled!")
    except ValueError:
        await update.message.reply_text("\u274c Group ID \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


async def handle_disable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        if update.effective_chat.type != "private":
            gid = update.effective_chat.id
            disable_group(gid)
            await update.message.reply_text(f"\u2705 Group {gid} disabled!")
            return
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /disable -100123456789")
        return

    try:
        gid = int(parts[1])
        disable_group(gid)
        await update.message.reply_text(f"\u2705 Group {gid} disabled!")
    except ValueError:
        await update.message.reply_text("\u274c Group ID \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


async def handle_enablelist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    groups = get_enabled_groups()
    if not groups:
        await update.message.reply_text("\U0001f4cb Enabled group \u12e8\u1208\u121d\u1362")
        return

    lines = ["\U0001f4cb Enabled Groups:\n"]
    for i, g in enumerate(groups, 1):
        name = g["group_name"] or "Unknown"
        enabled_at = g["enabled_at"].strftime("%Y-%m-%d %H:%M") if g["enabled_at"] else "?"
        lines.append(f"{i}. {name}\n   ID: {g['group_id']}\n   Enabled: {enabled_at}")

    await update.message.reply_text("\n\n".join(lines))


async def handle_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /addadmin 123456789")
        return

    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("\u274c Group ID \u12eb\u1235\u1348\u120d\u130b\u120d: /addadmin USER_ID GROUP_ID")
            return
        add_group_admin(gid, admin_id)
        await update.message.reply_text(f"\u2705 {admin_id} group admin \u1206\u1297\u120d!")
    except (ValueError, IndexError):
        await update.message.reply_text("\u274c \u1275\u12ad\u12ad\u1208\u129b ID \u133b\u134d!")


async def handle_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /removeadmin 123456789")
        return
    try:
        admin_id = int(parts[1])
        gid = update.effective_chat.id if update.effective_chat.type != "private" else (
            int(parts[2]) if len(parts) > 2 else None
        )
        if not gid:
            await update.message.reply_text("\u274c Group ID \u12eb\u1235\u1348\u120d\u130b\u120d")
            return
        remove_group_admin(gid, admin_id)
        await update.message.reply_text(f"\u2705 {admin_id} admin \u1270\u12c8\u1323!")
    except ValueError:
        await update.message.reply_text("\u274c \u1275\u12ad\u12ad\u1208\u129b ID \u133b\u134d!")


async def handle_userlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return

    if not group_id:
        await update.message.reply_text("\u274c Group \u12cd\u1235\u1325 \u1265\u127b \u12ed\u1230\u122b\u120d!")
        return

    users = get_usernames(group_id)
    if not users:
        await update.message.reply_text("\U0001f4cb Username \u12e8\u1208\u121d\u1362")
        return

    lines = [f"\U0001f465 Members ({len(users)} total):\n"]
    for u in users:
        badge = "\U0001f195" if not u["is_read"] else "  "
        lines.append(f"{badge} @{u['username']}")

    await update.message.reply_text("\n".join(lines))
    mark_usernames_read(group_id)


async def handle_clearusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return
    if not group_id:
        await update.message.reply_text("\u274c Group \u12cd\u1235\u1325 \u1265\u127b \u12ed\u1230\u122b\u120d!")
        return
    clear_usernames(group_id)
    await update.message.reply_text("\u2705 Username list \u1338\u12f3!")


async def handle_activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    activities = get_activity()
    if not activities:
        await update.message.reply_text("\U0001f4ca Activity data \u12e8\u1208\u121d\u1362")
        return

    lines = ["\U0001f4ca Group Activity:\n"]
    for a in activities:
        name = a.get("group_name") or str(a["group_id"])
        last = a["last_active"].strftime("%m/%d %H:%M") if a["last_active"] else "?"
        lines.append(
            f"\U0001f4cc {name}\n"
            f"   \U0001f4ac Messages: {a['messages'] or 0}\n"
            f"   \U0001f4dd Registrations: {a['registrations'] or 0}\n"
            f"   \U0001f4b0 Payments: {a['payments'] or 0}\n"
            f"   \U0001f550 Last active: {last}"
        )

    await update.message.reply_text("\n\n".join(lines))


async def handle_dbstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    statuses = get_db_status()
    lines = ["\U0001f5c4\ufe0f Database Status:\n"]
    for s in statuses:
        if s.get("error"):
            lines.append(f"DB{s['index']}: \u274c Error")
            continue
        active = "\U0001f7e2 ACTIVE" if s["is_active"] else ("\U0001f534 FULL" if s["is_full"] else "\u26aa Standby")
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
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /dbclear 2  (DB2 \u12eb\u1338\u12f3\u120d)")
        return

    try:
        db_num = int(parts[1])
        clear_db_data(db_num)
        await update.message.reply_text(f"\u2705 DB{db_num} \u1338\u12f3! (usernames \u12ed\u1240\u122b\u1209)")
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


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
            await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
            return

    winners = get_recent_winners(group_id, hours=24)

    if not winners:
        await update.message.reply_text("\U0001f3c6 Last 24hr winners \u12e8\u1209\u121d\u1362")
        return

    medals = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}
    lines = ["\U0001f3c6 Last 24hr Winners:\n"]
    for w in winners:
        medal = medals.get(w["place"], "\U0001f396\ufe0f")
        balance = w["balance"]
        sent_mark = "\u2705" if w["sent"] else "\u26a0\ufe0f \u12eb\u120d\u1270\u120b\u12a8"
        time_str = w["created_at"].strftime("%H:%M") if w["created_at"] else "?"
        line = f"{medal} {w['place']}\u129b: {w['user_name']} \u2014 ETB {w['prize']} {sent_mark}"
        if balance > 0:
            line += f"\n   \U0001f4b3 \u1240\u122a balance: ETB {balance}"
        line += f"\n   \U0001f550 {time_str}"
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
    await update.message.reply_text("\u2705 Bot on \u1206\u1297\u120d!")


async def handle_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    set_group_active(group_id, False)
    await update.message.reply_text("\U0001f534 Bot off \u1206\u1297\u120d!")


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
            await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
            return

    parts = update.message.text.strip().split()

    if len(parts) == 1:
        clear_balance_all(group_id)
        await update.message.reply_text("\u2705 \u1201\u1209\u121d balance \u1338\u12f3!")
    else:
        username = parts[1].lstrip("@")
        success = clear_balance_by_username(group_id, username)
        if success:
            await update.message.reply_text(f"\u2705 @{username} balance \u1338\u12f3!")
        else:
            await update.message.reply_text(f"\u274c @{username} \u12a0\u120d\u1270\u1308\u1298\u121d!")


async def handle_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
        return

    report = get_report(group_id)
    lines = ["\U0001f4ca Report (Last 24hr)\n"]

    if report["games_count"] > 0:
        lines.append(
            f"\U0001f3ae \u1328\u12cb\u1273\u12ce\u127d: {report['games_count']}\n"
            f"\U0001f4b0 Total bet: ETB {report['total_bet']:,.0f}\n"
            f"\U0001f3c6 Prize total: ETB {report['prize_total']:,.0f}\n"
            f"\U0001f4c8 Profit: ETB {report['profit']:,.0f}"
        )
    else:
        lines.append("\U0001f3ae \u12db\u122c \u1328\u12cb\u1273 \u12a0\u120d\u1270\u132b\u12c8\u1270\u121d")

    active = report.get("active")
    if active:
        lines.append("\n\u26a1 Active Game (Real-time)")
        lines.append(f"\U0001f4dd Registered: {active['total_slots']}")
        if active["counted"]:
            lines.append(
                f"\U0001f4b0 Total bet: ETB {active['total_bet']:,.0f}\n"
                f"\U0001f3c6 Prize: ETB {active['prize_total']:,.0f}\n"
                f"\U0001f4c8 Profit: ETB {active['profit']:,.0f}"
            )
        else:
            lines.append(f"\u26a0\ufe0f 15+ \u1232\u1206\u1295 profit \u12ed\u1273\u12eb\u120d ({active['total_slots']}/15)")

    await update.message.reply_text("\n".join(lines))

    try:
        cleanup_old_reports()
    except Exception:
        pass


async def handle_setwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("\u274c Main admin \u1265\u127b \u1290\u12cd!")
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            "\u274c \u121d\u1233\u120c: /setwarnmedia 2\n"
            "\u12a8\u12db photo/video/sticker \u12ed\u120b\u12a9\n"
            "Available: 0.5, 1, 2, 3, 5, 10 \u12f0\u1242\u1243"
        )
        return

    try:
        mins = float(parts[1])
        if mins < 0.5 or mins > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("\u274c 0.5 \u12a5\u1235\u12a8 10 \u1265\u127b!")
        return

    ctx.user_data["setwarn_minutes"] = mins
    await update.message.reply_text(
        f"\u2705 {mins} \u12f0\u1242\u1243 \u1270\u12d8\u130b\u1305\u1277\u120d!\n"
        f"\u12a0\u1201\u1295 photo/video/sticker/gif \u12ed\u120b\u12a9"
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
    await msg.reply_text(f"\u2705 {mins} \u12f0\u1242\u1243 warning media \u1270\u1240\u121d\u1327\u120d! ({media_type})")


async def handle_listwarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    medias = get_all_warning_media()
    if not medias:
        await update.message.reply_text("\U0001f4cb Warning media \u12e8\u1208\u121d\u1362")
        return

    lines = ["\U0001f4cb Warning Media:\n"]
    for m in medias:
        lines.append(f"\u23f1\ufe0f {m['minutes']} \u12f0\u1242\u1243 \u2014 {m['media_type']}")

    await update.message.reply_text("\n".join(lines))


async def handle_deletewarnmedia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_main_admin(update.effective_user.id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("\u274c \u121d\u1233\u120c: /deletewarnmedia 2")
        return

    try:
        mins = float(parts[1])
        delete_warning_media(mins)
        await update.message.reply_text(f"\u2705 {mins} \u12f0\u1242\u1243 warning media \u1320\u134b!")
    except ValueError:
        await update.message.reply_text("\u274c \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")


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
            # \u2705 used \u134e\u1276 \u12a8\u1206\u1290 (\u1240\u12f5\u121e real winner \u12a0\u121d\u1325\u1276 \u12e8\u1290\u1260\u1228) AI \u1328\u122d\u1236 \u12a0\u1295\u1320\u122b\u121d
            if photo_uid in handled_winner_photos or is_winner_photo_used(photo_uid):
                return

            winner_found = await handle_winner_photo(ctx.bot, update.message, settings, group_id=group_id)
            if winner_found:
                # \u2705 winner \u1232\u1308\u129d \u1265\u127b \u1290\u12cd "used" \u12e8\u121a\u12f0\u1228\u1308\u12cd \u2014 not-lottery/failed \u134e\u1276
                # \u12f5\u130b\u121a \u1218\u120b\u12ad \u1262\u127b\u120d (retry) \u12a5\u1295\u12f2\u1296\u122d used \u12a0\u12ed\u12f0\u1228\u130d\u121d
                handled_winner_photos.add(photo_uid)
                save_winner_photo(photo_uid, group_id=group_id)
                # announcement \u12c8\u12f2\u12eb\u12cd\u1291 \u1270\u120b\u12a8 \u2014 board 30 seconds \u1246\u12ed\u1276 \u12ed\u121d\u1323
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
                # FIX: \u1218\u1300\u1218\u122a\u12eb \u12a5\u1295\u12f0\u1270\u133b\u1348\u12cd \u12c8\u12f2\u12eb\u12cd\u1291 \u12ed\u1218\u12d8\u1308\u1263\u120d\u1363 \u1325\u12eb\u1244\u12cd \u12a8\u12da\u12eb \u1260\u128b\u120b \u1265\u127b
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)
                if ambiguous == "all_half":
                    await q_msg.reply_text("\u1201\u1209\u1295\u121d \u1260\u130d\u121b\u123d \u1290\u12cd? (\u12a0\u12ce/\u12a0\u12ed\u12f0\u1208\u121d)")
                elif ambiguous == "last_half":
                    await q_msg.reply_text(f"{format_number(ambiguous_number)} \u1265\u127b \u1260\u130d\u121b\u123d \u1290\u12cd? (\u12a0\u12ce/\u12a0\u12ed\u12f0\u1208\u121d)")
            else:
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)

        fresh = get_active_settings(group_id=group_id)
        if fresh:
            await _check_all_paid_and_resend(ctx.bot, fresh, group_id)


# ============================================================
# DAILY PROFIT: \u1328\u12cb\u1273\u12cd \u12ab\u1208\u1240 (\u1201\u1209\u121d \u2705 \u1206\u1290\u12cd) \u1260\u128b\u120b admin \u1260 /setgame \u120b\u12ed
# \u12ab\u1235\u1308\u1263\u12cd profit_per_game (\u124b\u121a \u1241\u1325\u122d) \u12cd\u132a \u121d\u1295\u121d \u1235\u120c\u1275 \u12a0\u12ed\u12f0\u1228\u130d\u121d\u1362 1 \u1328\u12cb\u1273 = 1 \u130a\u12dc
# profit_per_game \u12ed\u12f0\u1218\u122b\u120d\u1362 \u1275\u122a\u1308\u122d \u1201\u1208\u1275 \u1266\u1273 \u1290\u12cd (\u12e8\u1275\u129b\u12cd\u121d \u1218\u1300\u1218\u122a\u12eb \u1262\u12f0\u122d\u1235)\u1366
#   1) \u1201\u1209\u121d \u2705 \u1206\u1290\u12cd live/pre-booking \u1232\u1300\u121d\u122d (handle_video_chat_started)
#   2) Live \u12ab\u120d\u1270\u1320\u1240\u1219\u1363 \u1201\u1209\u121d \u2705 \u1206\u1290\u12cd \u12cd\u1324\u1275 (winner photo) \u1232\u120b\u12ad (_auto_newgame)
# profit_counted_games (in-memory set) \u1270\u1218\u1233\u1233\u12ed game_id \u12f5\u130b\u121a \u12a5\u1295\u12f3\u12ed\u1246\u1320\u122d \u12ed\u1320\u1265\u1243\u120d\u1362
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

    # pre-booking mode \u2014 registrations \u1240\u12f5\u121e \u12a0\u1209\u1363 board \u1265\u127b \u12ed\u120b\u12ad
    if _group_id in prebooking_groups:
        prebooking_groups.discard(_group_id)
        clear_prize_balance(_group_id)

        # balance \u12ab\u1208\u12cd pre-booked registrations \u2705 \u12eb\u12f0\u122d\u130b\u1278\u12cb\u120d
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
        await update.message.reply_text("\u274c Private chat \u1265\u127b \u1290\u12cd!")
        return ConversationHandler.END

    user_id = update.effective_user.id
    group_id = get_admin_group_id(user_id)
    if not group_id:
        await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
        return ConversationHandler.END

    ctx.user_data["send_group_id"] = group_id
    return await _send_show_places(update, ctx, group_id)


async def _send_show_places(update, ctx, group_id: int):
    settings = get_active_settings(group_id=group_id)
    if not settings:
        await update.message.reply_text("\u274c Active game \u12e8\u1208\u121d!")
        return ConversationHandler.END

    ctx.user_data["send_settings"] = settings

    prize_1st = settings.get("prize_1st", 0)
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")

    lines = ["\U0001f4b8 \u1208\u121b\u1295 \u1265\u122d \u1275\u120d\u12ab\u1208\u1205?"]
    lines.append(f"1 \u2014 1\u129b winner (prize: {prize_1st} \u1265\u122d)")
    if prize_2nd:
        lines.append(f"2 \u2014 2\u129b winner (prize: {prize_2nd} \u1265\u122d)")
    if prize_3rd:
        lines.append(f"3 \u2014 3\u129b winner (prize: {prize_3rd} \u1265\u122d)")
    lines.append("\n(1, 2, \u12c8\u12ed\u121d 3 \u133b\u134d)")

    await update.message.reply_text("\n".join(lines))
    return ASK_SEND_PLACE


async def send_ask_place(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text not in ("1", "2", "3"):
        await update.message.reply_text("\u274c 1, 2, \u12c8\u12ed\u121d 3 \u1265\u127b \u133b\u134d!")
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
        await update.message.reply_text(f"\u274c {place}\u129b winner \u12a0\u120d\u1270\u1218\u12d8\u1308\u1260\u121d!")
        return ConversationHandler.END

    ctx.user_data["send_place"] = place
    ctx.user_data["send_game_id"] = settings["id"]

    if len(winners) == 1:
        winner = winners[0]
        ctx.user_data["send_telegram_id"] = winner["telegram_id"]
        ctx.user_data["send_user_name"] = winner["user_name"]

        balance = winner.get("balance", 0)
        await update.message.reply_text(
            f"\U0001f464 {place}\u129b: {winner['user_name']}\n"
            f"\U0001f4b3 \u12a0\u1201\u1295 balance: ETB {balance}\n\n"
            f"\U0001f4b8 \u1235\u1295\u1275 \u1265\u122d \u120b\u12ab\u1205? (\u1241\u1325\u122d \u133b\u134d)"
        )
        return ASK_SEND_AMOUNT

    ctx.user_data["send_winners_list"] = winners
    lines = [f"\u26a0\ufe0f {place}\u129b \u1266\u1273 \u120b\u12ed {len(winners)} \u1230\u12cd \u12a0\u1208 (tie)\u1366\n"]
    for i, w in enumerate(winners, 1):
        bal = w.get("balance", 0)
        lines.append(f"{i}. {w['user_name']} (balance: ETB {bal})")
    lines.append("\n\u121b\u1295\u1295 \u1275\u120d\u12ab\u1208\u1205? \u1241\u1325\u122d \u133b\u134d (1, 2, ...)")
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
        await update.message.reply_text(f"\u274c 1 \u12a5\u1235\u12a8 {len(winners)} \u1241\u1325\u122d \u1265\u127b \u133b\u134d!")
        return ASK_SEND_WINNER

    winner = winners[idx - 1]
    place = ctx.user_data.get("send_place")
    ctx.user_data["send_telegram_id"] = winner["telegram_id"]
    ctx.user_data["send_user_name"] = winner["user_name"]

    balance = winner.get("balance", 0)
    await update.message.reply_text(
        f"\U0001f464 {place}\u129b: {winner['user_name']}\n"
        f"\U0001f4b3 \u12a0\u1201\u1295 balance: ETB {balance}\n\n"
        f"\U0001f4b8 \u1235\u1295\u1275 \u1265\u122d \u120b\u12ab\u1205? (\u1241\u1325\u122d \u133b\u134d)"
    )
    return ASK_SEND_AMOUNT


async def send_ask_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("\u274c \u1275\u12ad\u12ad\u1208\u129b \u1241\u1325\u122d \u133b\u134d!")
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

    place_label = {1: "1\u129b", 2: "2\u129b", 3: "3\u129b"}.get(place, f"{place}\u129b")

    lines = [
        f"\u2705 {place_label} winner: {user_name}",
        f"\U0001f4b8 \u12e8\u120b\u12ab\u1205: ETB {amount}",
        f"\U0001f4b3 \u1240\u122a balance: ETB {new_balance}",
    ]
    await update.message.reply_text("\n".join(lines))

    if group_id:
        try:
            announcement = (
                f"\U0001f4b8 {place_label} winner \u1265\u122d \u1270\u120b\u12a8!\n"
                f"\U0001f464 {user_name}\n"
                f"\U0001f4b0 ETB {amount}"
            )
            await ctx.bot.send_message(chat_id=group_id, text=announcement)
        except Exception:
            pass

    settings = ctx.user_data.get("send_settings")
    if settings:
        await _refresh_board(ctx, settings, group_id)

    return ConversationHandler.END


async def cancel_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\u274c /send \u1270\u1230\u122d\u12df\u120d\u1362")
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
            await update.message.reply_text("\u274c Admin \u12e8\u1206\u1295\u12ad\u1260\u1275 group \u12e8\u1208\u121d!")
            return

    is_main = is_main_admin(user_id)

    text = (
        "\U0001f916 Commands:\n\n"
        "\U0001f3ae *Game*\n"
        "/setgame \u2014 \u12a0\u12f2\u1235 game settings \u12eb\u1240\u1293\u1265\u122b\u120d\n"
        "/newgame \u2014 \u1241\u1325\u122e\u127d\u1295 \u1320\u122d\u130e \u12a0\u12f2\u1235 \u1328\u12cb\u1273 \u12ed\u1300\u121d\u122b\u120d\n"
        "/setcountdown 2 \u2014 countdown \u12f0\u1242\u1243 \u12ed\u1240\u12ed\u122b\u120d (0=\u12a0\u1325\u134b)\n"
        "/showslots on/off \u2014 sub-slots \u120b\u12ed \u1235\u121d \u12eb\u1233\u12eb\u120d/\u12eb\u1320\u134b\u120d\n"
        "/nekay 5 10+ 15 \u2014 manually \u1290\u1243\u12ed \u12eb\u12f0\u122d\u130b\u120d\n"
        "/status \u2014 \u1201\u1209\u1295\u121d commands \u12eb\u1233\u12eb\u120d\n\n"
        "\U0001f464 *\u121d\u12dd\u1308\u1263*\n"
        "/register 5 10+ \u12a0\u1260\u1260 \u2014 \u1241\u1325\u122d manually \u12ed\u1218\u12d8\u130d\u1263\u120d\n"
        "  \u2022 + = \u130d\u121b\u123d (\u1208\u121d\u1233\u120c 5+)\n\n"
        "\U0001f4b0 *\u12ad\u134d\u12eb*\n"
        "/paid 5 10 15 \u2014 \u1265\u12d9 \u1241\u1325\u122e\u127d paid \u12eb\u12f0\u122d\u130b\u120d\n"
        "/paid 5:2 \u2014 slot 2 paid \u12eb\u12f0\u122d\u130b\u120d\n"
        "/unpaid 5 10 \u2014 \u1265\u12d9 \u1241\u1325\u122e\u127d unpaid \u12eb\u12f0\u122d\u130b\u120d\n\n"
        "\U0001f5d1\ufe0f *\u12a0\u1235\u1270\u12f3\u12f0\u122d*\n"
        "/remove 5 \u2014 \u1241\u1325\u122d \u12a8 board \u12eb\u1235\u12c8\u1323\u120d\n"
        "/remove 5:1 \u2014 slot 1 \u1265\u127b \u12eb\u1235\u12c8\u1323\u120d\n"
        "/on \u2014 Bot \u12eb\u1235\u1290\u1233\u120d\n"
        "/off \u2014 Bot \u12eb\u1246\u121b\u120d\n"
        "/clearbalance \u2014 \u1201\u1209\u121d balance \u12eb\u1338\u12f3\u120d\n"
        "/clearbalance @username \u2014 \u12a0\u1295\u12f5 user balance \u12eb\u1338\u12f3\u120d\n\n"
        "\U0001f465 *Members*\n"
        "/userlist \u2014 username \u12dd\u122d\u12dd\u122d\n"
        "/clearusers \u2014 username list \u12eb\u1338\u12f3\u120d\n\n"
        "\U0001f4ca *Report*\n"
        "/report \u2014 real-time profit + games (last 24hr)\n\n"
        "\U0001f3c6 *Winner*\n"
        "/winners \u2014 last 24hr winners\n"
        "/send \u2014 winner \u1265\u122d \u12ed\u120b\u12ab\u120d (private chat \u1265\u127b)\n\n"
        "\U0001f4b8 *Winner Auto-Sender (userbot2)*\n"
        "/setwinnerapi api_id api_hash \u2014 winner API \u12eb\u1235\u1240\u121d\u1323\u120d (main admin)\n"
        "/startsession2 +phone \u2014 winner session \u12ed\u1300\u121d\u122b\u120d (private chat)\n"
        "/verifycode2 +phone code \u2014 session \u12eb\u1228\u130b\u130d\u1323\u120d\n"
        "/verify2fa2 +phone password \u2014 2FA \u12ab\u1208\n"
        "/listsessions2 \u2014 group \u12ed\u1205 sessions \u12dd\u122d\u12dd\u122d\n"
        "/removesession2 +phone \u2014 session \u12eb\u1235\u12c8\u130d\u12f3\u120d\n\n"
        "\u270f\ufe0f *Manual Board Edit*\n"
        "Board copy \u12a0\u122d\u130e edit \u12a0\u122d\u130e bot message \u120b\u12ed reply \u12a0\u122d\u130d\n"
        "Bot automatically \u12ed\u1240\u12ed\u1228\u12cb\u120d!\n"
    )

    if is_main:
        text += (
            "\n\U0001f527 *Main Admin*\n"
            "/enable \u2014 group \u12eb\u1235\u1290\u1233\u120d\n"
            "/disable \u2014 group \u12eb\u1320\u134b\u120d\n"
            "/enablelist \u2014 enabled groups \u12dd\u122d\u12dd\u122d\n"
            "/addadmin USER_ID \u2014 group admin \u12ed\u1328\u121d\u122b\u120d\n"
            "/removeadmin USER_ID \u2014 group admin \u12eb\u1235\u12c8\u1323\u120d\n"
            "/activity \u2014 group activity \u12eb\u1233\u12eb\u120d\n"
            "/dbstatus \u2014 DB status \u12eb\u1233\u12eb\u120d\n"
            "/dbclear N \u2014 DBN \u12eb\u1338\u12f3\u120d (username \u1233\u12ed\u1290\u12ab)\n"
            "/setwarnmedia 2 \u2014 warning media \u12eb\u1235\u1240\u121d\u1323\u120d\n"
            "/listwarnmedia \u2014 warning media \u12dd\u122d\u12dd\u122d\n"
            "/deletewarnmedia 2 \u2014 warning media \u12eb\u1338\u12f3\u120d\n"
            "/setcompletesticker \u2014 \u1201\u1209\u121d \u2705 \u1232\u1206\u1295 sticker \u12eb\u1235\u1240\u121d\u1323\u120d\n"
            "/listcompletestickers \u2014 complete stickers \u12dd\u122d\u12dd\u122d\n"
            "/removecompletesticker N \u2014 sticker #N \u12eb\u1235\u12c8\u1323\u120d\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

async def handle_admin_group_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin group \u120b\u12ed 30+ seconds video \u1232\u120d\u12ad \u2192 \u1240\u12f0\u121d \u12eb\u1208\u12cd\u1295 board \u12ed\u1230\u122d\u12db\u120d\u1363
    \u12a0\u12f2\u1231\u1295 board \u12a8\u1273\u127d \u12ed\u120b\u12ab\u120d (\u12a0\u1295\u12f5 \u130a\u12dc \u1265\u127b per game)
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

    # duration check \u2014 30 seconds+
    duration = getattr(video, "duration", None)
    if not duration or duration < 30:
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    game_id = settings["id"]

    # \u12a0\u1295\u12f5 \u130a\u12dc \u1265\u127b per game
    if _gk(group_id, game_id) in handled_video_boards:
        return
    handled_video_boards.add(_gk(group_id, game_id))

    # \u1240\u12f0\u121d \u12eb\u1208\u12cd\u1295 board \u12ed\u1230\u122d\u12dd
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
        except Exception:
            pass

    # \u12a0\u12f2\u1231\u1295 board \u12a8\u1273\u127d \u12ed\u120b\u12ad
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    new_msg = await ctx.bot.send_message(chat_id=group_id, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    logging.info(f"[VideoBoard] Group {group_id} game {game_id} board replaced after 30s+ video")


async def handle_video_chat_started(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin live \u1232\u1300\u121d\u122d + \u1201\u1209\u121d \u1241\u1325\u122e\u127d \u2705 \u12a8\u1206\u1291 \u2192 silent pre-booking mode \u12ed\u1300\u121d\u122d\u1362
    Board \u12a0\u12ed\u120b\u12ad\u121d\u1363 \u1230\u12ce\u127d \u1241\u1325\u122d \u1218\u12eb\u12dd \u12ed\u127d\u120b\u1209\u1363 /newgame \u1232\u120d board \u12ed\u1273\u12eb\u120d\u1362
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

    # FIX: daily profit \u2014 \u1201\u1209\u121d \u2705 \u1206\u1290\u12cd live \u1232\u1300\u121d\u122d 1 \u1328\u12cb\u1273 \u1270\u1265\u120e profit_per_game
    # \u12ed\u1218\u12d8\u1308\u1263\u120d (registrations \u12a8\u1218\u1325\u134b\u1273\u1278\u12cd \u1260\u134a\u1275)
    _maybe_record_game_profit(group_id, game_id, settings)

    # \u2705 FIX: registrations \u12a8\u1218\u1325\u134b\u1271 \u1260\u134a\u1275 snapshot \u12eb\u12f5\u122d\u130d \u2014 winner photo
    # \u1308\u1293 \u12cd\u1324\u1271 \u12ab\u120d\u1273\u12c8\u1240 (\u1308\u1293 admin \u12ab\u120d\u120b\u12a8\u12cd) \u1260\u134a\u1275 pre-booking \u1262\u1300\u121d\u122d\u1363 winner
    # lookup snapshot \u120b\u12ed \u1270\u1218\u120d\u12ad\u1276 \u1275\u12ad\u12ad\u1208\u129b\u12cd\u1295 \u1263\u1208\u1264\u1275 \u121b\u130d\u1298\u1275 \u12ed\u127d\u120b\u120d
    save_registrations_snapshot(game_id)

    # silently clear registrations only (game_settings row \u12ed\u1240\u122b\u120d)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations WHERE game_id=%s", (game_id,))
    cur.execute("DELETE FROM sms_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    cur.execute("DELETE FROM screenshot_payments WHERE matched=FALSE AND group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()

    # \u2705 \u12eb\u1208\u1240\u12cd \u1328\u12cb\u1273 carry_balance \u12a5\u12da\u1205 \u130b\u122d \u12ed\u1338\u12f3\u120d (\u12a5\u12cd\u1290\u1270\u129b\u12cd \u1328\u12cb\u1273 \u12eb\u1208\u1240\u1260\u1275 \u1266\u1273) \u2014
    # pre-booking round \u122b\u1231 \u1308\u1293 \u1235\u120b\u120d\u1300\u1218\u1228\u1363 \u12a8\u12da\u1205 \u1260\u128b\u120b \u12e8\u121a\u1308\u1263 \u1308\u1295\u12d8\u1265 \u1201\u1209 \u1208\u12a0\u12f2\u1231 \u12d9\u122d
    # \u1295\u1341\u1205 (\u12ab\u1208\u1348\u12cd \u1328\u12cb\u1273 \u1240\u122a \u1233\u12ed\u1240\u120b\u1240\u120d) \u12ed\u1206\u1293\u120d
    clear_carry_balance(group_id)

    # in-memory state reset
    nekay_active.discard(_gk(group_id, game_id))
    admin_nekay_games.discard(_gk(group_id, game_id))
    active_countdowns.pop(_gk(group_id, game_id), None)
    nekay_numbers.pop(_gk(group_id, game_id), None)
    countdown_done.discard(_gk(group_id, game_id))
    _stop_inactivity_tracker(game_id, group_id)

    # pre-booking mode \u12ed\u1300\u121d\u122d
    prebooking_groups.add(group_id)
    logging.info(f"[PreBooking] Group {group_id} entered pre-booking mode (live started, all paid)")

    # pre-booking media \u12ed\u120b\u12ab (sticker/photo/video announcement)
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

        # bot off \u1232\u1206\u1295 SMS \u121d\u1295\u121d \u12a0\u12eb\u1235\u12ac\u12f5
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
    return web.Response(text=f"\U0001f916 Bot is running!\n\U0001f550 Server time: {now}")


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
    print("\U0001f310 SMS Server started on port 8080")
    print("\U0001f4f1 SMS endpoint: /sms/{group_id}")


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
    # NEW: winner "\U0001f525 reaction" balance-clear feature
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

    # \u2705 FIX: \u12e8\u122b\u1231 group (-2) \u120b\u12ed \u1218\u1218\u12dd\u1308\u1265 \u12a0\u1208\u1260\u1275! python-telegram-bot \u1260\u12a0\u1295\u12f5
    # group \u12cd\u1235\u1325 \u12e8\u1218\u1300\u1218\u122a\u12eb\u12cd\u1295 filter-matching handler \u1265\u127b \u12ed\u1320\u122b\u120d \u2014 \u12ed\u1205
    # \u12a8 handle_winner_correction_reply \u130b\u122d \u1270\u1218\u1233\u1233\u12ed group (-1) \u12a5\u1293 \u1270\u1218\u1233\u1233\u12ed
    # filter \u1235\u1208\u1290\u1260\u1228\u12cd\u1363 \u1348\u133d\u121e \u12a0\u12ed\u1320\u122b\u121d \u1290\u1260\u122d (dead code)\u1362
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_owner_reply
    ), group=-2)

    # NEW: "\U0001f52516 21+" \u2192 \u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u121b\u12cd\u132b (\u12e8\u122b\u1231 group \u12eb\u1235\u1348\u120d\u1308\u12cb\u120d \u2014 \u12a8\u120b\u12ed \u12eb\u1209\u1275
    # handlers \u1201\u1209\u1295\u121d text \u1235\u1208\u121a\u12ed\u12d9)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & filters.Regex('^\\s*\U0001f525'),
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
                    lines = ["\U0001f4ca \u12e8\u12db\u122c Daily Report\n"]
                    if report["games_count"] > 0:
                        lines.append(
                            f"\U0001f3ae \u1328\u12cb\u1273\u12ce\u127d: {report['games_count']}\n"
                            f"\U0001f4b0 Total bet: ETB {report['total_bet']:,.0f}\n"
                            f"\U0001f3c6 Prize: ETB {report['prize_total']:,.0f}\n"
                            f"\U0001f4c8 Profit: ETB {report['profit']:,.0f}"
                        )
                    else:
                        lines.append("\U0001f3ae \u12db\u122c \u1328\u12cb\u1273 \u12a0\u120d\u1270\u132b\u12c8\u1270\u121d")
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
                # NEW: winner-\U0001f525-reaction feature \u2014 message_senders \u120b\u12ed \u12f0\u130d\u121e
                # \u12f0\u1205\u1295\u1290\u1275 (safety-net) periodic cleanup (clear_game \u122b\u1231 \u12a0\u12f2\u1235
                # game \u1232\u1300\u1218\u122d \u12eb group's records \u1262\u12eb\u1338\u12f3\u121d\u1363 \u12ed\u1204 \u1270\u1328\u121b\u122a \u1325\u1295\u1243\u1244 \u1290\u12cd)
                try:
                    cleanup_old_message_senders()
                except Exception:
                    pass
            except Exception as e:
                logging.warning(f"[Daily Report] Error: {e}")

    loop.create_task(_daily_report_scheduler())

    print("\U0001f916 Bot started!")
    # NEW: allowed_updates \u130d\u120d\u133d \u1270\u1265\u120e \u12ab\u120d\u1270\u1230\u1320 Telegram \u12e8\u12f5\u122e\u12cd\u1295 cached setting
    # \u1265\u127b \u12ed\u1320\u1240\u121b\u120d (message_reaction \u120b\u12ed\u12ab\u1270\u1275 \u12ed\u127d\u120b\u120d) \u2014 \u1235\u1208\u12da\u1205 winner-\U0001f525-reaction
    # feature \u12a5\u1295\u12f2\u1230\u122b Update.ALL_TYPES \u130d\u120d\u133d \u1270\u1265\u120e \u1270\u1230\u1325\u1277\u120d\u1362
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
