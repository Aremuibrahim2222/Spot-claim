# Spot Claim (Phase 1: Telegram bot on Vercel)

Env vars (Vercel > Settings > Environment Variables):
TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET (any long random string),
APP_BASE_URL (your https://xxx.vercel.app, no trailing slash),
KV_REST_API_URL + KV_REST_API_TOKEN (from Upstash Redis via Vercel Marketplace).

After deploy, open once: https://YOUR-APP.vercel.app/setup?secret=YOUR_WEBHOOK_SECRET
Then send /start to the bot.
