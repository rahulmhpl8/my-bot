import logging
import sqlite3
import random
import string
import io
import asyncio
import threading
import time
import requests
import os
import shutil                     # file operations के लिए
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ------------------ LOGGING SETUP ------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ------------------ CONFIGURATION (Environment Variables) ------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

admin_ids_str = os.environ.get("ADMIN_USER_IDS", "543578081")
ADMIN_USER_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip().isdigit()]

BOT_USERNAME = os.environ.get("BOT_USERNAME", "Geminiprolink_bot")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/lootjunctiontg")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@lootjunctiontg")

# ------------------ VERSION & AUTO-UPDATE ------------------
CURRENT_VERSION = "1.0.2"
UPDATE_MESSAGE = (
    "🚀 *New Update Available!*\n\n"
    "We've added new features and improvements. Check out the latest version now!\n"
    "Use the buttons below to explore."
)

# ------------------ DATABASE ------------------
DB_NAME = os.environ.get("DB_PATH", "users.db")

# ------------------ URL SHORTENER ------------------
def shorten_url(url):
    try:
        response = requests.get(f"http://tinyurl.com/api-create.php?url={url}", timeout=3)
        if response.status_code == 200:
            short = response.text.strip()
            if short.startswith("http"):
                return short
        return url
    except Exception:
        return url

# ------------------ CREDIT DEDUCTION ------------------
def deduct_credit(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ? AND credits > 0", (user_id,))
    conn.commit()
    conn.close()

# ------------------ DATABASE INIT ------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            ref_code TEXT UNIQUE,
            credits INTEGER DEFAULT 0,
            referred_by INTEGER,
            join_date TEXT,
            refer_count INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            full_name TEXT
        )
    """)
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    if 'verified' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
    if 'full_name' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ref_code ON users(ref_code)")

    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('credits_per_referral', '2')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bot_version', ?)", (CURRENT_VERSION,))

    c.execute("""
        CREATE TABLE IF NOT EXISTS gemini_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            short_link TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON gemini_history(user_id)")

    conn.commit()
    conn.close()

# ---------- USER FUNCTIONS ----------
def add_user(user_id, referred_by=None, full_name=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if c.fetchone():
        conn.close()
        return

    while True:
        ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        c.execute("SELECT ref_code FROM users WHERE ref_code = ?", (ref_code,))
        if not c.fetchone():
            break

    join_date = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO users (user_id, ref_code, referred_by, join_date, credits, verified, full_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, ref_code, referred_by, join_date, 0, 0, full_name)
    )
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_ref(ref_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE ref_code = ?", (ref_code,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, credits, refer_count, full_name FROM users ORDER BY credits DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_total_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_credits():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT SUM(credits) FROM users")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def reset_user_credits(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET credits = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_verified(user_id, verified=1):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET verified = ? WHERE user_id = ?", (verified, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_credits(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def add_all_credits(amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ?", (amount,))
    conn.commit()
    conn.close()

# ---------- CONFIG FUNCTIONS ----------
def get_credits_per_referral():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'credits_per_referral'")
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else 2

def set_credits_per_referral(amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE config SET value = ? WHERE key = 'credits_per_referral'", (str(amount),))
    conn.commit()
    conn.close()

def get_bot_version():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'bot_version'")
    row = c.fetchone()
    conn.close()
    return row[0] if row else "0.0.0"

def set_bot_version(version):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE config SET value = ? WHERE key = 'bot_version'", (version,))
    conn.commit()
    conn.close()

# ---------- GEMINI HISTORY FUNCTIONS ----------
def save_gemini_link(user_id, original_link, short_link):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO gemini_history (user_id, link, short_link) VALUES (?, ?, ?)",
        (user_id, original_link, short_link)
    )
    conn.commit()
    conn.close()

def get_user_gemini_history(user_id, limit=10):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "SELECT short_link, extracted_at FROM gemini_history WHERE user_id = ? ORDER BY extracted_at DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

# ------------------ KEYBOARDS ------------------
main_reply_keyboard = ReplyKeyboardMarkup(
    [
        ["🔵 Gemini", "🔴 Profile"],
        ["🟢 Refer", "🟡 Support"],
        ["📜 History", "🏆 Leaderboard"]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

join_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
    [InlineKeyboardButton("✅ I have Joined", callback_data="check_join")]
])

async def replace_bot_message(chat_id, context, text, parse_mode=None, reply_markup=None, key='gemini_last_msg_id'):
    prev_id = context.user_data.get(key)
    if prev_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prev_id)
        except Exception:
            pass
    new_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup
    )
    context.user_data[key] = new_msg.message_id
    return new_msg

