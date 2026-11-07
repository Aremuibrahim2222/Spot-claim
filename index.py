"""Spot Claim: instant campaign alerts for any registered platform (FastAPI on Vercel).

Flow: user sends a platform link -> bot gives a one-time connect link on the platform's
own site -> the platform confirms the login server-to-server (/link/confirm) -> when the
platform publishes a campaign it calls /notify -> linked users are alerted on Telegram.
No passwords ever reach Spot Claim."""
import os, json, hmac, asyncio, secrets, hashlib
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, Header, HTTPException

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
ADMIN = os.getenv("ADMIN_CHAT_ID", "")
BASE = os.getenv("APP_BASE_URL", "").rstrip("/")
KV_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL", "")
KV_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
TG = f"https://api.telegram.org/bot{TOKEN}"

app = FastAPI()

WELCOME = ("Welcome to Spot Claim 🚀\n\nNever miss a limited campaign spot again.\n\n"
           "Connect a campaign platform once, and I'll message you within a second "
           "whenever it drops a new campaign, with a direct link so you can claim first.")

MENU = {"inline_keyboard": [
    [{"text": "🔗 Connect Platform", "callback_data": "connect"},
     {"text": "My Platforms", "callback_data": "mine"}],
    [{"text": "Latest Campaigns", "callback_data": "latest"},
     {"text": "Help", "callback_data": "help"}],
]}

# ---------- helpers ----------
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

def domain_of(url: str):
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host if "." in host and " " not in url else None

def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def link_ok(link: str, domain: str) -> bool:
    """Alerts may only link to the platform's own domain (anti-phishing)."""
    d = domain_of(link) if (link or "").startswith("https://") else None
    return bool(d) and (d == domain or d.endswith("." + domain))

async def platform_by_secret(secret: str):
    if not secret:
        return None
    return await kv("GET", f"psecret:{sha(secret)}")

def alert_text(platform, name, link, spots=""):
    extra = f"\nSpots: {spots}" if spots else ""
    return (f"🚨 NEW CAMPAIGN DROPPED\n\nPlatform: {platform}\nCampaign: {name}{extra}\n"
            "Spots are first-come, so move fast.\n\nOpen campaign: " + link)

async def broadcast(domain, name, link, spots=""):
    p = await kv("GET", f"platform:{domain}")
    if not p:
        return {"sent": 0, "error": "unknown platform"}
    pname = json.loads(p)["name"]
    if not await kv("SET", f"seen:{link}", "1", "NX", "EX", 86400):
        return {"sent": 0, "duplicate": True}
    await kv("SET", f"latest:{domain}", json.dumps({"name": name, "link": link, "spots": spots}))
    subs = await kv("SMEMBERS", f"subs:{domain}") or []
    text = alert_text(pname, name, link, spots)
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
                    await kv("SREM", f"subs:{domain}", s)
                    await kv("SREM", f"chat:{s}", domain)
            if i + 25 < len(subs):
                await asyncio.sleep(1)
    return {"sent": sent, "duplicate": False}

# ---------- bot ----------
async def start_connect(chat_id, text):
    domain = domain_of(text)
    if not domain:
        return await send(chat_id, "That doesn't look like a valid link. Send the platform's website link.")
    raw = await kv("GET", f"platform:{domain}")
    if not raw:
        return await send(chat_id,
            f"{domain} isn't set up for Spot Claim yet.\n\n"
            "Its developer needs to add two small things: a Connect button and a campaign "
            "alert. Ask them to contact the Spot Claim owner for the integration guide.", MENU)
    p = json.loads(raw)
    token = secrets.token_urlsafe(24)
    await kv("SET", f"link:{token}", json.dumps({"chat": chat_id, "domain": domain}), "EX", 900)
    sep = "&" if "?" in p["connect_url"] else "?"
    url = f"{p['connect_url']}{sep}spotclaim_token={token}"
    await send(chat_id,
        f"{p['name']} is supported ✅\n\nTap below, log in on the {p['name']} website, "
        "and your account links to this bot automatically. The link expires in 15 minutes.",
        {"inline_keyboard": [[{"text": f"Log in on {p['name']}", "url": url}]]})

