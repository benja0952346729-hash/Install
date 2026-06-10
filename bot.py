import os
import logging
import asyncio
import json
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
    user_owns_number, get_user_numbers, remove_number
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
from responder import get_response
(
    ASK_TOTAL, ASK_PER_PERSON, ASK_PRICE_FULL,
    ASK_PRICE_HALF, ASK_PRIZE_1, ASK_PRIZE_2,
    ASK_PRIZE_3, ASK_PAYMENT,
    ASK_SEND_PLACE, ASK_SEND_AMOUNT
) = range(10)

pending_ambiguous = {}
active_countdowns = {}
nekay_active = set()
nekay_numbers = {}
msg_counter = {}

photo_processing = {}
pending_registrations = {}

handled_winner_photos = set()


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

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=GROUP_ID,
                message_id=board_msg_id,
                text=board_text
            )
        except Exception:
            new_msg = await bot.send_message(chat_id=GROUP_ID, text=board_text)
            update_board_message_id(game_id, new_msg.message_id)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await bot.delete_message(chat_id=GROUP_ID, message_id=rem_msg_id)
        except Exception:
            pass

    if snap:
        nekay_list = _build_nekay_from_snap(snap)
        nekay_text = build_nekay(nekay_list)
        new_nekay = await bot.send_message(chat_id=GROUP_ID, text=nekay_text)
        update_remaining_message_id(game_id, new_nekay.message_id)
    else:
        update_remaining_message_id(game_id, None)
        nekay_active.discard(game_id)
        nekay_numbers.pop(game_id, None)


def _increment_counter(group_id: int) -> int:
    msg_counter[group_id] = msg_counter.get(group_id, 0) + 1
    if msg_counter[group_id] >= 6:
        msg_counter[group_id] = 0
        return True
    return False


def _build_nekay_from_snap(snap: dict) -> list:
    result = []
    for number, slot in sorted(snap.items()):
        is_half = (slot == 2)
        result.append((number, is_half))
    return result


async def _countdown_task(bot, game_id: int, group_id: int, warn_seconds: int = 120):
    warn_msg = await bot.send_message(chat_id=group_id, text=build_warning())

    interval = 3
    steps = warn_seconds // interval
    total_bars = 12

    for i in range(steps, 0, -1):
        await asyncio.sleep(interval)
        remaining_secs = i * interval
        mins = remaining_secs // 60
        secs = remaining_secs % 60

        if mins > 0:
            time_str = f"⏳ {mins}:{secs:02d} ይቀራል"
        else:
            time_str = f"⏳ {secs} ሰከንድ ይቀራል"

        elapsed = steps - i
        filled = min(elapsed + 1, total_bars)
        empty = total_bars - filled
        bar = "🟥" * filled + "⬜" * empty

        try:
            await bot.edit_message_text(
                chat_id=group_id,
                message_id=warn_msg.message_id,
                text=build_warning(countdown_text=f"{time_str}\n{bar}")
            )
        except Exception:
            pass

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
        try:
            await bot.edit_message_text(
                chat_id=group_id,
                message_id=warn_msg.message_id,
                text=nekay_text
            )
        except Exception:
            await bot.send_message(chat_id=group_id, text=nekay_text)
        nekay_active.add(game_id)
        update_remaining_message_id(game_id, warn_msg.message_id)
    else:
        try:
            await bot.delete_message(chat_id=group_id, message_id=warn_msg.message_id)
        except Exception:
            pass

    active_countdowns.pop(game_id, None)


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot ተሰናድቷል!")


async def setgame_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin ብቻ ነው!")
        return ConversationHandler.END
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
    game_id = save_settings(ctx.user_data)

    settings = get_active_settings()
    taken = {}
    board_text = build_board(settings, taken)

    if GROUP_ID:
        msg = await ctx.bot.send_message(chat_id=GROUP_ID, text=board_text)
        update_board_message_id(game_id, msg.message_id)

    await update.message.reply_text(
        f"✅ Settings ተቀምጧል!\nGame ID: {game_id}"
    )
    return ConversationHandler.END


async def cancel_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup ተሰርዟል።")
    return ConversationHandler.END