# ------------------ AUTO-UPDATE BROADCAST ------------------
async def send_update_to_all_users(app, message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()

    total = len(rows)
    sent = 0
    failed = 0

    for (uid,) in rows:
        try:
            await app.bot.send_message(
                chat_id=uid,
                text=message,
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            failed += 1
            logging.error(f"Update broadcast failed for user {uid}: {e}")
        await asyncio.sleep(0.05)

    logging.info(f"Update broadcast sent to {sent} users, failed {failed}, total {total}")

async def check_and_broadcast_update(app):
    current = get_bot_version()
    if current != CURRENT_VERSION:
        logging.info(f"Bot version changed from {current} to {CURRENT_VERSION}. Broadcasting update message.")
        set_bot_version(CURRENT_VERSION)
        asyncio.create_task(send_update_to_all_users(app, UPDATE_MESSAGE))
    else:
        logging.info("Bot version unchanged. No broadcast needed.")

# ------------------ HANDLERS ------------------
async def send_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚨 *You must join our channel to use this bot!*\n\n"
        "1️⃣ Click the button below to join.\n"
        "2️⃣ Then click *'I have Joined'* to verify."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=join_keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    full_name = update.effective_user.full_name or "Unknown"

    user = get_user(user_id)
    if not user:
        add_user(user_id, referred_by=None, full_name=full_name)
        user = get_user(user_id)
    else:
        if not user[7] and full_name:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("UPDATE users SET full_name = ? WHERE user_id = ?", (full_name, user_id))
            conn.commit()
            conn.close()
            user = get_user(user_id)

    if user and user[6] == 1:
        try:
            member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                display_name = user[7] or full_name or "User"
                await update.message.reply_text(
                    f"👋 Welcome back {display_name}!\nYour unique ID: `{user_id}`",
                    parse_mode="Markdown",
                    reply_markup=main_reply_keyboard
                )
                return
            else:
                set_verified(user_id, 0)
        except Exception as e:
            logging.error(f"Membership check error: {e}")
            set_verified(user_id, 0)

    if args and args[0].startswith("ref"):
        ref_code = args[0][3:]
        referrer_id = get_user_by_ref(ref_code)
        if referrer_id and referrer_id != user_id:
            context.user_data['pending_referrer'] = referrer_id

    display_name = full_name or "User"
    await update.message.reply_text(
        f"👋 Welcome {display_name}!\nYour unique ID: `{user_id}`",
        parse_mode="Markdown",
        reply_markup=main_reply_keyboard
    )
    await send_join_prompt(update, context)

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            set_verified(user_id, 1)

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            bonus = get_credits_per_referral()
            c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (bonus, user_id))
            referrer_id = context.user_data.get('pending_referrer')
            if referrer_id:
                c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (bonus, referrer_id))
                c.execute("UPDATE users SET refer_count = refer_count + 1 WHERE user_id = ?", (referrer_id,))
                c.execute("UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL", (referrer_id, user_id))
                context.user_data.pop('pending_referrer', None)
            conn.commit()
            conn.close()

            await query.edit_message_text(
                text=f"✅ Verified! Welcome to the bot.\nYour unique ID: {user_id}",
                reply_markup=None
            )
            await update.effective_message.reply_text(
                "Use the buttons below to explore.",
                reply_markup=main_reply_keyboard
            )
        else:
            await query.answer("You haven't joined the channel yet! Please join first.", show_alert=True)
    except Exception as e:
        logging.error(f"Error in check_join: {e}")
        await query.edit_message_text(
            "⚠️ *Unable to verify membership.*\n\n"
            "The bot is not a member of the channel. Please contact the admin to add the bot to the channel, then try again.",
            parse_mode="Markdown",
            reply_markup=join_keyboard
        )

async def require_verified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        full_name = update.effective_user.full_name or "Unknown"
        add_user(user_id, referred_by=None, full_name=full_name)
        user = get_user(user_id)

    if user[6] == 0:
        await send_join_prompt(update, context)
        return False

    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            set_verified(user_id, 0)
            await send_join_prompt(update, context)
            return False
    except Exception as e:
        logging.error(f"Membership check error: {e}")
        set_verified(user_id, 0)
        await update.message.reply_text(
            "⚠️ *Membership verification failed.*\n"
            "Please ensure the bot is a member of the channel, then try again.",
            parse_mode="Markdown"
        )
        await send_join_prompt(update, context)
        return False

    return True

