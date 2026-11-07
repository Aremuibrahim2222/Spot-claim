# Spot Claim integration guide (for a platform's developer)

Spot Claim never sees your users' passwords. You add two things to your site.
You receive a **platform secret** from the Spot Claim owner. Keep it in a server-side
environment variable (e.g. SPOTCLAIM_SECRET). Never put it in browser code.

Base URL: https://spot-claim-jet.vercel.app

## 1. Connect page (links a user to Spot Claim)
Create a page, e.g. `/connect-spotclaim`. Spot Claim sends users there as
`/connect-spotclaim?spotclaim_token=TOKEN`.
1. If the user isn't logged in, send them to your normal login, then back to this page
   (keep the token).
2. When they are logged in, call from YOUR SERVER:

```js
const r = await fetch("https://spot-claim-jet.vercel.app/link/confirm", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-Platform-Secret": process.env.SPOTCLAIM_SECRET },
  body: JSON.stringify({ token }),
});
```
3. If `r.ok`, show "Linked! Return to Telegram." (410 = token expired or already used).

## 2. Campaign alert (fires when a campaign is published)
Right after a campaign is created, from your server:

```js
try {
  await fetch("https://spot-claim-jet.vercel.app/notify", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Platform-Secret": process.env.SPOTCLAIM_SECRET },
    body: JSON.stringify({
      name: campaign.title,
      link: `https://YOUR-DOMAIN/campaigns/${campaign.id}`,
      spots: String(campaign.spots),
    }),
  });
} catch (e) {} // never block publishing if the alert fails
```
The link must be on your own domain. Duplicate links are ignored.
