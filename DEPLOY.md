# Running Jiya for real users (free tier)

One process serves the dashboard, the API, the scheduler, the Telegram poller and the browser-call
WebSocket on a single port, so one HTTPS tunnel is all you need.

## 1. Configure
```bash
cp newtalk/.env.example newtalk/.env      # fill in keys; see comments in the file
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # use for SESSION_SECRET and ADMIN_API_KEY
```
Telegram: BotFather -> `/newbot`, put the token and bot username in `.env`. No webhook is required.

## 2. Start the server
```bash
.venv/bin/python -m newtalk.scheduler.daily_job      # http://localhost:8000
```
It runs the shared pipeline at `PIPELINE_HOURS` (default 06:00, 13:00, 19:00 IST), ticks the call
scheduler every minute, polls Telegram, and purges text older than 30 days at 03:30.

## 3. Expose it over HTTPS (browser microphones and Telegram buttons need HTTPS)
Cloudflare quick tunnel (free, no account):
```bash
cloudflared tunnel --url http://localhost:8000
```
or ngrok: `ngrok http 8000`. Copy the `https://...` URL into `PUBLIC_BASE_URL` in `.env` and restart.
A quick-tunnel URL changes on every restart; a named Cloudflare tunnel or reserved ngrok domain is stable.

## 4. Invite people
```bash
curl -X POST localhost:8000/api/admin/invites \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"count": 5, "note": "demo batch"}'
```
Share `https://<public-url>/app/` plus one code per person. Each code is bound to one person on first use.

## 5. First run
```bash
curl -X POST localhost:8000/pipeline/run -H "X-Admin-Key: $ADMIN_API_KEY"   # fill the news pool now
.venv/bin/python -m newtalk.ingestion.feed_health                             # which feeds are alive
```

## Backups
```bash
scripts/backup_db.sh                                   # online-safe copy into ./backups, keeps 14
(crontab -e)  0 3 * * * /full/path/to/NewsTalk/scripts/backup_db.sh
```

## Limits to know
- Free TTS (`edge-tts`) is an unofficial Microsoft endpoint: fine for a demo, replace before scaling.
- Phone (PSTN) calls are not available on free tiers; delivery is Telegram ring + browser call.
- Groq free-tier rate limits are the real capacity ceiling; segments are cached per story and
  language so cost scales with stories x languages, not users.