# ---------- Profile ----------
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    user = get_user(user_id)
    if not user:
        await message.reply_text("Please /start the bot first.")
        return

    if user[6] == 0:
        await send_join_prompt(update, context)
        return

    try:
        join_dt = datetime.strptime(user[4], "%Y-%m-%d %H:%M:%S")
        join_display = join_dt.strftime("%d-%m-%Y")
    except:
        join_display = user[4][:10]

    text = (
        f"👤 *Profile*\n"
        f"ID: `{user[0]}`\n"
        f"Name: {user[7] or 'N/A'}\n"
        f"Referral Code: `{user[1]}`\n"
        f"Credits: {user[2]}\n"
        f"Total Referrals: {user[5]}\n"
        f"Joined: {join_display}"
    )
    await message.reply_text(text, parse_mode="Markdown", reply_markup=main_reply_keyboard)

# ---------- Refer ----------
async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    user = get_user(user_id)
    if not user:
        await message.reply_text("Please /start the bot first.")
        return

    if user[6] == 0:
        await send_join_prompt(update, context)
        return

    bonus = get_credits_per_referral()
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{user[1]}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20this%20bot%20and%20get%20credits!"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share", url=share_url)],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="refer_back")]
    ])
    await message.reply_text(
        f"🔗 *Your Referral Link*\n\n`{ref_link}`\n\nShare this link with friends using the button below.\n\nYou get *{bonus} credits* per referral!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def refer_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Returning to main menu.",
        reply_markup=main_reply_keyboard
    )

# ---------- Leaderboard ----------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_verified(update, context):
        return
    rows = get_all_users()
    if not rows:
        await update.message.reply_text("No users yet.", reply_markup=main_reply_keyboard)
        return
    top = rows[:10]
    text = "🏆 *Leaderboard (Top 10 by Credits)*\n\n"
    for i, (uid, credits, refs, name) in enumerate(top, start=1):
        display = name if name else f"User {uid}"
        text += f"{i}. {display} – Credits: {credits} (Refs: {refs})\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_reply_keyboard)

# ---------- History ----------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    if not await require_verified(update, context):
        return

    rows = get_user_gemini_history(user_id, limit=10)
    if not rows:
        await message.reply_text(
            "📭 *No Gemini links found in your history.*\n\n"
            "Use the *Gemini* button to extract a new link.",
            parse_mode="Markdown",
            reply_markup=main_reply_keyboard
        )
        return

    text = "📜 *Your Gemini Link History (last 10)*\n\n"
    for short_link, extracted_at in rows:
        try:
            dt = datetime.strptime(extracted_at, "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%d-%m-%Y %H:%M")
        except:
            date_str = extracted_at[:16]
        text += f"• `{short_link}`  _(extracted: {date_str})_\n"

    await message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_reply_keyboard
    )

# ------------------ GEMINI FLOW ------------------
async def gemini_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message = update.message

    old_timer = context.user_data.pop('gemini_timer_msg_id', None)
    if old_timer:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_timer)
        except Exception:
            pass

    user = get_user(user_id)
    if not user:
        await message.reply_text("Please /start the bot first.")
        return

    if user[6] == 0:
        await send_join_prompt(update, context)
        return

    if user[2] <= 0:
        await message.reply_text(
            "⚠️ *Insufficient Credits!*\n\n"
            "Please Refer This Bot to Earn Credit or Contact Our Support.\n\n"
            "Use the *Refer* button to share your referral link and earn credits per new user.",
            parse_mode="Markdown",
            reply_markup=main_reply_keyboard
        )
        return

    await replace_bot_message(
        chat_id=chat_id,
        context=context,
        text="*Gemini Link Extractor*\n\nPlease Enter 10 Digit Number:",
        parse_mode="Markdown",
        reply_markup=main_reply_keyboard,
        key='gemini_last_msg_id'
    )
    context.user_data['gemini_step'] = 'awaiting_mobile'
    context.user_data['jio_otp'] = None
    context.user_data['otp_attempts'] = 0
    context.user_data.pop('gemini_cancelled', None)

