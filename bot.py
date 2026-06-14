import os
import logging
import asyncio
import time
import json
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from config import BOT_TOKEN, ADMIN_IDS, GROUP_ID
from database import (
    init_db, save_settings, get_active_settings,
    register_number, get_taken_numbers, get_paid_numbers,
    update_board_message_id, update_remaining_message_id,
    admin_remove_player, admin_mark_paid, mark_nekay,
    clear_game, get_unpaid_numbers,
    get_winner_by_place, deduct_winner_balance,
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
)
from parser import parse_numbers, format_number
from board import (
    build_board, build_remaining,
    count_remaining, get_group_start,
    build_warning, build_nekay
)
from handlers import handle_payment_photo, handle_sms_webhook, handle_winner_photo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
from responder import get_response, RESPONSES
import random

(
    ASK_TOTAL, ASK_PER_PERSON, ASK_PRICE_FULL,
    ASK_PRICE_HALF, ASK_PRIZE_1, ASK_PRIZE_2,
    ASK_PRIZE_3, ASK_PAYMENT, ASK_GAME_RULE,
    ASK_SLOT_SYMBOL, ASK_COUNTDOWN_ENABLED,
    ASK_COUNTDOWN_MINUTES,
    ASK_SEND_PLACE, ASK_SEND_AMOUNT
) = range(14)

pending_ambiguous = {}
active_countdowns = {}  # {game_id: {"task": Task, "start": float, "warn_secs": int}}
countdown_done = set()
nekay_active = set()
nekay_numbers = {}
msg_counter = {}

photo_processing = {}
pending_registrations = {}

handled_winner_photos = set()

low_remaining_trackers = {}

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

            if game_id not in low_remaining_trackers:
                return

            settings = get_active_settings(group_id=group_id)
            if not settings or settings["id"] != game_id:
                return

            taken = get_taken_numbers(game_id)
            remaining_count = count_remaining(settings, taken)
            is_nekay = game_id in nekay_active

            if game_id in active_countdowns:
                return

            if remaining_count == 0 and not is_nekay:
                return

            # ሰዓት check — ከምሽቱ 4 (10 PM) እስከ ጠዋቱ 2 (8 AM) አይላክም
            now_et = datetime.now(et_tz)
            hour = now_et.hour
            if hour >= 22 or hour < 8:
                continue

            # 4 ጊዜ ከላከ በኋላ ማንም ካልወሰደ ይሞታል
            if urgency_count >= MAX_COUNT:
                return

            # የቀደመውን urgency message ሰርዝ
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

            if game_id not in low_remaining_trackers:
                return

            settings = get_active_settings(group_id=group_id)
            if not settings or settings["id"] != game_id:
                return

            taken = get_taken_numbers(game_id)
            remaining_count = count_remaining(settings, taken)
            is_nekay = game_id in nekay_active

            if remaining_count == 0 and not is_nekay:
                return

            if is_nekay:
                snap = nekay_numbers.get(game_id, {})
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
        low_remaining_trackers.pop(game_id, None)


def _reset_inactivity_tracker(bot, game_id: int, group_id: int):
    existing = low_remaining_trackers.get(game_id)
    if existing and not existing["task"].done():
        existing["task"].cancel()
    task = asyncio.create_task(_inactivity_notify_task(bot, game_id, group_id))
    low_remaining_trackers[game_id] = {"task": task, "group_id": group_id}



def _stop_inactivity_tracker(game_id: int):
    existing = low_remaining_trackers.pop(game_id, None)
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


# ============================================================
# NEKAY PAYMENT CALLBACK
# ============================================================

