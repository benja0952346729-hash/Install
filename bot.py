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
        "/nekay 5 10+ 15 — manually ነቃይ ያደርጋል (ቀድሞ የነበረውን ይተካል)\n"
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
            await nekay_payment_cb(_bot_instance, settings["id"], 0, confirmed)
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

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    register_userbot_handlers(app)

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
    app.add_handler(CommandHandler("setcountdown", handle_setcountdown))
    app.add_handler(CommandHandler("nekay", handle_nekay_cmd))
    app.add_handler(CommandHandler("setcompletesticker", handle_setcompletesticker))
    app.add_handler(CommandHandler("listcompletestickers", handle_listcompletestickers))
    app.add_handler(CommandHandler("removecompletesticker", handle_removecompletesticker))
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
        handle_admin_board_reply
    ), group=0)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ), group=1)

    from telegram.ext import ChatMemberHandler
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_server())

    global _bot_instance
    _bot_instance = app.bot

    # ── Jina Brain init (background task) ──────────────────────────
    async def _init_jina_background():
        try:
            from jina_brain import init_jina_brain
            from responder import INTENT_EXAMPLES
            from config import JINA_API_KEYS as _jina_keys
            await init_jina_brain(INTENT_EXAMPLES, _jina_keys)
        except Exception as e:
            logging.warning(f"[Jina] Background init error: {e}")

    loop.create_task(_init_jina_background())

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
            except Exception as e:
                logging.warning(f"[Daily Report] Error: {e}")

    loop.create_task(_daily_report_scheduler())

    print("🤖 Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