async def gemini_mobile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    step = context.user_data.get('gemini_step')
    chat_id = update.effective_chat.id

    if step == 'awaiting_mobile':
        if not user_text.isdigit() or len(user_text) != 10:
            await update.message.reply_text(
                "❌ *Invalid number!*\nPlease enter a 10-digit number or press a main menu button to cancel.",
                parse_mode="Markdown",
                reply_markup=main_reply_keyboard
            )
            return

        context.user_data['jio_mobile'] = user_text
        context.user_data['gemini_step'] = 'awaiting_otp'

        await replace_bot_message(
            chat_id=chat_id,
            context=context,
            text="Processing... ⏳",
            reply_markup=main_reply_keyboard,
            key='gemini_last_msg_id'
        )

        loop = asyncio.get_running_loop()
        threading.Thread(
            target=perform_jio_login,
            args=(update, context, user_text, loop, chat_id),
            daemon=True
        ).start()

    elif step == 'awaiting_otp':
        if not user_text.isdigit() or len(user_text) < 4:
            await update.message.reply_text(
                "❌ *Invalid OTP!*\nPlease enter the 4-6 digit OTP received on your mobile:",
                parse_mode="Markdown",
                reply_markup=main_reply_keyboard
            )
            return

        context.user_data['jio_otp'] = user_text
        await replace_bot_message(
            chat_id=chat_id,
            context=context,
            text="⏳ Submitting OTP...",
            reply_markup=main_reply_keyboard,
            key='gemini_last_msg_id'
        )

# ------------------ JIO LOGIN API ------------------
JIO_SEND_OTP_URL = "https://www.jio.com/api/jio-login-service/login/sendOtp"
JIO_VALIDATE_OTP_URL = "https://www.jio.com/api/jio-login-service/login/validateOtp"
JIO_ACTIVATE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/activate/Z0241"
JIO_GOOGLE_AI_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/google-ai"
JIO_GOOGLE_AI_SUBMIT_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/submit"

def _build_jio_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.jio.com",
        "Referer": "https://www.jio.com/selfcare/login/",
    })
    return session

_REDIRECT_KEYS = ("redirectionurl", "redirecturl", "redirectionlink", "redirectlink", "url")

def _extract_redirection_url(body):
    redirect_by_key = []
    google_urls = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value.strip().lower().startswith("http"):
                    if key.lower() in _REDIRECT_KEYS:
                        redirect_by_key.append(value.strip())
                    if "accounts.google.com" in value.lower():
                        google_urls.append(value.strip())
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    if google_urls:
        return google_urls[0]
    if redirect_by_key:
        return redirect_by_key[0]
    return None

