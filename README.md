# Spot Claim: instant campaign alerts

Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, NOTIFY_SECRET, ADMIN_CHAT_ID,
APP_BASE_URL, KV_REST_API_URL, KV_REST_API_TOKEN.

After deploy open once: /setup?secret=<TELEGRAM_WEBHOOK_SECRET>

Announce a campaign:
- Admin: in the bot send `/drop Campaign name | https://link | 20`
- Automatic: POST /notify with header `X-Notify-Secret` and JSON {"name","link","spots"}
