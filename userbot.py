"""
userbot.py — Telethon-based userbot commands
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import FloodWaitError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

from database import get_conn