def perform_jio_login(update, context, mobile, loop, chat_id):
    def notify(text):
        asyncio.run_coroutine_threadsafe(
            replace_bot_message(
                chat_id=chat_id,
                context=context,
                text=text,
                parse_mode="Markdown",
                reply_markup=main_reply_keyboard,
                key='gemini_last_msg_id'
            ),
            loop
        )

    try:
        session = _build_jio_session()

        # ---------- 1. Send OTP ----------
        asyncio.run_coroutine_threadsafe(
            replace_bot_message(
                chat_id=chat_id,
                context=context,
                text="⏳ OTP Sending Please Wait...",
                parse_mode="Markdown",
                reply_markup=main_reply_keyboard,
                key='gemini_last_msg_id'
            ),
            loop
        )

        try:
            send_resp = session.post(
                JIO_SEND_OTP_URL,
                json={"mobileNumber": mobile, "loginFlowType": "MOBILE", "alternateNumber": ""},
                timeout=30
            )
            send_data = send_resp.json()
        except Exception as e:
            logging.error(f"sendOtp error: {e}")
            notify("❌ Unable to reach Jio server to send OTP. Please try again later.\nNo credits were deducted.")
            return

        if send_resp.status_code != 200 or str(send_data.get("responseCode")) != "200":
            logging.error(f"sendOtp failed: {send_resp.status_code} {send_data}")
            notify(
                "❌ *Could not send OTP.*\n\n"
                "Please check the number and try again.\n"
                "No credits were deducted."
            )
            return

        # OTP sent – start timer message
        async def send_timer_msg():
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="🔐 OTP Sent!\nPlease enter the OTP within 30 seconds.",
                parse_mode="Markdown",
                reply_markup=main_reply_keyboard
            )
            return msg.message_id

        timer_msg_id = asyncio.run_coroutine_threadsafe(send_timer_msg(), loop).result()
        context.user_data['gemini_timer_msg_id'] = timer_msg_id

        # ---------- 2. Wait for OTP with timer (max 30 seconds) ----------
        max_seconds = 30
        otp_received = None
        for remaining in range(max_seconds, 0, -1):
            if context.user_data.get('gemini_cancelled'):
                timer_id = context.user_data.pop('gemini_timer_msg_id', None)
                if timer_id:
                    asyncio.run_coroutine_threadsafe(
                        context.bot.delete_message(chat_id=chat_id, message_id=timer_id),
                        loop
                    )
                asyncio.run_coroutine_threadsafe(
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="⛔ Operation cancelled by user.",
                        reply_markup=main_reply_keyboard
                    ),
                    loop
                )
                context.user_data.pop('gemini_step', None)
                context.user_data.pop('jio_otp', None)
                return

            if context.user_data.get('jio_otp'):
                otp_received = context.user_data['jio_otp']
                break

            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=timer_msg_id,
                    text=f"🔐 OTP Sent!\nPlease enter the OTP.\n⏳ Time remaining: **{remaining}** seconds",
                    parse_mode="Markdown",
                    reply_markup=main_reply_keyboard
                ),
                loop
            )
            time.sleep(1)

        if context.user_data.get('gemini_cancelled'):
            timer_id = context.user_data.pop('gemini_timer_msg_id', None)
            if timer_id:
                asyncio.run_coroutine_threadsafe(
                    context.bot.delete_message(chat_id=chat_id, message_id=timer_id),
                    loop
                )
            context.user_data.pop('gemini_step', None)
            context.user_data.pop('jio_otp', None)
            return

        if not otp_received:
            timer_id = context.user_data.pop('gemini_timer_msg_id', None)
            if timer_id:
                asyncio.run_coroutine_threadsafe(
                    context.bot.delete_message(chat_id=chat_id, message_id=timer_id),
                    loop
                )
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(
                    chat_id=chat_id,
                    text="⏰ OTP timeout. Please try again later.",
                    reply_markup=main_reply_keyboard
                ),
                loop
            )
            context.user_data.pop('gemini_step', None)
            context.user_data.pop('jio_otp', None)
            return

        # OTP received – delete timer message
        timer_id = context.user_data.pop('gemini_timer_msg_id', None)
        if timer_id:
            asyncio.run_coroutine_threadsafe(
                context.bot.delete_message(chat_id=chat_id, message_id=timer_id),
                loop
            )

        # ---------- 4. Validate OTP ----------
        try:
            validate_resp = session.post(
                JIO_VALIDATE_OTP_URL,
                json={"otp": otp_received},
                timeout=30
            )
            try:
                validate_data = validate_resp.json()
            except ValueError:
                validate_data = {}
        except Exception as e:
            logging.error(f"validateOtp error: {e}")
            notify("❌ Unable to reach Jio server to verify OTP. Please try again later.\nNo credits were deducted.")
            return

        if validate_resp.status_code != 200 or validate_data.get("errorCode"):
            notify("❌ *Invalid OTP!*\nPlease try again from start.\nNo credits were deducted.")
            return

        # ---------- 5. Proceed to Gemini link ----------
        notify("🔍 *Finding Gemini Subscription Link...*")
        session.headers.update({"Referer": "https://www.jio.com/selfcare/googleai/"})

        # 5a. activate
        activate_msg = ""
        try:
            act_resp = session.get(JIO_ACTIVATE_URL, timeout=30)
            logging.info(f"activate response {act_resp.status_code}: {act_resp.text[:1500]}")
            try:
                act_body = act_resp.json()
            except ValueError:
                act_body = {}
            activate_msg = str(act_body.get("errorMessage") or "").upper()
        except Exception as e:
            logging.error(f"activate error: {e}")

        if "ALREADY_EXISTS" in activate_msg:
            notify(
                "⚠️ *Offer Already Claimed*\n\n"
                "The Gemini offer has already been activated on this number, so "
                "there is no new claim link to generate.\nNo credits were deducted."
            )
            return
        if "LEAD_GENERATED" in activate_msg:
            notify(
                "❌ *Number Not Eligible*\n\n"
                "This number is not currently eligible for the Gemini offer "
                "(it needs an active qualifying Jio plan).\nNo credits were deducted."
            )
            return

        # 5b. google-ai
        gemini_link = None
        ga_msg = ""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ga_resp = session.get(JIO_GOOGLE_AI_URL, timeout=30)
                logging.info(f"google-ai response {ga_resp.status_code}: {ga_resp.text[:1500]}")
                try:
                    ga_body = ga_resp.json()
                except ValueError:
                    ga_body = {}
                ga_msg = str(ga_body.get("errorMessage") or "")
                if ga_resp.status_code == 200:
                    gemini_link = _extract_redirection_url(ga_body)
                    if gemini_link:
                        try:
                            session.get(JIO_GOOGLE_AI_SUBMIT_URL, timeout=30)
                        except Exception as e:
                            logging.error(f"google-ai submit error: {e}")
                else:
                    logging.error(f"google-ai failed: {ga_resp.status_code} {ga_body}")
                break
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    notify("⏰ *Jio server is taking too long to respond.*\nPlease try again in a few moments.\nNo credits were deducted.")
                    return
                time.sleep(2)
                continue
            except Exception as e:
                logging.error(f"google-ai fetch error: {e}")
                notify(f"❌ *Error fetching link:* {str(e)[:100]}\nNo credits were deducted.")
                return

        if gemini_link:
            short_link = shorten_url(gemini_link)
            user_id = update.effective_user.id
            save_gemini_link(user_id, gemini_link, short_link)
            deduct_credit(user_id)
            notify(
                f"✅ *Gemini subscription link found*\n\n"
                f"🔗 *Your Link:*\n`{short_link}`\n\n"
                "You can use this link.\n\n"
                "1 credit has been deducted for this request."
            )
        else:
            reason = f"\n(Jio said: {ga_msg})" if ga_msg and ga_msg.upper() != "SUCCESS" else ""
            notify(
                "❌ *Gemini Subscription Link Not Found*\n\n"
                "This number may have already claimed the offer or is not "
                "eligible for it right now, so Jio returned no claim link."
                f"{reason}\nNo credits were deducted."
            )

    except Exception as e:
        logging.error(f"Jio API Error: {e}")
        notify(f"❌ *Error:* {str(e)[:150]}\n\nNo credits were deducted.")
    finally:
        context.user_data.pop('jio_otp', None)
        context.user_data.pop('gemini_step', None)
        context.user_data.pop('gemini_cancelled', None)
        context.user_data.pop('gemini_timer_msg_id', None)