async def nekay_payment_cb(bot, game_id: int, telegram_id: int, confirmed: list):
    if game_id not in nekay_active:
        return

    snap = nekay_numbers.get(game_id, {})
    changed = False

    for c in confirmed:
        number = c["number"]
        if number in snap:
            del snap[number]
            changed = True

    if not changed:
        return

    nekay_numbers[game_id] = snap

    settings = get_active_settings()
    if not settings:
        return

    group_id = settings.get("group_id") or GROUP_ID
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
        except Exception:
            new_msg = await bot.send_message(chat_id=group_id, text=board_text)
            update_board_message_id(game_id, new_msg.message_id)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
        except Exception:
            pass

    if snap:
        nekay_list = _build_nekay_from_snap(snap)
        nekay_text = build_nekay(nekay_list)
        new_nekay = await bot.send_message(chat_id=group_id, text=nekay_text)
        update_remaining_message_id(game_id, new_nekay.message_id)
    else:
        update_remaining_message_id(game_id, None)
        nekay_active.discard(game_id)
        nekay_numbers.pop(game_id, None)
        _stop_inactivity_tracker(game_id)


def _increment_counter(group_id: int) -> bool:
    msg_counter[group_id] = msg_counter.get(group_id, 0) + 1
    if msg_counter[group_id] >= 4:
        msg_counter[group_id] = 0
        return True
    return False


def _build_nekay_from_snap(snap: dict) -> list:
    result = []
    for number, slot in sorted(snap.items()):
        is_half = (slot == 2)
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
        snap = {}
        for number, slots in unpaid:
            if slots == {1} or slots == {1, 2} or len(slots) == 0:
                snap[number] = 0
            elif slots == {2}:
                snap[number] = 2
            else:
                snap[number] = 0
        nekay_numbers[game_id] = snap

        for number, slots in unpaid:
            mark_nekay(game_id, number)

        nekay_list = _build_nekay_from_snap(snap)
        nekay_text = build_nekay(nekay_list)

        # FIX 4: warning message አይጠፋም — ነቃይ list አዲስ message ከታች ይላካል
        nekay_sent = await bot.send_message(chat_id=group_id, text=nekay_text)

        nekay_active.add(game_id)
        update_remaining_message_id(game_id, nekay_sent.message_id if nekay_sent else None)
    else:
        # unpaid የለም — warning message ይቀራል (አይጠፋም)
        pass

    active_countdowns.pop(game_id, None)


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
        return await _finish_setgame(update, ctx)


async def ask_countdown_minutes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        mins = float(update.message.text.strip())
        if mins < 0.5 or mins > 10:
            raise ValueError
        ctx.user_data["countdown_minutes"] = mins
    except ValueError:
        await update.message.reply_text("❌ 0.5 እስከ 10 ብቻ ጻፍ!")
        return ASK_COUNTDOWN_MINUTES
    return await _finish_setgame(update, ctx)


