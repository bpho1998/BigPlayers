# 🏛️ Campaign Finance Monitor Bot

A GitHub Actions bot that watches SF Ethics Commission filings and Cal-Access (California Secretary of State) for new campaign finance activity involving tracked individuals and organizations — and posts Discord alerts when matches are found.

---

## What It Monitors

### Data Sources

| Source | What's covered | Update cadence |
|--------|---------------|----------------|
| **SF Ethics / DataSF** (`pitq-e56w`) | All SF transactions: Forms 460, 461, 496, 497, 450 | Every 24 hours |
| **SF Ethics Filings Received** (`wo4n-ge8j`) | Committee/filer registration & receipt log | Every 24 hours |
| **Cal-Access bulk export** | Statewide contributions, IEs, late filings (RCPT_CD, S496, S497) | Daily |

### Tracked Individuals

- Chris Larsen · Ron Conway · Sergey Brin · Michael Seibel · Garry Tan
- Arthur Rock · Bill Oberndorf · Michael Moritz · David Sacks
- Jeremy Stoppelman · Emmett Shear · Jessica Livingston

### Tracked Organizations

- Grow California · Golden State Promise · Fairshake
- Building a Better California · Grow SF · TogetherSF
- Neighbors for a Better SF · Abundant SF · Progress SF
- Stop Crime SF · Forward Action SF · ConnectedSF · Advance SF · Believe in SF · SF Believes

---

## Setup

### 1. Fork / clone this repository

```bash
git clone https://github.com/YOUR_USERNAME/campaign-finance-bot.git
cd campaign-finance-bot
```

### 2. Create a Discord Webhook

1. Go to your Discord server → **Server Settings → Integrations → Webhooks**
2. Click **New Webhook**, give it a name (e.g. "Campaign Finance Bot"), pick a channel
3. Click **Copy Webhook URL**

### 3. Add the webhook as a GitHub Secret

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste the webhook URL you copied
5. Click **Add secret**

### 4. Enable GitHub Actions

Go to the **Actions** tab in your repo and click **"I understand my workflows, go ahead and enable them"** if prompted.

The bot will now run automatically every day at **9 AM Pacific time**.

---

## Manual Runs & Testing

Trigger a run instantly from **Actions → Campaign Finance Monitor → Run workflow**.

To test without downloading the large Cal-Access file (faster):

- Set the `skip_calaccess` input to `true` when triggering manually
- Or set the `SKIP_CALACCESS` environment variable to `1` locally

### Local testing

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export SKIP_CALACCESS=1   # optional: skip the ~200 MB Cal-Access download

python src/check_filings.py
```

---

## How It Works

```
GitHub Actions (daily cron)
        │
        ▼
check_filings.py
        │
        ├─► SF Ethics DataSF SODA API
        │     • Queries each tracked term via $q full-text search
        │     • Filters to filings from the last 48 hours
        │
        ├─► SF Ethics "Filings Received" API
        │     • Same search, catches filer/committee name matches
        │
        └─► Cal-Access bulk ZIP download
              • Streams RCPT_CD.TSV, S496_CD.TSV, S497_CD.TSV
              • Scans every row for any tracked term
              │
              ▼
        Dedupe against data/seen_ids.json (committed back to repo)
              │
              ▼
        Discord webhook → embeds per match + daily summary
```

---

## Deduplication

`data/seen_ids.json` stores SHA-256 hashes of every row already alerted on. The bot commits this file back to the repo after each run, so you never get duplicate Discord pings for the same filing — even across daily runs.

---

## Customizing

### Add or remove tracked terms

Edit `TRACKED_NAMES` and `TRACKED_ORGS` in `src/check_filings.py`.

### Change the schedule

Edit the `cron` expression in `.github/workflows/monitor.yml`. Use [crontab.guru](https://crontab.guru) to build expressions.

### Skip Cal-Access (faster / lighter)

Cal-Access downloads a ~200–400 MB ZIP each run. If you only care about SF local filings, set `SKIP_CALACCESS=1` permanently by adding it as a repository variable (**Settings → Secrets and variables → Actions → Variables**).

---

## Discord Alert Format

Each match produces an embed like:

```
🔔 Match: Garry Tan
Garry Tan appeared in a new SF Ethics filing.

📅 Date          2026-06-15
🏛️ Committee     Neighbors for a Better SF
👤 Contributor   Garry Tan
💰 Amount        $50,000
📄 Form Type     497
🆔 Filing ID     2490123
```

A summary embed is sent at the top of each batch:

```
📊 Campaign Finance Digest — 2026-06-28
Found 3 new match(es) across SF Ethics and Cal-Access.
Tracked 12 individuals and 13 organizations.
```

---

## Data Sources & Links

- SF Ethics DataSF SODA API: https://data.sfgov.org/resource/pitq-e56w.json
- SF Ethics Filings Received: https://data.sfgov.org/resource/wo4n-ge8j.json
- Cal-Access Bulk Download: https://www.sos.ca.gov/campaign-lobbying/helpful-resources/raw-data-campaign-finance-and-lobbying-activity
- Netfile Public Portal (SF): https://public.netfile.com/pub2/?aid=sfo
- Cal-Access Search: https://cal-access.sos.ca.gov/Campaign/

---

## Limitations

- **SF data** is updated nightly — contributions filed today may appear tomorrow.
- **Cal-Access** covers *state-level* filings only; SF-local committees file with the SF Ethics Commission instead. The bot checks both.
- Name matching is case-insensitive substring search. A contributor named "Ron Conway Jr." will match "Ron Conway". False positives are unlikely given these names, but review embeds for context.
- Street addresses are redacted from public data per California law.