# ------------------ SUPPORT SYSTEM ------------------
async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    user = get_user(user_id)
    if not user:
        await message.reply_text("Please /start the bot first.")
        return

    if user[6] == 0:
        await send_join_prompt(update, context)
        return

    context.user_data['support_mode'] = True
    await message.reply_text(
        "📩 *Support*\n\n"
        "Please type your question or send a photo/file/voice/video/audio.\n"
        "Our support team will get back to you shortly.",
        parse_mode="Markdown",
        reply_markup=main_reply_keyboard
    )

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('support_mode', False):
        user_id = update.effective_user.id
        user = get_user(user_id)
        name = user[7] if user else "Unknown"
        message = update.message.text

        for admin_id in ADMIN_USER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"📨 *New Support Message*\n"
                        f"From: User `{user_id}` ({name})\n"
                        f"Message:\n{message}\n\n"
                        f"Reply using: `/reply {user_id} <your message>`"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Failed to send support message to admin {admin_id}: {e}")

        await update.message.reply_text(
            "✅ Your message has been sent to support.\n"
            "We'll get back to you as soon as possible.",
            reply_markup=main_reply_keyboard
        )
        context.user_data.pop('support_mode', None)

async def support_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('support_mode', False):
        return

    user_id = update.effective_user.id
    user = get_user(user_id)
    name = user[7] if user else "Unknown"
    message = update.message

    for admin_id in ADMIN_USER_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"📨 *New Support Message (Media)*\n"
                    f"From: User `{user_id}` ({name})\n"
                    f"Media type: {message.effective_attachment.__class__.__name__}\n"
                    f"Caption: {message.caption or 'None'}"
                ),
                parse_mode="Markdown"
            )
            await message.forward(chat_id=admin_id)
        except Exception as e:
            logging.error(f"Failed to send support media to admin {admin_id}: {e}")

    await update.message.reply_text(
        "✅ Your media message has been sent to support.\n"
        "We'll get back to you as soon as possible.",
        reply_markup=main_reply_keyboard
    )
    context.user_data.pop('support_mode', None)

# ------------------ ADMIN REPLY ------------------
async def reply_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /reply <user_id> <message>")
        return

    target_id = int(args[0])
    reply_text = " ".join(args[1:])

    user = get_user(target_id)
    if not user:
        await update.message.reply_text(f"User {target_id} not found.")
        return

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"📩 *Reply from Support:*\n\n{reply_text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Reply sent to user {target_id}.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send reply: {e}")

# ------------------ ADMIN COMMANDS ------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return
    total_users = get_total_users()
    total_credits = get_total_credits()
    bonus = get_credits_per_referral()
    text = (
        f"📊 *Bot Statistics*\n"
        f"Total Users: {total_users}\n"
        f"Total Credits in System: {total_credits}\n"
        f"Credits per Referral: {bonus}"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_reply_keyboard)

async def reset_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /reset_credits <user_id>")
        return
    target_id = int(args[0])
    reset_user_credits(target_id)
    await update.message.reply_text(f"Credits for user {target_id} have been reset to 0.")