async def handle_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    user = msg.from_user
    user_id = user.id
    user_name = user.first_name or "Unknown"
    text = msg.text.strip()
    group_id = update.effective_chat.id

    if user_id in pending_ambiguous:
        await handle_ambiguous_reply(update, ctx, text, user_id, user_name, group_id)
        return

    settings = get_active_settings()
    if not settings:
        return

    game_id = settings["id"]
    taken = get_taken_numbers(game_id)
    snap = nekay_numbers.get(game_id, {})
    nekay_list = _build_nekay_from_snap(snap)
    remaining = count_remaining(settings, taken)

    parse_result = parse_numbers(text)

    if not parse_result:
        resp = get_response(
            text=text,
            settings=settings,
            taken=taken,
            paid=get_paid_numbers(game_id),
            nekay_list=nekay_list,
            remaining_count=remaining,
            countdown_seconds=0,
            user_name=user_name,
            user_id=user_id,
        )
        if resp["reply"]:
            await msg.reply_text(resp["reply"])
        if resp["resend_remaining"]:
            await _send_remaining(ctx, settings, group_id)
        if resp["resend_nekay"]:
            if snap:
                nekay_text = build_nekay(nekay_list)
                await ctx.bot.send_message(chat_id=group_id, text=nekay_text)

        # ================================================================
        # CANCEL NUMBER — "07 አልፈልግም / 07 ሽጠው / 07 አጥፋው"
        # ================================================================
        if resp.get("cancel_number"):
            num = resp["cancel_number"]
            if user_owns_number(game_id, user_id, num):
                removed = remove_number(game_id, user_id, num)
                if removed:
                    # nekay snap ውስጥ ካለ አስወጣ
                    if game_id in nekay_numbers and num in nekay_numbers.get(game_id, {}):
                        del nekay_numbers[game_id][num]
                    # Board ዘምን
                    await _refresh_board(ctx, settings)
                    # nekay active ከሆነ nekay message ዘምን
                    if game_id in nekay_active:
                        snap2 = nekay_numbers.get(game_id, {})
                        rem_msg_id = settings.get("remaining_message_id")
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
            else:
                await msg.reply_text("ቁጥሩ የእርስዎ አይደለም 🙏")
        return

    # ቁጥር አለ — registration
    if photo_processing.get(group_id):
        q = pending_registrations.setdefault(group_id, [])
        q.append((user_id, user_name, text, msg))
        return

    numbers = parse_result["numbers"]
    ambiguous = parse_result["ambiguous"]
    ambiguous_number = parse_result["ambiguous_number"]

    if ambiguous:
        pending_ambiguous[user_id] = {
            "numbers": numbers,
            "ambiguous": ambiguous,
            "ambiguous_number": ambiguous_number,
            "game_id": settings["id"],
            "settings": settings,
            "group_id": group_id,
            "user_name": user_name
        }
        if ambiguous == "all_half":
            await msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
        elif ambiguous == "last_half":
            await msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
        return

    await process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg)


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
            numbers = [(n, True) for n, _ in numbers]
    elif ambiguous == "last_half":
        if not yes:
            numbers = [(n, False) for n, _ in numbers]

    del pending_ambiguous[user_id]
    await process_registration(ctx, settings, numbers, user_id, user_name, group_id, update.message)


