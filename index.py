"""Spot Claim: Telegram webhook bot + secure connect page (FastAPI on Vercel).
State lives in Redis (Upstash REST). Passwords are used in memory once and never stored or logged."""
import os, json, secrets, hmac, html
from urllib.parse import parse_qs
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse
import adapters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
BASE = os.getenv("APP_BASE_URL", "").rstrip("/")
ENC_KEY = os.getenv("ENCRYPTION_KEY", "")
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

# ---- Encryption ----
def enc(obj: dict) -> str:
    return Fernet(ENC_KEY.encode()).encrypt(json.dumps(obj).encode()).decode()

def dec(s: str) -> dict:
    return json.loads(Fernet(ENC_KEY.encode()).decrypt(s.encode()))

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

# ---- Bot handlers ----
async def on_button(chat_id, data):
    if data == "connect":
        await kv("SET", f"state:{chat_id}", "awaiting_url", "EX", 600)
        await send(chat_id, "Send me the website link you want to connect.")
    elif data == "accounts":
        slugs = await kv("SMEMBERS", f"accounts:{chat_id}") or []
        if not slugs:
            return await send(chat_id, "No connected accounts yet. Tap Connect Website.")
        rows = [[{"text": f"Disconnect {adapters.BY_SLUG[s].name}", "callback_data": f"disc:{s}"}]
                for s in slugs if s in adapters.BY_SLUG]
        await send(chat_id, "Your connected accounts:", {"inline_keyboard": rows})
    elif data.startswith("disc:"):
        slug = data[5:]
        a = adapters.BY_SLUG.get(slug)
        if a:
            blob = await kv("GET", f"session:{chat_id}:{slug}")
            if blob:
                try:
                    await a.revoke(dec(blob))
                except Exception:
                    pass
            await kv("DEL", f"session:{chat_id}:{slug}")
            await kv("SREM", f"accounts:{chat_id}", slug)
            await send(chat_id, f"{a.name} disconnected and your saved session was deleted.", MENU)
    elif data == "monitor":
        await send(chat_id, "Connect an account first, then monitoring can be started.")
    elif data == "claims":
        await send(chat_id, "No claims yet.")
    elif data == "settings":
        await send(chat_id, "Settings are coming soon.")
    elif data == "help":
        await send(chat_id,
            "1. Connect Website: send a campaign site link.\n"
            "2. Log in on the secure Spot Claim page I link you to.\n"
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
    a = adapters.lookup(domain)
    if not a:
        return await send(chat_id,
            f"{domain} isn't supported yet. It needs a dedicated integration "
            "before automation can work.", MENU)
    if not a.ready:
        return await send(chat_id,
            f"{a.name} is recognized, but its integration is still being finished "
            "and tested. I'll let you know when you can connect.", MENU)
    token = secrets.token_urlsafe(24)
    await kv("SET", f"connect:{token}", json.dumps({"chat": chat_id, "slug": a.slug}), "EX", 600)
    await send(chat_id,
        f"{a.name} is supported ✅\n\nTap below to log in on the secure Spot Claim page. "
        "Never send your password here. The link expires in 10 minutes.",
        {"inline_keyboard": [[{"text": "Log in securely", "url": f"{BASE}/connect/{a.slug}?t={token}"}]]})

# ---- Secure connect page ----
HDRS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"}

def page(body: str, status=200):
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Spot Claim</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#0b1020;color:#eef;display:grid;place-items:center;min-height:100vh}}
.c{{width:min(92vw,380px);background:#141b34;padding:28px;border-radius:16px}}
h1{{font-size:22px;margin:0 0 6px}}p{{color:#9aa4c7;font-size:14px}}
input{{width:100%;box-sizing:border-box;padding:12px;margin:6px 0 14px;border-radius:10px;border:1px solid #2a3560;background:#0b1020;color:#fff;font-size:16px}}
button{{width:100%;padding:13px;border:0;border-radius:10px;background:#4f7cff;color:#fff;font-size:16px;font-weight:600}}
.e{{color:#ff8a8a}}</style></head><body><div class="c">{body}</div></body></html>"""
    return HTMLResponse(doc, status_code=status, headers=HDRS)

def form(a, token, err=""):
    e = f'<p class="e">{html.escape(err)}</p>' if err else ""
    return page(f"""<h1>Connect {html.escape(a.name)}</h1>
<p>Log in with your {html.escape(a.name)} details. Your password is used once to sign in and is never saved. Only an encrypted session is kept, and you can disconnect any time.</p>{e}
<form method="post" action="/connect/{html.escape(a.slug)}" autocomplete="off">
<input type="hidden" name="t" value="{html.escape(token)}">
<label>X username</label><input name="username" required autocapitalize="none">
<label>Password</label><input name="password" type="password" required>
<button type="submit">Log in securely</button></form>""")

async def valid_ticket(token, slug):
    raw = await kv("GET", f"connect:{token}") if token else None
    if not raw:
        return None
    t = json.loads(raw)
    return t if t.get("slug") == slug else None

@app.get("/connect/{slug}")
async def connect_page(slug: str, t: str = ""):
    a = adapters.BY_SLUG.get(slug)
    if not a or not a.ready or not await valid_ticket(t, slug):
        return page("<h1>Link expired</h1><p>Go back to the bot and tap Connect Website again.</p>", 400)
    return form(a, t)

@app.post("/connect/{slug}")
async def connect_submit(slug: str, req: Request):
    a = adapters.BY_SLUG.get(slug)
    f = {k: v[0] for k, v in parse_qs((await req.body()).decode()).items()}
    token = f.get("t", "")
    ticket = await valid_ticket(token, slug) if a and a.ready else None
    if not ticket:
        return page("<h1>Link expired</h1><p>Go back to the bot and tap Connect Website again.</p>", 400)
    n = await kv("INCR", f"attempts:{token}")
    await kv("EXPIRE", f"attempts:{token}", 600)
    if n and int(n) > 5:
        return page("<h1>Too many attempts</h1><p>Go back to the bot and start again.</p>", 429)
    username, password = f.get("username", "").strip(), f.get("password", "")
    try:
        session = await a.login(username, password)
    except Exception:  # never log or echo credentials
        return form(a, token, "Login failed. Check your details and try again.")
    finally:
        password = None
    await kv("SET", f"session:{ticket['chat']}:{slug}", enc(session))
    await kv("SADD", f"accounts:{ticket['chat']}", slug)
    await kv("DEL", f"connect:{token}")
    await send(ticket["chat"], f"✅ {a.name} connected. Tap Start Monitoring when you're ready.", MENU)
    return page("<h1>Connected ✅</h1><p>You can close this page and return to Telegram.</p>")

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
    if not WEBHOOK_SECRET or not hmac.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{TG}/setWebhook", json={
            "url": f"{BASE}/webhook", "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message", "callback_query"]})
    return r.json()