async def _finish_setgame(update, ctx):
    setup_group_id = ctx.user_data.get("setup_group_id")
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

    if get_ungreeted_winner(game_id, user_id):
        mark_winner_greeted(user_id)
        await msg.reply_text(random.choice(RESPONSES["winner_greeting"]))

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    snap = nekay_numbers.get(game_id, {})
    nekay_list = _build_nekay_from_snap(snap)
    remaining = count_remaining(settings, taken)

    cd_data = active_countdowns.get(game_id)
    if cd_data and isinstance(cd_data, dict):
        elapsed = time.time() - cd_data["start"]
        countdown_seconds = max(0, int(cd_data["warn_secs"] - elapsed))
    else:
        countdown_seconds = 0

    resp = get_response(
        text=text,
        settings=settings,
        taken=taken,
        paid=paid,
        nekay_list=nekay_list,
        remaining_count=remaining,
        countdown_seconds=countdown_seconds,
        user_name=user_name,
        user_id=user_id,
    )

    # Cancel number
    if resp.get("cancel_number"):
        num = resp["cancel_number"]
        if not user_owns_number(game_id, user_id, num):
            await msg.reply_text("ቁጥሩ የእርስዎ አይደለም 🙏")
            return
        removed = remove_number(game_id, user_id, num)
        if removed:
            if resp["reply"]:
                await msg.reply_text(resp["reply"])
            if game_id in nekay_numbers and num in nekay_numbers.get(game_id, {}):
                del nekay_numbers[game_id][num]
            fresh = get_active_settings(group_id=group_id)
            if fresh:
                await _refresh_board(ctx, fresh, group_id)
                if game_id in nekay_active:
                    snap2 = nekay_numbers.get(game_id, {})
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
                        nekay_active.discard(game_id)
                        nekay_numbers.pop(game_id, None)
        return

    # Type change
    if resp.get("type_change"):
        tc = resp["type_change"]
        target = tc["target"]
        numbers = tc["numbers"]

        # parsed_name ከ parse_numbers ይወስድ
        parse_result = parse_numbers(text)
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
                # parsed_name ካለ ስም update አርግ
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

            if game_id in nekay_active:
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
                        except Exception:
                            try:
                                await ctx.bot.delete_message(chat_id=group_id, message_id=fresh_board_msg_id)
                            except Exception:
                                pass
                            new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                            update_board_message_id(game_id, new_msg.message_id)
                    else:
                        new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                        update_board_message_id(game_id, new_msg.message_id)
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
                    except Exception:
                        new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                        update_board_message_id(game_id, new_msg.message_id)
                else:
                    new_msg = await ctx.bot.send_message(chat_id=group_id, text=fresh_board)
                    update_board_message_id(game_id, new_msg.message_id)

            if game_id in nekay_active:
                snap_fresh = nekay_numbers.get(game_id, {})
                for num in numbers:
                    actual_num = get_group_start(num, fresh["numbers_per_person"]) \
                        if fresh["numbers_per_person"] > 1 else num
                    if actual_num in snap_fresh:
                        if target == "half" and snap_fresh[actual_num] == 0:
                            snap_fresh[actual_num] = 2
                        elif target == "full":
                            del snap_fresh[actual_num]
                nekay_numbers[game_id] = snap_fresh

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
                    nekay_active.discard(game_id)
                    nekay_numbers.pop(game_id, None)
                    _stop_inactivity_tracker(game_id)
            else:
                if fresh_remaining <= 7:
                    await _send_remaining(ctx, fresh, group_id)
                    _reset_inactivity_tracker(ctx.bot, game_id, group_id)

                if fresh_remaining == 0 and game_id not in active_countdowns and game_id not in countdown_done:
                    _stop_inactivity_tracker(game_id)
                    countdown_enabled = fresh.get("countdown_enabled", True)
                    if countdown_enabled:
                        countdown_mins = fresh.get("countdown_minutes") or 2
                        warn_secs = int(float(countdown_mins) * 60)
                        task = asyncio.create_task(_countdown_task(ctx.bot, game_id, group_id, warn_seconds=warn_secs))
                        active_countdowns[game_id] = {"task": task, "start": time.time(), "warn_secs": warn_secs}
                        countdown_done.add(game_id)
        return

    # Change number
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
                if game_id in nekay_numbers:
                    snap3 = nekay_numbers.get(game_id, {})
                    if from_num in snap3:
                        del snap3[from_num]
                    nekay_numbers[game_id] = snap3
                fresh = get_active_settings(group_id=group_id)
                if fresh:
                    await _refresh_board(ctx, fresh, group_id)
            else:
                register_number(game_id, user_id, user_name, from_num, False)
                await msg.reply_text(f"{to_num:02d} አልተቻለም 🙏")
        return

    # Why not registered
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

    # Parse numbers
    parse_result = parse_numbers(text)

    if not parse_result:
        if resp["reply"]:
            await msg.reply_text(resp["reply"])
        if resp["resend_remaining"]:
            if game_id in nekay_active:
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
        if ambiguous == "all_half":
            await msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
        elif ambiguous == "last_half":
            await msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
        return

    if game_id in active_countdowns:
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

    if ambiguous == "all_half":
        if yes:
            numbers = [(n, True, nm) for n, _, nm in numbers]
    elif ambiguous == "last_half":
        if not yes:
            numbers = [(n, False, nm) for n, _, nm in numbers]

    del pending_ambiguous[user_id]
    await process_registration(ctx, settings, numbers, user_id, user_name, group_id, update.message)