async def process_registration(ctx, settings, numbers, user_id, user_name, group_id, msg):
    game_id = settings["id"]
    per_person = settings["numbers_per_person"]

    taken_before = get_taken_numbers(game_id)
    remaining_before = count_remaining(settings, taken_before)

    registered = []
    all_taken = []

    for num, is_half in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        if actual_num < 1 or actual_num > settings["total_numbers"]:
            all_taken.append(actual_num)
            continue

        is_nekay = game_id in nekay_numbers and actual_num in nekay_numbers.get(game_id, {})
        result = register_number(game_id, user_id, user_name, actual_num, is_half, force=is_nekay)
        if result in ["registered", "registered_half"]:
            registered.append((actual_num, is_half))
        else:
            all_taken.append(actual_num)

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    remaining_count = count_remaining(settings, taken)
    snap = nekay_numbers.get(game_id, {})
    nekay_list = _build_nekay_from_snap(snap)

    if registered:
        reg_result = "registered"
    elif all_taken:
        reg_result = "taken"
    else:
        reg_result = None

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

    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")
    should_resend = _increment_counter(group_id)

    crossed_into_low = (remaining_before > 7) and (remaining_count <= 7)
    if crossed_into_low:
        should_resend = True

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
                    await ctx.bot.edit_message_text(
                        chat_id=group_id,
                        message_id=board_msg_id,
                        text=board_text
                    )
                except Exception:
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

    elif remaining_count <= 7:
        if should_resend:
            if board_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
                except Exception:
                    pass
            new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
            update_board_message_id(game_id, new_board.message_id)
            board_msg_id = new_board.message_id
        else:
            if board_msg_id:
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=group_id,
                        message_id=board_msg_id,
                        text=board_text
                    )
                except Exception:
                    new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    update_board_message_id(game_id, new_board.message_id)
                    board_msg_id = new_board.message_id

        await _send_remaining(ctx, settings, group_id)

    else:
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
                    await ctx.bot.edit_message_text(
                        chat_id=group_id,
                        message_id=board_msg_id,
                        text=board_text
                    )
                except Exception:
                    new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
                    update_board_message_id(game_id, new_board.message_id)

    if remaining_count == 0 and game_id not in active_countdowns:
        task = asyncio.create_task(
            _countdown_task(ctx.bot, game_id, group_id)
        )
        active_countdowns[game_id] = task


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


async def _refresh_board(ctx, settings):
    game_id = settings["id"]
    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    board_msg_id = settings.get("board_message_id")

    if board_msg_id:
        try:
            await ctx.bot.edit_message_text(
                chat_id=GROUP_ID,
                message_id=board_msg_id,
                text=board_text
            )
        except Exception:
            new_msg = await ctx.bot.send_message(chat_id=GROUP_ID, text=board_text)
            update_board_message_id(game_id, new_msg.message_id)
    else:
        new_msg = await ctx.bot.send_message(chat_id=GROUP_ID, text=board_text)
        update_board_message_id(game_id, new_msg.message_id)


async def handle_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /remove 5  ወይም  /remove 5:1 10 15:2")
        return

    settings = get_active_settings()
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

    await _refresh_board(ctx, settings)

    msg = ""
    if removed:
        msg += f"✅ {', '.join(removed)} ተወጣ!"
    if errors:
        msg += f"\n❌ ያልተቀበለ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_paid_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /paid 5 10 15  ወይም  /paid 5:2")
        return

    is_paid = update.message.text.startswith("/paid")
    settings = get_active_settings()
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
                await ctx.bot.delete_message(chat_id=GROUP_ID, message_id=rem_msg_id)
            except Exception:
                pass
        if snap:
            from board import build_nekay
            nekay_list = _build_nekay_from_snap(snap)
            nekay_text = build_nekay(nekay_list)
            new_nekay = await ctx.bot.send_message(chat_id=GROUP_ID, text=nekay_text)
            update_remaining_message_id(settings["id"], new_nekay.message_id)
        else:
            update_remaining_message_id(settings["id"], None)
            nekay_active.discard(settings["id"])
            nekay_numbers.pop(settings["id"], None)

    await _refresh_board(ctx, settings)

    mark = "✅" if is_paid else "❌"
    updated_str = ", ".join(f"{format_number(n)}:{s}" for n, s in updated)
    msg = f"{mark} {updated_str} updated!"
    if errors:
        msg += f"\n❌ ያልተቀበለ: {', '.join(errors)}"
    await update.message.reply_text(msg)


async def handle_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    settings = get_active_settings()
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    clear_game(settings["id"])
    nekay_active.discard(settings["id"])
    active_countdowns.pop(settings["id"], None)
    nekay_numbers.pop(settings["id"], None)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=GROUP_ID, message_id=rem_msg_id)
        except Exception:
            pass

    board_text = build_board(settings, {}, {})
    new_msg = await ctx.bot.send_message(chat_id=GROUP_ID, text=board_text)
    update_board_message_id(settings["id"], new_msg.message_id)
    update_remaining_message_id(settings["id"], None)

    await update.message.reply_text("✅ አዲስ ጨዋታ ተጀምሯል!")