async def list_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, full_name, ref_code, credits, refer_count, join_date FROM users ORDER BY join_date DESC")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No users registered yet.")
        return

    content = "📋 FULL USER LIST (with Names)\n"
    content += "="*70 + "\n"
    content += f"{'User ID':<12} | {'Name':<20} | {'Ref Code':<8} | {'Credits':<7} | {'Refs':<4} | Join Date\n"
    content += "-"*70 + "\n"
    for uid, name, ref, credits, refs, joined in rows:
        name_display = (name or 'N/A')[:20]
        content += f"{uid:<12} | {name_display:<20} | {ref:<8} | {credits:<7} | {refs:<4} | {joined[:10]}\n"

    file_obj = io.BytesIO(content.encode('utf-8'))
    file_obj.name = "users_with_names.txt"
    await update.message.reply_document(
        document=file_obj,
        filename="users_with_names.txt",
        caption=f"✅ Total Users: {len(rows)}"
    )

    print("\n" + "="*70)
    print("📋 USER LIST (with Names) - Printed in Console")
    print("="*70)
    print(content)

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removeuser <user_id>")
        return
    target_id = int(args[0])
    user = get_user(target_id)
    if not user:
        await update.message.reply_text(f"User {target_id} not found.")
        return
    delete_user(target_id)
    await update.message.reply_text(f"User {target_id} has been removed from the system.")

async def add_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")
        return
    try:
        target_id = int(args[0])
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("Please provide a valid user ID and amount (integer).")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be a positive integer.")
        return

    user = get_user(target_id)
    if not user:
        await update.message.reply_text(f"User {target_id} not found.")
        return

    add_credits(target_id, amount)
    new_credits = user[2] + amount
    await update.message.reply_text(
        f"✅ Added {amount} credits to user {target_id}.\n"
        f"New balance: {new_credits} credits."
    )

async def add_all_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /addallcredits <amount>")
        return
    try:
        amount = int(args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid integer amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be a positive integer.")
        return

    total_users = get_total_users()
    if total_users == 0:
        await update.message.reply_text("No users registered to add credits.")
        return

    add_all_credits(amount)
    await update.message.reply_text(
        f"✅ Added {amount} credits to ALL {total_users} users.\n"
        f"Total credits distributed: {amount * total_users}."
    )

async def set_referral_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ Unauthorized.")
        return

    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /set_referral_credits <amount>")
        return

    try:
        amount = int(args[0])
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please provide a non‑negative integer.")
        return

    set_credits_per_referral(amount)
    await update.message.reply_text(f"✅ Referral credits per referral set to **{amount}**.")

# ------------------ GET DATABASE COMMAND (ADMIN ONLY) ------------------
async def get_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Only admins can download the database
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    try:
        # Check if database file exists
        if not os.path.exists(DB_NAME):
            await update.message.reply_text("❌ Database file not found!")
            return
        
        # Send the database file
        with open(DB_NAME, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename="users.db",
                caption=f"📊 Database backup\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📁 Size: {os.path.getsize(DB_NAME)} bytes"
            )
        print(f"✅ Database sent to admin {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending database: {str(e)[:100]}")
        logging.error(f"get_db error: {e}")

# ------------------ UPLOAD DATABASE COMMAND (ADMIN ONLY) ------------------
async def upload_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Only admins can upload the database
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    # Check if a file is attached
    if not update.message.document:
        await update.message.reply_text(
            "❌ Please send a file.\n"
            "Usage: Send a .db file with caption /uploaddb"
        )
        return
    
    # Check if it's a .db file
    file_name = update.message.document.file_name
    if not file_name.endswith('.db'):
        await update.message.reply_text(
            "❌ Please send a valid .db file."
        )
        return
    
    try:
        # Download the file
        file = await update.message.document.get_file()
        temp_path = f"/tmp/{file_name}"
        await file.download_to_drive(temp_path)
        
        # Check if file is valid SQLite database
        try:
            conn = sqlite3.connect(temp_path)
            conn.execute("SELECT 1 FROM users LIMIT 1")
            conn.close()
        except Exception as e:
            await update.message.reply_text(
                f"❌ Invalid database file: {str(e)[:100]}"
            )
            os.remove(temp_path)
            return
        
        # Backup old database
        if os.path.exists(DB_NAME):
            backup_name = f"{DB_NAME}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(DB_NAME, backup_name)
            await update.message.reply_text(f"✅ Old database backed up as: {backup_name}")
        
        # Replace with new database
        shutil.move(temp_path, DB_NAME)
        
        await update.message.reply_text(
            f"✅ Database updated successfully!\n"
            f"📁 New database: {file_name}\n"
            f"📅 Updated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"✅ Database uploaded by admin {user_id}")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error uploading database: {str(e)[:100]}")
        logging.error(f"upload_db error: {e}")

# ------------------ BROADCAST COMMAND ------------------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("You are not authorized.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /broadcast <your message>")
        return

    message_text = " ".join(args)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No users registered yet.")
        return

    total = len(rows)
    sent = 0
    failed = 0

    for (uid,) in rows:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=message_text,
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            failed += 1
            logging.error(f"Broadcast failed for user {uid}: {e}")
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ Broadcast completed.\n"
        f"Sent: {sent}\n"
        f"Failed: {failed}\n"
        f"Total users: {total}"
    )