async def process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg, skip_board_update=False):
    game_id = settings["id"]
    per_person = settings["numbers_per_person"]

    taken_before = get_taken_numbers(game_id)
    remaining_before = count_remaining(settings, taken_before)

    registered = []
    all_taken = []
    no_change_reply = False

    allow_toggle = (len(numbers) == 1)

    for num, is_half, parsed_name in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        if parsed_name:
            actual_name = parsed_name
        elif actual_num in taken_before:
            existing_slots = taken_before[actual_num]
            slot1 = next((s for s in existing_slots if s[2] == 1), None)
            if slot1 and slot1[0] != user_name and slot1[1]:  # ሌላ user + half
                actual_name = user_name
            else:
                actual_name = slot1[0] if slot1 else user_name
        else:
            actual_name = user_name

        if actual_num < 1 or actual_num > settings["total_numbers"]:
            all_taken.append(actual_num)
            continue

        is_nekay = game_id in nekay_numbers and actual_num in nekay_numbers.get(game_id, {})
        result = register_number(
            game_id, user_id, actual_name, actual_num, is_half,
            force=is_nekay, allow_toggle=allow_toggle,
            is_parsed_name=bool(parsed_name)
        )
        if result in ["registered", "registered_half"]:
            registered.append((actual_num, is_half))
        elif isinstance(result, dict) and result.get("status") == "ok":
            new_is_half = get_user_numbers(game_id, user_id)
            actual_is_half = is_half
            for n_num, n_half, n_slot, n_paid in new_is_half:
                if n_num == actual_num and n_slot == 1:
                    actual_is_half = n_half
                    break
            registered.append((actual_num, actual_is_half))
        elif isinstance(result, dict) and result.get("status") == "no_change":
            no_change_reply = True
        else:
            all_taken.append(actual_num)

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    remaining_count = count_remaining(settings, taken)
    snap = nekay_numbers.get(game_id, {})
    nekay_list = _build_nekay_from_snap(snap)

    if not registered and not all_taken and no_change_reply:
        await msg.reply_text("እሺ 🙏")
        return

    reg_result = "registered" if registered else ("taken" if all_taken else None)

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
    )

    if resp["reply"]:
        await msg.reply_text(resp["reply"])

    if not registered:
        return

    if skip_board_update:
        return

    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")

    should_resend = _increment_counter(group_id)

    crossed_into_low = (remaining_before > 7) and (remaining_count <= 7)
    if crossed_into_low and game_id not in nekay_active:
        should_resend = True

    if remaining_count > 7 and game_id not in nekay_active:
        should_resend = False

    if game_id in nekay_active:
        if should_resend:
            if board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                except Exception:
                    pass
            new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            update_board_message_id(game_id, new_board.message_id)
        else:
            if board_msg_id:
                try:
                    await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
                except Exception:
                    try:
                        await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                    except Exception:
                        pass
                    new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    update_board_message_id(game_id, new_board.message_id)
            else:
                new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                update_board_message_id(game_id, new_board.message_id)

        for num, is_half in registered:
            if num in snap:
                if is_half and snap[num] == 0:
                    snap[num] = 2
                else:
                    del snap[num]
        nekay_numbers[game_id] = snap

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
            update_remaining_message_id(game_id, new_nekay.message_id)
        else:
            update_remaining_message_id(game_id, None)
            nekay_active.discard(game_id)
            nekay_numbers.pop(game_id, None)
            _stop_inactivity_tracker(game_id)

        # ነቃይ ጊዜ ሰው ቁጥር ሲወስድ tracker reset
        _reset_inactivity_tracker(ctx.bot, game_id, group_id)

    elif remaining_count <= 7:
        if should_resend:
            if board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                except Exception:
                    pass
            new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            update_board_message_id(game_id, new_board.message_id)
        else:
            if board_msg_id:
                try:
                    await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
                except Exception:
                    new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    update_board_message_id(game_id, new_board.message_id)
        await _send_remaining(ctx, settings, group_id)
        _reset_inactivity_tracker(ctx.bot, game_id, group_id)

    else:
        if board_msg_id:
            try:
                await ctx.bot.edit_message_text(chat_id=group_id, message_id=board_msg_id, text=board_text)
            except Exception:
                new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                update_board_message_id(game_id, new_board.message_id)

    if remaining_count == 0 and game_id not in active_countdowns and game_id not in countdown_done:
        _stop_inactivity_tracker(game_id)
        countdown_enabled = settings.get("countdown_enabled", True)
        if countdown_enabled:
            countdown_mins = settings.get("countdown_minutes") or 2
            warn_secs = int(float(countdown_mins) * 60)
            task = asyncio.create_task(_countdown_task(ctx.bot, game_id, group_id, warn_seconds=warn_secs))
            active_countdowns[game_id] = {"task": task, "start": time.time(), "warn_secs": warn_secs}
            countdown_done.add(game_id)

    try:
        check_and_rotate_db()
    except Exception:
        pass
