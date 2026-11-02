"""Spot Claim: Telegram webhook bot on FastAPI (Vercel-friendly).
State lives in Redis (Upstash REST), because serverless keeps no memory."""
import os, json, secrets, hmac
import httpx
from fastapi import FastAPI, Request, Header, HTTPException
import adapters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
BASE = os.getenv("APP_BASE_URL", "").rstrip("/")
KV_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL", "")
KV_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
TG = f"https://api.telegram.org/bot{TOKEN}"

app = FastAPI()

WELCOME = ("Welcome to Spot Claim 🚀\n\nNever miss a limited campaign spot again.\n\n"
           "Connect your campaign platform, activate monitoring, and let Spot Claim "
           "watch for new opportunities.")

MENU = {"inline_keyboard": [
    [{"text": "Connect Website", "callback_data": "connect"},
     {"text": "My Accounts", "callback_data": "accounts"}],
    [{"text": "Start Monitoring", "callback_data": "monitor"},
     {"text": "My Claims", "callback_data": "claims"}],
    [{"text": "Settings", "callback_data": "settings"},
     {"text": "Help", "callback_data": "help"}],
]}

# ---- Redis (Upstash REST) ----
async def kv(*cmd):
    if not KV_URL:
        return None
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(KV_URL, json=list(cmd),
                         headers={"Authorization": f"Bearer {KV_TOKEN}"})
        return r.json().get("result")

# ---- Telegram ----
async def send(chat_id, text, markup=None):
    body = {"chat_id": chat_id, "text": text}
    if markup:
        body["reply_markup"] = markup
    async with httpx.AsyncClient(timeout=8) as c:
        await c.post(f"{TG}/sendMessage", json=body)

async def answer_cb(cb_id):
    async with httpx.AsyncClient(timeout=8) as c:
        await c.post(f"{TG}/answerCallbackQuery", json={"callback_query_id": cb_id})

# ---- Handlers ----
async def on_button(chat_id, data):
    if data == "connect":
        await kv("SET", f"state:{chat_id}", "awaiting_url", "EX", 600)
        await send(chat_id, "Send me the website link you want to connect.")
    elif data == "accounts":
        await send(chat_id, "No connected accounts yet. Tap Connect Website.")
    elif data == "monitor":
        await send(chat_id, "Connect an account first, then monitoring can be started.")
    elif data == "claims":
        await send(chat_id, "No claims yet.")
    elif data == "settings":
        await send(chat_id, "Settings are coming soon.")
    elif data == "help":
        await send(chat_id,
            "1. Connect Website: send a campaign site link.\n"
            "2. Authorize securely via the link I give you.\n"
            "3. Start Monitoring.\n\nI never ask for your password in chat.")

async def on_text(chat_id, text):
    if text.startswith("/start"):
        await kv("DEL", f"state:{chat_id}")
        return await send(chat_id, WELCOME, MENU)
    if await kv("GET", f"state:{chat_id}") != "awaiting_url":
        return await send(chat_id, "Use the menu below.", MENU)
    domain = adapters.normalize(text)
    if not domain:
        return await send(chat_id, "That doesn't look like a valid link. Try again.")
    await kv("DEL", f"state:{chat_id}")
    info = adapters.lookup(domain)
    if not info:
        return await send(chat_id,
            f"{domain} isn't supported yet. It needs a dedicated integration "
            "before automation can work.", MENU)
    token = secrets.token_urlsafe(24)
    await kv("SET", f"connect:{token}", json.dumps({"chat": chat_id, "domain": domain}), "EX", 600)
    link = f"{BASE}/connect/{info['name'].lower()}?t={token}"
    await send(chat_id,
        f"{info['name']} is supported ✅\n\nTap below to authorize securely. "
        "Never send your password here.",
        {"inline_keyboard": [[{"text": "Authorize securely", "url": link}]]})

# ---- Routes ----
@app.get("/")
async def health():
    return {"app": "Spot Claim", "status": "ok"}

@app.post("/webhook")
async def webhook(req: Request,
                  x_telegram_bot_api_secret_token: str = Header(default="")):
    if not WEBHOOK_SECRET or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, WEBHOOK_SECRET):
        raise HTTPException(status_code=403)
    try:
        u = await req.json()
        if "callback_query" in u:
            cb = u["callback_query"]
            await answer_cb(cb["id"])
            await on_button(cb["message"]["chat"]["id"], cb.get("data", ""))
        elif "message" in u and "text" in u["message"]:
            m = u["message"]
            await on_text(m["chat"]["id"], m["text"])
    except Exception as e:  # always 200 so Telegram doesn't retry-storm
        print("webhook error:", type(e).__name__)
    return {"ok": True}

@app.get("/setup")
async def setup(secret: str = ""):
    """Open once after deploy: /setup?secret=<TELEGRAM_WEBHOOK_SECRET>"""
    if not WEBHOOK_SECRET or not hmac.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{TG}/setWebhook", json={
            "url": f"{BASE}/webhook", "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message", "callback_query"]})
    return r.json()