# ------------------ MAIN TEXT HANDLER ------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if context.user_data.get('gemini_step') in ['awaiting_mobile', 'awaiting_otp']:
        if text in ["🔵 Gemini", "🔴 Profile", "🟢 Refer", "🟡 Support", "📜 History", "🏆 Leaderboard"]:
            context.user_data['gemini_cancelled'] = True
            context.user_data.pop('gemini_step', None)
            context.user_data.pop('jio_otp', None)
        else:
            if text.isdigit():
                await gemini_mobile_handler(update, context)
            else:
                await update.message.reply_text(
                    "Please enter a 10-digit number or press a main menu button to cancel.",
                    reply_markup=main_reply_keyboard
                )
            return

    if context.user_data.get('support_mode', False):
        await support_message(update, context)
        return

    if text.isdigit() and len(text) >= 4:
        await update.message.reply_text(
            "⏰ OTP session expired. Please click 🔵 Gemini again to start a new request.",
            reply_markup=main_reply_keyboard
        )
        return

    if text == "🔵 Gemini":
        await gemini_handler(update, context)
    elif text == "🔴 Profile":
        await profile(update, context)
    elif text == "🟢 Refer":
        await refer(update, context)
    elif text == "🟡 Support":
        await support_button(update, context)
    elif text == "📜 History":
        await history(update, context)
    elif text == "🏆 Leaderboard":
        await leaderboard(update, context)
    else:
        await update.message.reply_text(
            "कृपया नीचे दिए गए बटनों का उपयोग करें।",
            reply_markup=main_reply_keyboard
        )

# ------------------ SETUP COMMANDS ------------------
async def setup_commands(app):
    default_commands = [
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("leaderboard", "🏆 Top 10 users"),
    ]
    admin_commands = [
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("leaderboard", "🏆 Top 10 users"),
        BotCommand("stats", "📊 Bot statistics"),
        BotCommand("reset_credits", "🔄 Reset user credits"),
        BotCommand("allusers", "📋 Get full user list"),
        BotCommand("removeuser", "❌ Remove a user"),
        BotCommand("addcredits", "➕ Add credits to a user"),
        BotCommand("addallcredits", "➕ Add credits to all users"),
        BotCommand("reply", "💬 Reply to a user's support message"),
        BotCommand("broadcast", "📢 Send a message to all users"),
        BotCommand("set_referral_credits", "⚙️ Change referral bonus amount"),
        BotCommand("getdb", "📥 Download database file"),
        BotCommand("uploaddb", "📤 Upload database file (send .db file)"),
    ]
    await app.bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())
    for admin_id in ADMIN_USER_IDS:
        await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
    print("✅ Bot commands configured.")

async def post_init(app):
    await setup_commands(app)
    await check_and_broadcast_update(app)

# ------------------ MAIN ------------------
def main():
    print("Script is created by Rahul Mahipal")
    
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset_credits", reset_credits))
    app.add_handler(CommandHandler("allusers", list_all_users))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(CommandHandler("addcredits", add_credits_command))
    app.add_handler(CommandHandler("addallcredits", add_all_credits_command))
    app.add_handler(CommandHandler("reply", reply_user))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("set_referral_credits", set_referral_credits))
    app.add_handler(CommandHandler("getdb", get_db))
    app.add_handler(CommandHandler("uploaddb", upload_db))

    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(refer_back_callback, pattern="^refer_back$"))

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL | filters.VOICE | filters.VIDEO | filters.AUDIO,
            support_media_handler
        )
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.post_init = post_init

    print("✅ Bot running with all updates (auto-delete, referral config, history, auto-broadcast).")
    app.run_polling()

if __name__ == "__main__":
    main()
