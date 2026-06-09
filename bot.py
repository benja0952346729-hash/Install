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
    admin_remove_player, admin_mark_paid,
    clear_game, get_unpaid_numbers
)
from parser import parse_numbers, format_number
from board import (
    build_board, build_remaining,
    count_remaining, get_group_start,
    build_warning, build_nekay
)
from handlers import handle_payment_photo, handle_sms_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

(
    ASK_TOTAL, ASK_PER_PERSON, ASK_PRICE_FULL,
    ASK_PRICE_HALF, ASK_PRIZE_1, ASK_PRIZE_2,
    ASK_PRIZE_3, ASK_PAYMENT
) = range(8)

pending_ambiguous = {}
active_countdowns = {}  # game_id: task


async def _countdown_task(bot, game_id: int, group_id: int, warn_seconds: int = 120):
    """Background countdown — warning message ይዘምናል፣ ጊዜ ካለቀ ነቃይ ይላካል"""
    warn_msg = await bot.send_message(chat_id=group_id, text=build_warning(warn_seconds))

    interval = 5
    elapsed = 0
    while elapsed < warn_seconds:
        await asyncio.sleep(interval)
        elapsed += interval
        left = warn_seconds - elapsed
        if left < 0:
            left = 0
        try:
            await bot.edit_message_text(
                chat_id=group_id,
                message_id=warn_msg.message_id,
                text=build_warning(left)
            )
        except Exception:
            pass
        if left == 0:
            break

    # ጊዜ አለቀ — ያልከፈሉ ያወጣ
    unpaid = get_unpaid_numbers(game_id)
    if unpaid:
        for number, is_half in unpaid:
            admin_remove_player(game_id, number)
        nekay_text = build_nekay(unpaid)
        try:
            await bot.edit_message_text(
                chat_id=group_id,
                message_id=warn_msg.message_id,
                text=nekay_text
            )
        except Exception:
            await bot.send_message(chat_id=group_id, text=nekay_text)
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

    result = parse_numbers(text)
    if not result:
        return

    numbers = result["numbers"]
    ambiguous = result["ambiguous"]
    ambiguous_number = result["ambiguous_number"]

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

    registered = []
    failed = []

    for num, is_half in numbers:
        actual_num = get_group_start(num, per_person) if per_person > 1 else num

        if actual_num < 1 or actual_num > settings["total_numbers"]:
            failed.append(format_number(num))
            continue

        result = register_number(game_id, user_id, user_name, actual_num, is_half)
        if result in ["registered", "registered_half"]:
            registered.append((actual_num, is_half))
        else:
            failed.append(format_number(num))

    if not registered:
        if failed:
            await msg.reply_text(f"❌ {', '.join(failed)} ቀድሞ ተወስዷል!")
        return

    taken = get_taken_numbers(game_id)
    paid = get_paid_numbers(game_id)
    board_text = build_board(settings, taken, paid)
    remaining_count = count_remaining(settings, taken)

    board_msg_id = settings.get("board_message_id")

    if remaining_count <= 7:
        if board_msg_id:
            try:
                await ctx.bot.delete_message(chat_id=group_id, message_id=board_msg_id)
            except Exception:
                pass
        new_board = await ctx.bot.send_message(chat_id=group_id, text=board_text)
        update_board_message_id(game_id, new_board.message_id)

        remaining_text = build_remaining(settings, taken)
        rem_msg_id = settings.get("remaining_message_id")
        if remaining_text:
            if rem_msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=group_id, message_id=rem_msg_id)
                except Exception:
                    pass
            rem_msg = await ctx.bot.send_message(chat_id=group_id, text=remaining_text)
            update_remaining_message_id(game_id, rem_msg.message_id)
            settings["board_message_id"] = new_board.message_id
            settings["remaining_message_id"] = rem_msg.message_id
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

    # Board ሲሞላ countdown ይጀምር
    if remaining_count == 0 and game_id not in active_countdowns:
        task = asyncio.create_task(
            _countdown_task(ctx.bot, game_id, group_id)
        )
        active_countdowns[game_id] = task

    reg_list = ", ".join(format_number(n) + ("+" if h else "") for n, h in registered)
    warning = ""
    for n, is_half in numbers:
        if is_half:
            warning = "\n\n⚠️ በሚቀጥለው መጨረሻ ላይ ይህን ምልክት + አይጠቀሙ 🙏 ግራ ያጋባል"
            break

    if failed:
        fail_list = ", ".join(failed)
        await msg.reply_text(f"✅ {reg_list} ተመዘገበ!\n❌ {fail_list} ቀድሞ ተወስዷል!{warning}")
    else:
        await msg.reply_text(f"✅ {reg_list} ተመዘገበ!{warning}")


# ============================================================
# ADMIN — BOARD REFRESH HELPER
# ============================================================

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


# ============================================================
# ADMIN — /remove
# ============================================================

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


# ============================================================
# ADMIN — /paid /unpaid
# ============================================================

async def handle_paid_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("❌ ምሳሌ: /paid 5  ወይም  /paid 5 2")
        return
    try:
        number = int(parts[1])
        slot = int(parts[2]) if len(parts) > 2 else 1
    except ValueError:
        await update.message.reply_text("❌ ቁጥር ብቻ ጻፍ!")
        return

    is_paid = update.message.text.startswith("/paid")
    settings = get_active_settings()
    if not settings:
        return

    admin_mark_paid(settings["id"], number, slot, is_paid)
    await _refresh_board(ctx, settings)

    mark = "✅" if is_paid else "❌"
    await update.message.reply_text(f"{mark} {format_number(number)} slot {slot} updated!")


# ============================================================
# ADMIN — /newgame
# ============================================================

async def handle_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    settings = get_active_settings()
    if not settings:
        await update.message.reply_text("❌ Active game የለም!")
        return

    clear_game(settings["id"])

    # አሮጌ board ይሰርዛል
    board_msg_id = settings.get("board_message_id")
    if board_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=GROUP_ID, message_id=board_msg_id)
        except Exception:
            pass

    # አሮጌ remaining ይሰርዛል
    rem_msg_id = settings.get("remaining_message_id")
    if rem_msg_id:
        try:
            await ctx.bot.delete_message(chat_id=GROUP_ID, message_id=rem_msg_id)
        except Exception:
            pass

    # አዲስ ባዶ board ይላካል
    board_text = build_board(settings, {}, {})
    new_msg = await ctx.bot.send_message(chat_id=GROUP_ID, text=board_text)
    update_board_message_id(settings["id"], new_msg.message_id)
    update_remaining_message_id(settings["id"], None)

    await update.message.reply_text("✅ አዲስ ጨዋታ ተጀምሯል!")


# ============================================================
# SMS WEBHOOK SERVER
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

        result = await handle_sms_webhook(sms_text)
        return web.json_response(result)
    except Exception as e:
        logging.error(f"[SMS Endpoint] Error: {e}", exc_info=True)
        return web.json_response({"success": False, "reason": "server_error"}, status=500)


async def health_check(request):
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return web.Response(text=f"🤖 Bot is running!\n🕐 Server time: {now}")


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
        },
        fallbacks=[CommandHandler("cancel", cancel_setup)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(setup_conv)
    app.add_handler(CommandHandler("remove", handle_remove))
    app.add_handler(CommandHandler("paid", handle_paid_cmd))
    app.add_handler(CommandHandler("unpaid", handle_paid_cmd))
    app.add_handler(CommandHandler("newgame", handle_newgame))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.GROUPS,
        lambda u, c: handle_payment_photo(c.bot, u.message)
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server())

    print("🤖 Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
