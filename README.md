# Telegram `/all` tagger — mentions every group member, even silent ones

Type `/all` in a group and the bot mentions **every member Telegram lets us list**, including people
who never wrote a message, never touched the bot and have no username. Mentions use numeric IDs:
`<a href="tg://user?id=123456789">Nassim</a>`.

---------------------------------------------------------------------------------------------

## 1. Architecture (and why)

```
 Telegram group ──/all──▶ Telegram Bot API ──webhook──▶ [ Render free web service (Python) ]
                                                            │        │             │
                                            (1) MTProto ◀───┘        │             │
                                   helper user account (Telethon)    │             │
                                   channels.getParticipants          │ (2) upsert  │ (3) sendMessage
                                                                     ▼             ▼
                                                               Supabase Postgres   Bot API ──▶ group
```

| Component | Job |
|---|---|
| **Bot** (BotFather token) | Receives `/all` (via webhook) and posts the mentions. |
| **Helper user account** (MTProto session, Telethon) | Reads the participant list. **A bot cannot do this**: the Bot API has no "list members" method, and bots are also blocked from listing members through MTProto in most groups. Only a *user* account that is a member of the group can. |
| **Supabase Postgres** | Persists `telegram_user_id`, names, username, group, timestamps. Identity = numeric ID. |
| **Render free web service** | Runs the Python app 24/7 without your PC. |

**Why Telethon:** mature, asyncio-native, exposes the raw `channels.getParticipants` /
`messages.getFullChat` calls, typed `FloodWaitError`, and `StringSession` (the whole login fits in
one secret string, ideal for hosts with no persistent disk). Pyrogram's original repo has seen little
maintenance (only forks are active), and TDLib means C++ bindings — needless for this job.

**Why not Supabase Edge Functions:** they run Deno/TypeScript, not Python/Telethon, and have hard
limits (Free plan: 150 s wall clock, 2 s CPU per request). A Telegram login session is a poor fit
for that runtime. Supabase is used for what it is good at: the database.

**Key design decisions**
* Webhook (not long polling): a sleeping free host is woken by the incoming request.
* MTProto connects **on demand** per `/all`, then disconnects. This avoids two processes ever using
  the same session at once (which can get a session killed) and works on hosts that restart.
* Supabase failure never blocks `/all` — mentions are sent even if the DB is down.

---------------------------------------------------------------------------------------------

## 2. What Telegram does and does NOT allow (read this!)

| Situation | Reality |
|---|---|
| Members who **never sent a message**, no username | ✅ Listed by `channels.getParticipants` — that is exactly what it is for. |
| Supergroup, helper account is a member | ✅ Full listing, paginated 200 per page. |
| Basic group (small legacy group) | ✅ Works via `messages.getFullChat`. If it later upgrades to a supergroup its ID changes — run `/all` from the new one. |
| Private vs public group | No difference for listing; the helper account just has to be a member (private = join via invite link). |
| Broadcast **channels** | ❌ Only admins can see subscribers, and channels have no "members" to tag. The bot replies with a clear error. |
| Groups that **hide their member list** | ⚠️ Telegram lets supergroups above a size threshold hide members from non-admins. Make the helper account an **admin** (you can leave all its rights switched off — test it). The bot warns when the list is hidden/incomplete. |
| Groups with > ~10,000 members | ⚠️ Telegram caps what any client can enumerate. The bot mentions what it can and says how many were missed. |
| Deleted accounts | Skipped (nothing to mention). Bots skipped unless `INCLUDE_BOTS=true`. The helper account itself is skipped. |
| Members who left | Marked `is_active=false` in the DB after a *complete* listing. |
| `tg://user?id=` mentions | Telegram guarantees them for users who are **members of the group where they are mentioned** — which is our case, so no `/start` needed. |
| Notifications | A mention notifies the user, but Telegram may not notify for very large numbers of mentions in one message, and muted users stay muted. Tune `MENTIONS_PER_MESSAGE` (default 20) during testing. |
| Terms of Service | Automating a user account is a grey area. Use a **dedicated second account**, keep usage low (this app only reads when someone runs `/all`), never spam. |

---------------------------------------------------------------------------------------------

## 3. Hosting: what is *currently* free (checked September 2026)

