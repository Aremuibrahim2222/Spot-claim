import os, secrets, logging
from dotenv import load_dotenv
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
import adapters

load_dotenv()
logging.basicConfig(level=logging.INFO)
BASE = os.getenv("APP_BASE_URL", "")

WELCOME = ("Welcome to Spot Claim 🚀\n\nNever miss a limited campaign spot again.\n\n"
           "Connect your campaign platform, activate monitoring, and let Spot Claim "
           "watch for new opportunities.")

MENU = M([
    [B("Connect Website", callback_data="connect"), B("My Accounts", callback_data="accounts")],
    [B("Start Monitoring", callback_data="monitor"), B("My Claims", callback_data="claims")],
    [B("Settings", callback_data="settings"), B("Help", callback_data="help")],
])

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    c.user_data.clear()
    await u.effective_message.reply_text(WELCOME, reply_markup=MENU)

async def on_button(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d = q.data
    if d == "connect":
        c.user_data["awaiting_url"] = True
        await q.message.reply_text("Send me the website link you want to connect.")
    elif d == "accounts":
        await q.message.reply_text("No connected accounts yet. Tap Connect Website.")
    elif d == "monitor":
        await q.message.reply_text("Connect an account first, then monitoring can be started.")
    elif d == "claims":
        await q.message.reply_text("No claims yet.")
    elif d == "settings":
        await q.message.reply_text("Settings are coming soon.")
    elif d == "help":
        await q.message.reply_text(
            "1. Connect Website: send a campaign site link.\n"
            "2. Authorize securely via the link I give you.\n"
            "3. Start Monitoring.\n\n"
            "I never ask for your password in chat.")

async def on_text(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.user_data.get("awaiting_url"):
        await u.message.reply_text("Use the menu below.", reply_markup=MENU)
        return
    domain = adapters.normalize(u.message.text)
    if not domain:
        await u.message.reply_text("That doesn't look like a valid link. Try again.")
        return
    c.user_data["awaiting_url"] = False
    info = adapters.lookup(domain)
    if not info:
        await u.message.reply_text(
            f"{domain} isn't supported yet. It needs a dedicated integration "
            "before automation can work.", reply_markup=MENU)
        return
    # One-time, expiring token. Store server-side (DB/Redis) with user id + domain.
    token = secrets.token_urlsafe(24)
    link = f"{BASE}/connect/{info['name'].lower()}?t={token}"
    await u.message.reply_text(
        f"{info['name']} is supported ✅\n\nTap below to authorize securely. "
        "Never send your password here.",
        reply_markup=M([[B("Authorize securely", url=link)]]))

def main():
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
