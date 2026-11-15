"""
Force-Join Redirect Bot
- /start -> user ko aapke saare (support) channels ke Join buttons dikhte hain
- "Claim" dabane par bot check karta hai ki user ne sab channels join kiye ya nahi
- Sab join hone ke baad user ko MAIN channel ka link milta hai (jahan saara content hai)

Setup: neeche "YAHAN APNI SETTINGS BHARO" wale hisse me token, admin id, 2 channels
(id + link) aur main channel ka link bharo. Bot ko dono channels me ADMIN banao.
(Main channel ko CHANNELS me mat daalna - uska sirf link chahiye.)
"""
import asyncio
import logging
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("joinbot")

# =====================  YAHAN APNI SETTINGS BHARO  =====================
BOT_TOKEN = "9151808699:AAE__Hj5ZJV8BJZrF3HsXayDiQN0GoJDcV8"          # @BotFather se mila token
ADMIN_IDS = {9151808699}                      # apni Telegram numeric ID (@userinfobot se)
MAIN_CHANNEL_LINK = "https://t.me/Thunber_Anime_Hindi_95"   # main content channel ka link

# Sirf 2 channels join karwane hain: Chat channel aur Movies channel
CHANNELS = [
    {"id": -1004447969394, "link": "https://t.me/Crunchyroll_Discuss",   "title": "Chat Channel"},
    {"id": , -1003076552128"link": "https://t.me/animemoviesmarathon", "title": "Movies Channel"},
]
DB_PATH = "bot.db"
# =======================================================================

# (Optional) server par environment variables set karoge to wo upar wali settings ko override kar denge
BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN)
MAIN_CHANNEL_LINK = os.getenv("MAIN_CHANNEL_LINK", MAIN_CHANNEL_LINK)
DB_PATH = os.getenv("DB_PATH", DB_PATH)
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS").split(",") if x.strip()}


def parse_channels(raw: str):
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        cid, link, *title = [p.strip() for p in part.split("|")]
        out.append({"id": int(cid), "link": link, "title": title[0] if title else "Join"})
    return out


if os.getenv("FORCE_CHANNELS"):
    CHANNELS = parse_channels(os.getenv("FORCE_CHANNELS"))

# ---------------------------------------------------------------- database
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, first_name TEXT, verified INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0, joined_at INTEGER)""")
db.commit()


def upsert_user(uid, name):
    db.execute("INSERT OR IGNORE INTO users(user_id, first_name, joined_at) VALUES(?,?,?)",
               (uid, name, int(time.time())))
    db.execute("UPDATE users SET blocked=0 WHERE user_id=?", (uid,))
    db.commit()


def set_verified(uid, val):
    db.execute("UPDATE users SET verified=? WHERE user_id=?", (1 if val else 0, uid))
    db.commit()


def set_blocked(uid):
    db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))
    db.commit()


# ---------------------------------------------------------------- helpers
async def missing_channels(bot, uid):
    """Wo channels jinhe user ne abhi join nahi kiya."""
    missing = []
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch["id"], uid)
            ok = m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                              ChatMemberStatus.OWNER) or (
                m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False))
        except TelegramError as e:
            log.warning("get_chat_member failed for %s: %s (bot channel me admin hai?)", ch["id"], e)
            ok = False
        if not ok:
            missing.append(ch)
    return missing


def join_keyboard(channels):
    rows, row = [], []
    for ch in channels:
        row.append(InlineKeyboardButton(f"➕ {ch['title']}", url=ch["link"]))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Claim", callback_data="claim")])
    return InlineKeyboardMarkup(rows)


MAIN_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🎬 Open Main Channel", url=MAIN_CHANNEL_LINK)]])
VERIFIED_TEXT = "🎉 Verified!\n\nAb niche button dabao aur Main Channel join karo, saara content wahin hai 👇"


# ---------------------------------------------------------------- handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.first_name)
    missing = await missing_channels(context.bot, u.id)
    if missing:
        set_verified(u.id, False)
        await update.message.reply_text(
            f"👋 Hey {u.first_name}!\n\nPehle niche diye saare channels Join karo, "
            "phir ✅ Claim dabao.",
            reply_markup=join_keyboard(CHANNELS))
    else:
        set_verified(u.id, True)
        await update.message.reply_text(VERIFIED_TEXT, reply_markup=MAIN_KEYBOARD)


async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    upsert_user(u.id, u.first_name)
    missing = await missing_channels(context.bot, u.id)
    if missing:
        set_verified(u.id, False)
        await q.answer("❌ Abhi saare channels join nahi kiye!", show_alert=True)
        try:
            await q.edit_message_reply_markup(join_keyboard(missing))
        except TelegramError:
            pass
        return
    set_verified(u.id, True)
    await q.answer("✅ Verified!")
    await q.edit_message_text(VERIFIED_TEXT, reply_markup=MAIN_KEYBOARD)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    ver = db.execute("SELECT COUNT(*) FROM users WHERE verified=1 AND blocked=0").fetchone()[0]
    await update.message.reply_text(f"👥 Total users: {total}\n✅ Verified (active): {ver}")


async def bc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: kisi bhi message ko reply karke /broadcast likho -> sab verified users ko jayega."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    src = update.message.reply_to_message
    if not src:
        await update.message.reply_text("Jis message ko bhejna hai, usko reply karke /broadcast likho.")
        return
    users = db.execute("SELECT user_id FROM users WHERE verified=1 AND blocked=0").fetchall()

    async def run():
        n = 0
        for (uid,) in users:
            try:
                await context.bot.copy_message(uid, src.chat_id, src.message_id)
                n += 1
            except Forbidden:
                set_blocked(uid)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramError:
                pass
            await asyncio.sleep(0.05)
        await update.message.reply_text(f"Broadcast done: {n}/{len(users)} users.")

    context.application.create_task(run())
    await update.message.reply_text(f"Broadcast shuru: {len(users)} users.")


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def keep_alive():
    """Render Web Service ke liye chhota web-port (UptimeRobot isse ping karega)."""
    port = int(os.getenv("PORT", "10000"))
    srv = HTTPServer(("0.0.0.0", port), _Ping)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("ping server on port %s", port)


def main():
    keep_alive()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", bc))
    app.add_handler(CallbackQueryHandler(claim, pattern="^claim$"))
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