# ============================================================
# HELPERS
# ============================================================

async def _send_remaining(ctx, settings, group_id):
    game_id = settings["id"]
    taken = get_taken_numbers(game_id)
    remaining_text = build_remaining(settings, taken)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
        except Exception:
            pass

    if remaining_text:
        rem_msg = await ctx.bot.send_message(chat_id=group_id, text=remaining_text)
        update_remaining_message_id(game_id, rem_msg.message_id)
    else:
        update_remaining_message_id(game_id, None)


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
        except Exception:
            new_msg = await ctx.bot.send_message(chat_id=_group_id, text=board_text)
            update_board_message_id(game_id, new_msg.message_id)
    else:
        new_msg = await ctx.bot.send_message(chat_id=_group_id, text=board_text)
        update_board_message_id(game_id, new_msg.message_id)


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def handle_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /remove 5  ወይም  /remove 5:1 10 15:2")
        return

    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    removed = []
    errors = []

    for part in parts[1:]:
        try:
            if ":" in part:
                num_str, slot_str = part.split(":", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = None
            admin_remove_player(settings["id"], number, slot)
            label = f"{format_number(number)}:{slot}" if slot else format_number(number)
            removed.append(label)
        except ValueError:
            errors.append(part)

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
        await update.message.reply_text("❌ ምሳሌ: /paid 5 10 15  ወይም  /paid 5:2")
        return

    is_paid = update.message.text.startswith("/paid")
    settings = get_active_settings(group_id=group_id)
    if not settings:
        return

    updated = []
    errors = []

    for part in parts[1:]:
        try:
            if ":" in part:
                num_str, slot_str = part.split(":", 1)
                number = int(num_str)
                slot = int(slot_str)
            else:
                number = int(part)
                slot = 1
            admin_mark_paid(settings["id"], number, slot, is_paid)
            updated.append((number, slot))

            if is_paid and settings["id"] in nekay_active:
                snap = nekay_numbers.get(settings["id"], {})
                if number in snap:
                    del snap[number]
                    nekay_numbers[settings["id"]] = snap
        except ValueError:
            errors.append(part)

    if is_paid and settings["id"] in nekay_active:
        snap = nekay_numbers.get(settings["id"], {})
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
            nekay_active.discard(settings["id"])
            nekay_numbers.pop(settings["id"], None)

    await _refresh_board(ctx, settings, group_id)

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

    clear_game(settings["id"])
    nekay_active.discard(settings["id"])
    active_countdowns.pop(settings["id"], None)
    nekay_numbers.pop(settings["id"], None)
    countdown_done.discard(settings["id"])
    _stop_inactivity_tracker(settings["id"])

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

        is_nekay = settings["id"] in nekay_numbers and actual_num in nekay_numbers.get(settings["id"], {})
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
        if db_num < 1 or db_num > len(get_all_db_urls() if True else []):
            await update.message.reply_text(f"❌ DB{db_num} የለም!")
            return
        clear_db_data(db_num)
        await update.message.reply_text(f"✅ DB{db_num} ጸዳ! (usernames ይቀራሉ)")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")


def get_all_db_urls():
    from config import DATABASE_URLS
    return DATABASE_URLS


async def handle_winners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return

    if not group_id:
        await update.message.reply_text("❌ Group ውስጥ ብቻ ይሰራል!")
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
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
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
    group_id = update.effective_chat.id
    if not is_admin(update.effective_user.id, group_id):
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
        lines.append("🎮 ዛሬ ጨዋታ የለም (15+ registered)")

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

    if is_main_admin(user_id) and ctx.user_data.get("setwarn_minutes"):
        await handle_warnmedia_upload(update, ctx)
        return

    if is_admin(user_id, group_id):
        settings = get_active_settings(group_id=group_id)
        if settings:
            photo_uid = update.message.photo[-1].file_unique_id
            if photo_uid in handled_winner_photos:
                return
            handled_winner_photos.add(photo_uid)

            await handle_winner_photo(ctx.bot, update.message, settings, group_id=group_id)
            await _auto_newgame(ctx.bot, settings, group_id)
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
            await nekay_payment_cb(ctx.bot, game_id, update.effective_user.id, confirmed)

    try:
        await handle_payment_photo(ctx.bot, update.message, nekay_cb=_nekay_cb)
    finally:
        photo_processing[group_id] = False
        queued = pending_registrations.pop(group_id, [])
        for (q_user_id, q_user_name, q_text, q_msg) in queued:
            settings2 = get_active_settings(group_id=group_id)
            if not settings2:
                continue
            result = parse_numbers(q_text)
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
                if ambiguous == "all_half":
                    await q_msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
                elif ambiguous == "last_half":
                    await q_msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
            else:
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)