| Provider | Status | Fit |
|---|---|---|
| **Render** – free web service | Free, no credit card, 750 instance-hours/month per workspace (one service 24/7 ≈ 744 h). Sleeps after 15 min without traffic; wake-up takes up to ~1 min. Background *workers* are not free — hence a **web service + webhook**. | ✅ **Chosen** |
| Koyeb | 1 free service, 0.1 vCPU / 512 MB, scale-to-zero. Free-tier terms change often (verify signup requirements yourself). | Backup option |
| Railway | No permanent free tier — one-time trial credit only. | ❌ |
| Fly.io | No free tier for new accounts (short trial, card required). | ❌ |
| Supabase Edge Functions | Free but wrong runtime and limits (see above). | ❌ for MTProto |

Verify before you commit — free tiers change: <https://render.com/docs/free>.
Supabase free projects have historically been **paused after about a week of inactivity** — check your
project dashboard and un-pause if needed (using `/all` weekly keeps it awake).

**Sleeping:** with the webhook design the bot still works while asleep — Telegram delivers the update,
Render wakes up, and the command is handled (or retried by Telegram). To avoid the delay, add a free
uptime pinger (UptimeRobot, cron-job.org…) hitting `https://YOUR-APP.onrender.com/health` every ≤ 10 min.
One always-awake service fits inside the 750 h pool. (Check the pinger's current free interval.)

---------------------------------------------------------------------------------------------

## 4. Step-by-step setup (beginner friendly)

### Step 1 — Create the bot (BotFather)
1. In Telegram open **@BotFather** → `/newbot` → choose a name and a username ending in `bot`.
2. Copy the **token** (`123456:ABC…`). This is `BOT_TOKEN`. Treat it like a password.
3. (Optional) `/setjoingroups` → keep enabled until you have added the bot; disable later so strangers can't add it.

### Step 2 — Get `API_ID` and `API_HASH`
1. Log in at <https://my.telegram.org> with the **helper account's** phone number.
2. **API development tools** → create an application (any name) → copy `api_id` and `api_hash`.

### Step 3 — Prepare the helper account
* Use a **separate Telegram account** (second SIM / eSIM), not your personal one.
* Enable Two-Step Verification on it (Settings → Privacy → Two-Step Verification).
* Join your test group with it. If the group hides its member list, make it an admin.

### Step 4 — Create Supabase
1. <https://supabase.com> → New project (free plan). Save the DB password somewhere safe.
2. **SQL Editor → New query** → paste all of `sql/schema.sql` → **Run**.
3. **Project Settings → API**: copy the **Project URL** (`SUPABASE_URL`) and the **service_role / secret key**
   (`SUPABASE_SERVICE_KEY`). This key bypasses all security: server-side only, never in a public repo.
   (If you get an "Invalid API key" error with a new-style secret key, run `pip install -U supabase`.)

### Step 5 — Log the helper account in ONCE (creates `TELETHON_SESSION`)
This needs a computer for about two minutes — it does **not** host anything, you can switch it off afterwards.
(No PC? Use Google Colab or GitHub Codespaces.)
```bash
pip install telethon
python scripts/generate_session.py
```
Enter `API_ID`, `API_HASH`, then the phone number, the code Telegram sends to the helper account, and the
2FA password. Copy the printed string → this is `TELETHON_SESSION`. Never commit or share it.
Do not run the generated string anywhere else while the server uses it.

### Step 6 — Put the code on GitHub
Create a **private** repository and upload this project (the `.gitignore` already excludes `.env` and sessions).
Double-check no real secret is in any file — `.env.example` must contain placeholders only.

### Step 7 — Deploy on Render
1. <https://render.com> → **New → Web Service** → connect the GitHub repo.
2. Runtime **Python 3**, Build command `pip install -r requirements.txt`, Start command `python -m app.main`,
   Instance type **Free**, Health check path `/health`.
   (Or use **New → Blueprint** with the included `render.yaml`.)
3. **Environment** tab → add: `BOT_TOKEN`, `API_ID`, `API_HASH`, `TELETHON_SESSION`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_KEY`, `WEBHOOK_SECRET` (random: `python -c "import secrets; print(secrets.token_urlsafe(32))"`),
   `PYTHON_VERSION=3.12.3`. Leave `PUBLIC_URL` empty on Render.
4. Deploy. The logs must show `Webhook set for @yourbot …`.

### Step 8 — Add the bot to the group
Add the bot as a normal member. It does **not** need admin rights: commands starting with `/` reach bots even with
privacy mode on. Send `/chatid` in the group, copy the ID and set `ALLOWED_CHAT_IDS=-100xxxxxxxxxx` in Render
so the bot only serves your group.

### Step 9 — Run it
Type `/all` (as a group admin). Expected: `📢 SIGL L3 — 48 members` followed by the mentions, in batches.

---------------------------------------------------------------------------------------------

## 5. Project layout

```
app/
  main.py               aiohttp server: /health + Telegram webhook
  config.py             env-var settings (fails fast, redacts secrets)
  deps.py               shared objects
  bot/  api.py          tiny Bot API client (429 handling)
        commands.py     command registry, /all, /help, /chatid   <- add /sync /menu /events here
        handlers.py     update -> command routing
        mentions.py     tg://user?id= mention builder + message splitting
  mtproto/ client.py    Telethon StringSession, connect-on-demand
           participants.py  pagination, FloodWait, retries, group-type detection
  database/ supabase.py, models.py
scripts/generate_session.py   one-time login
sql/schema.sql                Supabase schema
tests/                        unit tests (pytest)
```

Run the unit tests: `pip install -r requirements-dev.txt && pytest`.

---------------------------------------------------------------------------------------------

## 6. Test plan (use a separate test group)

**Setup:** create a test supergroup with: the bot, the helper account, you (admin), and ≥ 5 test accounts
covering — (A) wrote messages, (B) **never wrote anything**, (C) has a username, (D) **no username**,
(E) Arabic/French/emoji name. Record the true member count from the group info page.

| # | Test | Expected |
|---|---|---|
| 1 | `/all` as admin | Header shows the correct count; **B and D users are mentioned and notified**. |
| 2 | Compare DB: `select * from members where group_id = …` | One row per member, `username` null for D users. |
| 3 | Change a user's username, run `/all` again | Same mention (ID-based); DB `username` updated; row count unchanged; `discovered_at` unchanged. |
| 4 | Remove the username entirely | Still mentioned; `username` becomes null. |
| 5 | Run `/all` 3× quickly | 2nd/3rd reply with cooldown/"already running" message; DB has no duplicates (UNIQUE constraint). |
| 6 | A member leaves, run `/all` | They are no longer mentioned; `is_active=false` in DB. |
| 7 | Non-admin runs `/all` | Polite refusal (`ALL_PERMISSION=admins`). |
| 8 | Run `/all` in a private chat with the bot | "only works in a group". |
| 9 | Run in a group where the helper account is **not** a member | Clear error telling you to add it. |
| 10 | Basic group (turn off "supergroup" by using a tiny new group) | Works; note the ID changes if Telegram upgrades it. |
| 11 | Hidden member list (large groups only) | Warning shown if incomplete; works fully once the helper is admin. |
| 12 | Large list (≥ 200 members, use a big public group you own/admin) | Multiple pages fetched (see logs), multiple mention messages, no lost users. |
| 13 | Rate limiting: run `/all` in many big groups back-to-back | Logs show `FloodWait: sleeping…`; waits are honoured; waits over `MAX_FLOOD_WAIT_SECONDS` produce a clear "try later" message. |
| 14 | Temporarily set a wrong Supabase key | Mentions still sent; error logged. |
| 15 | Let Render sleep 20 min, then `/all` | Answered after the wake-up delay. |
| 16 | Try `MENTIONS_PER_MESSAGE` = 5 / 20 / 50 | Pick the largest value where everyone still gets a notification. |

---------------------------------------------------------------------------------------------

## 7. Security checklist
* Secrets live only in Render's environment (and your password manager). `.env` is git-ignored; `.env.example` holds placeholders.
* `TELETHON_SESSION` = full access to the helper account. If it leaks: Telegram → Settings → Devices → terminate that session, then regenerate.
* Use a dedicated helper account with 2FA and nothing valuable in it.
* Supabase tables have RLS enabled with no policies: the public `anon` key can read nothing; only the service-role key (server-side) can.
* The webhook only accepts requests carrying `X-Telegram-Bot-Api-Secret-Token` (compared in constant time).
* `ALLOWED_CHAT_IDS` stops strangers from using your helper account through your bot; `ALL_PERMISSION=admins` stops members spamming `/all`.
* Logs never print tokens, hashes or session strings; the `Settings` object redacts itself.
* Privacy: you store members' names/IDs. Tell your group, and delete rows on request (`delete from members where telegram_user_id = …`).
* Never run the same session string on two machines at once.

## 8. Known limitations
See section 2, plus: cold starts on free hosting; the exact "notify" behaviour for many mentions is decided by Telegram
(test it); a user who left between the count and the listing can cause a harmless "incomplete" warning; the session string
is not re-saved if Telegram migrates the account to another data center (regenerate it if `/all` reports logged-out).

## 9. Adding commands later
```python
# app/bot/commands.py
@command("sync")
async def cmd_sync(ctx: Context) -> None:
    ...
```
That is the whole registration — routing, whitelisting and `/cmd@botname` handling are already in `handlers.py`.