async def handle_group_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if is_admin(user_id):
        settings = get_active_settings()
        if settings:
            photo_uid = update.message.photo[-1].file_unique_id
            if photo_uid in handled_winner_photos:
                return
            handled_winner_photos.add(photo_uid)

            await handle_winner_photo(ctx.bot, update.message, settings)
            await _auto_newgame(ctx.bot, settings)
            return

    _increment_counter(group_id)
    settings = get_active_settings()
    game_id = settings["id"] if settings else None

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
            settings2 = get_active_settings()
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
                    "numbers": numbers,
                    "ambiguous": ambiguous,
                    "ambiguous_number": ambiguous_number,
                    "game_id": settings2["id"],
                    "settings": settings2,
                    "group_id": group_id,
                    "user_name": q_user_name
                }
                if ambiguous == "all_half":
                    await q_msg.reply_text("ሁሉንም በግማሽ ነው? (አዎ/አይደለም)")
                elif ambiguous == "last_half":
                    await q_msg.reply_text(f"{format_number(ambiguous_number)} ብቻ በግማሽ ነው? (አዎ/አይደለም)")
            else:
                await process_registration(ctx, settings2, numbers, q_user_id, q_user_name, group_id, q_msg)


async def _auto_newgame(bot, settings: dict):
    game_id = settings["id"]

    nekay_active.discard(game_id)
    active_countdowns.pop(game_id, None)
    nekay_numbers.pop(game_id, None)

    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await bot.delete_message(chat_id=GROUP_ID, message_id=rem_msg_id)
        except Exception:
            pass

    clear_game(game_id)

    board_text = build_board(settings, {}, {})
    new_msg = await bot.send_message(chat_id=GROUP_ID, text=board_text)
    update_board_message_id(game_id, new_msg.message_id)
    update_remaining_message_id(game_id, None)


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
    from datetime import datetime
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


async def send_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    if update.effective_chat.type != "private":
        await update.message.reply_text("❌ Private chat ብቻ ነው!")
        return ConversationHandler.END

    settings = get_active_settings()
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return ConversationHandler.END

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
    settings = get_active_settings()
    if not settings:
        return ConversationHandler.END

    winner = get_winner_by_place(settings["id"], place)
    if not winner:
        await update.message.reply_text(f"❌ {place}ኛ winner አልተመዘገበም!")
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

    result = deduct_winner_balance(game_id, telegram_id, amount)
    new_balance = result["new_balance"]

    settings = get_active_settings()
    place_label = {1: "1ኛ", 2: "2ኛ", 3: "3ኛ"}.get(place, f"{place}ኛ")

    lines = [
        f"✅ {place_label} winner: {user_name}",
        f"💸 የላካህ: ETB {amount}",
        f"💳 ቀሪ balance: ETB {new_balance}",
    ]

    await update.message.reply_text("\n".join(lines))

    if settings:
        await _refresh_board(ctx, settings)

    return ConversationHandler.END


async def cancel_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ /send ተሰርዟል።")
    return ConversationHandler.END


async def handle_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
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
        "/remove 5:1 — slot 1 ብቻ ያስወጣል\n\n"
        "💸 *Winner*\n"
        "/send — winner ብር ይላካል (private chat ብቻ)\n"
        "  • winner photo group ላይ ሲላክ auto announce + አዲስ game"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 3:
        await update.message.reply_text("❌ ምሳሌ: /register 5 አበበ  ወይም  /register 5 10 15+ አበበ")
        return

    user_name = parts[-1]
    number_parts = parts[1:-1]

    settings = get_active_settings()
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

    await _refresh_board(ctx, settings)

    reg_list = ", ".join(format_number(n) + ("+" if h else "") for n, h in registered)
    msg = f"✅ {reg_list} → {user_name} ተመዘገበ!"
    if failed:
        msg += f"\n❌ {', '.join(failed)} ቀድሞ ተወስዷል!"
    await update.message.reply_text(msg)


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
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.GROUPS,
        handle_group_photo
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server())

    global _bot_instance
    _bot_instance = app.bot

    print("🤖 Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
