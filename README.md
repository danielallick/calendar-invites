# Financial Calendar Bot

Automatically scrapes configured financial calendar websites, enriches events with AI-generated context via Claude, and sends calendar invites to your email.

Runs daily on GitHub Actions (free tier). Zero infrastructure to manage.

## How it works

```
Financial calendar websites → Scraper → Claude API (enrichment) → .ics email → Your calendar
```

1. **Scrapes** all enabled websites listed in `financial_sources.json` for earnings dates, AGMs, and report publications
2. **Deduplicates** against previously sent events (stored in `sent_events.json`)
3. **Enriches** each new event with Claude, adding investor-relevant context
4. **Emails** a `.ics` calendar invite that auto-creates an event in your calendar
5. **Commits** the updated state back to the repo so events aren't sent twice

## Setup (10 minutes)

### 1. Fork or clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/calendar-invites.git
```

### 2. Create a Gmail App Password

You need an App Password (not your regular Gmail password):

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. You may need to enable 2-Step Verification first
3. Generate a new app password for "Mail"
4. Copy the 16-character password

### 3. Get a Claude API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Add some credits ($5 is plenty — each run costs ~$0.01)

### 4. Add GitHub Secrets

In your repo → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `CLAUDE_API_KEY` | Your Anthropic API key |
| `GMAIL_ADDRESS` | Your Gmail address (sender) |
| `GMAIL_APP_PASSWORD` | The 16-char app password from step 2 |
| `CALENDAR_EMAIL` | Email to receive invites (can be same as GMAIL_ADDRESS) |

### 5. Enable GitHub Actions

Go to the Actions tab in your repo and enable workflows. You can trigger the first run manually via "Run workflow".

## Customization

### Change the schedule

Edit `.github/workflows/calendar-sync.yml`:

```yaml
schedule:
  - cron: "0 7 * * 1"  # Every Monday at 7 AM UTC
```

### Add or remove websites

Edit `financial_sources.json`.

- Set `enabled` to `true` or `false`
- Add a new source object with:
  - `id` (unique key)
  - `company`
  - `ticker`
  - `events_url`
  - `investor_url`
  - `parser` (currently `table_two_column`)

Current defaults include:
- Aixtron: `https://www.aixtron.com/en/press/events`
- Kendrion: `https://www.kendrion.com/en/about-kendrion/investor-relations/financial-calendar`
- Azelis: `https://www.azelis.com/en/financial-calendar`

### Skip Claude enrichment

If you don't want AI descriptions, simply don't set the `CLAUDE_API_KEY` secret. The bot will fall back to basic event descriptions.

## Costs

- **GitHub Actions**: Free (runs ~30 seconds/day, well within free tier)
- **Claude API**: ~$0.01/run (only calls API for new events)
- **Gmail SMTP**: Free

## Local testing

```bash
pip install -r requirements.txt

# Set env vars
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export CALENDAR_EMAIL="you@gmail.com"
export CLAUDE_API_KEY="sk-ant-..."

python scraper.py
```

## License

MIT