async def _auto_newgame(bot, settings: dict, group_id: int = None):
    game_id = settings["id"]
    _group_id = group_id or settings.get("group_id") or GROUP_ID

    try:
        profit_data = calculate_game_profit(game_id)
        if profit_data and profit_data.get("counted") and _group_id:
            save_game_report(
                group_id=_group_id,
                game_id=game_id,
                total_bet=profit_data["total_bet"],
                prize_total=profit_data["prize_total"],
                profit=profit_data["profit"],
                registered_count=profit_data["registered_count"],
            )
    except Exception as e:
        logging.warning(f"[AutoNewgame] Report save error: {e}")

    nekay_active.discard(game_id)
    active_countdowns.pop(game_id, None)
    nekay_numbers.pop(game_id, None)
    countdown_done.discard(game_id)
    _stop_inactivity_tracker(game_id)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await bot.delete_message(chat_id=_group_id, message_id=rem_msg_id)
        except Exception:
            pass

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

    parts = update.message.text.strip().split()
    group_id = None
    if len(parts) > 1:
        try:
            group_id = int(parts[1])
        except ValueError:
            pass

    if not group_id:
        enabled = get_enabled_groups()
        admin_groups = []
        for g in enabled:
            if is_admin(user_id, g["group_id"]):
                admin_groups.append(g)

        if not admin_groups:
            await update.message.reply_text("❌ Admin የሆነህ active group የለም!")
            return ConversationHandler.END

        if len(admin_groups) == 1:
            group_id = admin_groups[0]["group_id"]
        else:
            lines = ["📋 የትኛው group? ID ጻፍ:\n"]
            for g in admin_groups:
                lines.append(f"• {g['group_name'] or g['group_id']}: {g['group_id']}")
            await update.message.reply_text("\n".join(lines))
            ctx.user_data["awaiting_group_id"] = True
            ctx.user_data["admin_groups"] = admin_groups
            return ASK_SEND_PLACE

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
    if ctx.user_data.get("awaiting_group_id"):
        try:
            group_id = int(update.message.text.strip())
            ctx.user_data["send_group_id"] = group_id
            ctx.user_data["awaiting_group_id"] = False
            return await _send_show_places(update, ctx, group_id)
        except ValueError:
            await update.message.reply_text("❌ Group ID ቁጥር ብቻ ጻፍ!")
            return ASK_SEND_PLACE

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

    winner = get_winner_by_place(settings["id"], place)
    if not winner:
        await update.message.reply_text(f"❌ {place}ኛ winner አልተመዘገበም!")
        return ConversationHandler.END

    if winner.get("group_id") and winner["group_id"] != group_id:
        await update.message.reply_text("❌ ይህ winner የዚህ group አይደለም!")
        return ConversationHandler.END

    ctx.user_data["send_place"] = place
    ctx.user_data["send_telegram_id"] = winner["telegram_id"]
    ctx.user_data["send_user_name"] = winner["user_name"]
    ctx.user_data["send_game_id"] = settings["id"]

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

    result = deduct_winner_balance(game_id, telegram_id, amount)
    new_balance = result["new_balance"]

    mark_winner_sent(game_id, telegram_id, amount)

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
    group_id = update.effective_chat.id if update.effective_chat.type != "private" else None
    if not is_admin(update.effective_user.id, group_id):
        return

    is_main = is_main_admin(update.effective_user.id)

    text = (
        "🤖 Commands:\n\n"
        "🎮 *Game*\n"
        "/setgame — አዲስ game settings ያቀናብራል\n"
        "/newgame — ቁጥሮችን ጠርጎ አዲስ ጨዋታ ይጀምራል\n"
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
        "/send — winner ብር ይላካል (private chat ብቻ)\n"
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
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

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
        raw = await request.text()
        try:
            parsed = json.loads(raw)
            sms_text = parsed.get("sms", raw)
        except Exception:
            sms_text = raw

        if not sms_text:
            return web.json_response({"success": False, "reason": "empty_body"})

        result = await handle_sms_webhook(sms_text, bot=_bot_instance, nekay_cb=_make_nekay_cb())
        return web.json_response(result)
    except Exception as e:
        logging.error(f"[SMS Endpoint] Error: {e}", exc_info=True)
        return web.json_response({"success": False, "reason": "server_error"}, status=500)


async def health_check(request):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return web.Response(text=f"🤖 Bot is running!\n🕐 Server time: {now}")


_bot_instance = None


def _make_nekay_cb():
    async def _nekay_cb(confirmed):
        settings = get_active_settings()
        if settings and _bot_instance:
            await nekay_payment_cb(_bot_instance, settings["id"], 0, confirmed)
    return _nekay_cb


async def start_server():
    web_app = web.Application()
    web_app.router.add_post("/sms", sms_endpoint)
    web_app.router.add_get("/", health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("🌐 SMS Server started on port 8080")


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
        },
        fallbacks=[CommandHandler("cancel", cancel_setup)],
    )

    send_conv = ConversationHandler(
        entry_points=[CommandHandler("send", send_start)],
        states={
            ASK_SEND_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, send_ask_place)],
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
    app.add_handler(CommandHandler("report", handle_report))
    app.add_handler(CommandHandler("setwarnmedia", handle_setwarnmedia))
    app.add_handler(CommandHandler("listwarnmedia", handle_listwarnmedia))
    app.add_handler(CommandHandler("deletewarnmedia", handle_deletewarnmedia))

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
        filters.Sticker.ALL & filters.ChatType.PRIVATE,
        handle_warnmedia_upload
    ))

    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.GROUPS,
        handle_group_photo
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ))

    from telegram.ext import ChatMemberHandler
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server())

    global _bot_instance
    _bot_instance = app.bot

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
                        await _bot_instance.send_message(chat_id=gid, text="\n".join(lines))
                    except Exception:
                        pass
                cleanup_old_reports()
            except Exception as e:
                logging.warning(f"[Daily Report] Error: {e}")

    loop.create_task(_daily_report_scheduler())

    print("🤖 Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
