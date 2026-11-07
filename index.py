"""Spot Claim: instant campaign alerts on Telegram (FastAPI on Vercel).
No logins, no passwords. A campaign is announced via POST /notify (from SubsGigs)
or by the admin with /drop in the bot, then broadcast to all subscribers."""
import os, json, hmac, asyncio
import httpx
from fastapi import FastAPI, Request, Header, HTTPException

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
NOTIFY_SECRET = os.getenv("NOTIFY_SECRET", "")
ADMIN = os.getenv("ADMIN_CHAT_ID", "")
BASE = os.getenv("APP_BASE_URL", "").rstrip("/")
KV_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL", "")
KV_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
TG = f"https://api.telegram.org/bot{TOKEN}"

app = FastAPI()

WELCOME = ("Welcome to Spot Claim 🚀\n\nNever miss a limited campaign spot again.\n\n"
           "Turn on alerts and I'll message you the moment a new SubsGigs campaign "
           "drops, with a direct link so you can claim your spot first.")

MENU = {"inline_keyboard": [
    [{"text": "🔔 Turn On Alerts", "callback_data": "on"},
     {"text": "🔕 Turn Off Alerts", "callback_data": "off"}],
    [{"text": "Latest Campaign", "callback_data": "latest"},
     {"text": "Help", "callback_data": "help"}],
]}

async def kv(*cmd):
    if not KV_URL:
        return None
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(KV_URL, json=list(cmd),
                         headers={"Authorization": f"Bearer {KV_TOKEN}"})
        return r.json().get("result")

async def send(chat_id, text, markup=None, client=None):
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if markup:
        body["reply_markup"] = markup
    if client:
        return await client.post(f"{TG}/sendMessage", json=body)
    async with httpx.AsyncClient(timeout=8) as c:
        return await c.post(f"{TG}/sendMessage", json=body)

def alert_text(name, link, spots=""):
    extra = f"\nSpots: {spots}" if spots else ""
    return (f"🚨 NEW CAMPAIGN DROPPED\n\nCampaign: {name}{extra}\n"
            "Spots are first-come, so move fast.\n\nOpen campaign: " + link)

async def broadcast(name, link, spots=""):
    """Send to every subscriber in parallel batches. Skips duplicates."""
    fresh = await kv("SET", f"seen:{link}", "1", "NX", "EX", 86400)
    if not fresh:
        return {"sent": 0, "duplicate": True}
    await kv("SET", "latest", json.dumps({"name": name, "link": link, "spots": spots}))
    subs = await kv("SMEMBERS", "subs") or []
    text = alert_text(name, link, spots)
    markup = {"inline_keyboard": [[{"text": "Open campaign", "url": link}]]}
    sent = 0
    async with httpx.AsyncClient(timeout=10) as c:
        for i in range(0, len(subs), 25):  # stay under Telegram's ~30 msg/s limit
            batch = subs[i:i + 25]
            res = await asyncio.gather(*[send(s, text, markup, c) for s in batch],
                                       return_exceptions=True)
            for s, r in zip(batch, res):
                if isinstance(r, Exception):
                    continue
                if r.status_code == 200:
                    sent += 1
                elif r.status_code == 403:  # user blocked the bot
                    await kv("SREM", "subs", s)
            if i + 25 < len(subs):
                await asyncio.sleep(1)
    return {"sent": sent, "duplicate": False}

def clean(name, link):
    name = (name or "").strip()[:120]
    link = (link or "").strip()
    if not name or not link.startswith("https://"):
        return None
    return name, link

async def on_button(chat_id, data):
    if data == "on":
        await kv("SADD", "subs", str(chat_id))
        await send(chat_id, "🔔 Alerts are ON. I'll message you the moment a campaign drops.", MENU)
    elif data == "off":
        await kv("SREM", "subs", str(chat_id))
        await send(chat_id, "🔕 Alerts are OFF.", MENU)
    elif data == "latest":
        raw = await kv("GET", "latest")
        if not raw:
            return await send(chat_id, "No campaign has been announced yet.", MENU)
        l = json.loads(raw)
        await send(chat_id, alert_text(l["name"], l["link"], l.get("spots", "")),
                   {"inline_keyboard": [[{"text": "Open campaign", "url": l["link"]}]]})
    elif data == "help":
        await send(chat_id, "Tap Turn On Alerts. When a new SubsGigs campaign drops you'll get a "
                            "message with a direct link. Log in and claim your spot yourself.")

async def on_text(chat_id, text):
    if text.startswith("/start"):
        return await send(chat_id, WELCOME, MENU)
    if text.startswith("/id"):
        return await send(chat_id, f"Your chat ID: {chat_id}")
    if text.startswith("/drop"):
        if not ADMIN or str(chat_id) != ADMIN:
            return await send(chat_id, "Not allowed.")
        parts = text[5:].split("|")
        c = clean(parts[0], parts[1] if len(parts) > 1 else "")
        if not c:
            return await send(chat_id, "Use: /drop Campaign name | https://link")
        r = await broadcast(c[0], c[1], parts[2].strip() if len(parts) > 2 else "")
        return await send(chat_id, "Already announced." if r["duplicate"] else f"Sent to {r['sent']} subscribers.")
    await send(chat_id, "Use the menu below.", MENU)

@app.get("/")
async def health():
    return {"app": "Spot Claim", "status": "ok"}

@app.post("/notify")
async def notify(req: Request, x_notify_secret: str = Header(default="")):
    """SubsGigs (or you) calls this when a campaign is published."""
    if not NOTIFY_SECRET or not hmac.compare_digest(x_notify_secret, NOTIFY_SECRET):
        raise HTTPException(status_code=403)
    d = await req.json()
    c = clean(d.get("name"), d.get("link"))
    if not c:
        raise HTTPException(status_code=422, detail="name and https link required")
    return await broadcast(c[0], c[1], str(d.get("spots", ""))[:20])

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
            async with httpx.AsyncClient(timeout=8) as c:
                await c.post(f"{TG}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
            await on_button(cb["message"]["chat"]["id"], cb.get("data", ""))
        elif "message" in u and "text" in u["message"]:
            m = u["message"]
            await on_text(m["chat"]["id"], m["text"])
    except Exception as e:
        print("webhook error:", type(e).__name__)
    return {"ok": True}

@app.get("/setup")
async def setup(secret: str = ""):
    if not WEBHOOK_SECRET or not hmac.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{TG}/setWebhook", json={
            "url": f"{BASE}/webhook", "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message", "callback_query"]})
    return r.json()