async def on_button(chat_id, data):
    if data == "connect":
        await send(chat_id, "Send me the website link of the campaign platform you want to connect.")
    elif data == "mine":
        doms = await kv("SMEMBERS", f"chat:{chat_id}") or []
        if not doms:
            return await send(chat_id, "No platforms linked yet. Tap Connect Platform.", MENU)
        rows = []
        for d in doms:
            raw = await kv("GET", f"platform:{d}")
            if raw and len(d) < 55:
                rows.append([{"text": f"Unlink {json.loads(raw)['name']}", "callback_data": f"un:{d}"}])
        await send(chat_id, "Linked platforms (alerts are ON):", {"inline_keyboard": rows})
    elif data.startswith("un:"):
        d = data[3:]
        await kv("SREM", f"subs:{d}", str(chat_id))
        await kv("SREM", f"chat:{chat_id}", d)
        await send(chat_id, "Unlinked. You won't get alerts from that platform.", MENU)
    elif data == "latest":
        doms = await kv("SMEMBERS", f"chat:{chat_id}") or []
        shown = 0
        for d in doms:
            l, p = await kv("GET", f"latest:{d}"), await kv("GET", f"platform:{d}")
            if l and p:
                l, p = json.loads(l), json.loads(p)
                await send(chat_id, alert_text(p["name"], l["name"], l["link"], l.get("spots", "")),
                           {"inline_keyboard": [[{"text": "Open campaign", "url": l["link"]}]]})
                shown += 1
        if not shown:
            await send(chat_id, "No campaigns yet from your linked platforms.", MENU)
    elif data == "help":
        await send(chat_id, "1. Tap Connect Platform and send the platform's link.\n"
                            "2. Log in on the platform's site using the button I give you.\n"
                            "3. You'll get an alert here the moment it drops a campaign.\n\n"
                            "I never ask for your password.")

async def on_text(chat_id, text):
    t = text.strip()
    if t.startswith("/start"):
        return await send(chat_id, WELCOME, MENU)
    if t.startswith("/id"):
        return await send(chat_id, f"Your chat ID: {chat_id}")
    is_admin = bool(ADMIN) and str(chat_id) == ADMIN
    if t.startswith("/addplatform"):
        if not is_admin:
            return await send(chat_id, "Not allowed.")
        a = [x.strip() for x in t[12:].split("|")]
        d = domain_of(a[1]) if len(a) > 2 else None
        if not d or not a[0] or not a[2].startswith("https://"):
            return await send(chat_id, "Use: /addplatform Name | domain.com | https://domain.com/connect-spotclaim")
        old = await kv("GET", f"platform:{d}")
        if old and json.loads(old).get("sha"):
            await kv("DEL", f"psecret:{json.loads(old)['sha']}")
        secret = secrets.token_urlsafe(32)
        await kv("SET", f"platform:{d}", json.dumps({"name": a[0][:60], "connect_url": a[2], "sha": sha(secret)}))
        await kv("SET", f"psecret:{sha(secret)}", d)
        return await send(chat_id, f"✅ {a[0]} registered ({d}).\n\nPlatform secret (shown once, give it to the dev, "
                                   f"never share publicly):\n{secret}")
    if t.startswith("/drop"):
        if not is_admin:
            return await send(chat_id, "Not allowed.")
        a = [x.strip() for x in t[5:].split("|")]
        d = domain_of(a[0]) if len(a) > 2 else None
        if not d or not link_ok(a[2], d):
            return await send(chat_id, "Use: /drop domain.com | Campaign name | https://domain.com/link | 20")
        r = await broadcast(d, a[1][:120], a[2], a[3][:20] if len(a) > 3 else "")
        return await send(chat_id, r.get("error") or ("Already announced." if r.get("duplicate")
                                                      else f"Sent to {r['sent']} users."))
    if "." in t and " " not in t:  # looks like a link: start connecting
        return await start_connect(chat_id, t)
    await send(chat_id, "Use the menu below.", MENU)

# ---------- API for platforms ----------
@app.get("/")
async def health():
    return {"app": "Spot Claim", "status": "ok"}

@app.post("/link/confirm")
async def link_confirm(req: Request, x_platform_secret: str = Header(default="")):
    """Platform calls this (server-to-server) after the user logs in on the platform."""
    domain = await platform_by_secret(x_platform_secret)
    if not domain:
        raise HTTPException(status_code=401)
    d = await req.json()
    raw = await kv("GET", f"link:{d.get('token', '')}")
    if not raw:
        raise HTTPException(status_code=410, detail="token expired or used")
    t = json.loads(raw)
    if t["domain"] != domain:
        raise HTTPException(status_code=403)
    await kv("DEL", f"link:{d['token']}")
    await kv("SADD", f"subs:{domain}", str(t["chat"]))
    await kv("SADD", f"chat:{t['chat']}", domain)
    p = json.loads(await kv("GET", f"platform:{domain}"))
    await send(t["chat"], f"✅ {p['name']} linked. I'll alert you the moment it drops a campaign.", MENU)
    return {"ok": True, "linked": True}

@app.post("/notify")
async def notify(req: Request, x_platform_secret: str = Header(default="")):
    """Platform calls this when it publishes a campaign."""
    domain = await platform_by_secret(x_platform_secret)
    if not domain:
        raise HTTPException(status_code=401)
    d = await req.json()
    name, link = str(d.get("name", "")).strip()[:120], str(d.get("link", "")).strip()
    if not name or not link_ok(link, domain):
        raise HTTPException(status_code=422, detail="name and an https link on your own domain required")
    return await broadcast(domain, name, link, str(d.get("spots", ""))[:20])

# ---------- Telegram ----------
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
