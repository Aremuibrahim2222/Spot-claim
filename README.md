# Spot Claim

Instant campaign alerts for any registered platform.

Vercel env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, ADMIN_CHAT_ID, APP_BASE_URL,
KV_REST_API_URL, KV_REST_API_TOKEN. After deploy open once: /setup?secret=<TELEGRAM_WEBHOOK_SECRET>

Admin commands (only from ADMIN_CHAT_ID):
- /addplatform Name | domain.com | https://domain.com/connect-spotclaim   (returns the platform secret once)
- /drop domain.com | Campaign name | https://domain.com/link | 20        (manual alert)

Give DEVGUIDE.md and the platform secret to each platform's developer.
