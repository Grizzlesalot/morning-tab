# Morning Tab

A personal new-tab page rebuilt every morning around 6am Melbourne time by GitHub Actions.

Sections: Fantasy League Lens, trending paranormal videos, AI updates, Moca and Minds,
AFL cards sold on eBay (Teamcoach and Select 2024 to 2026, Essendon and West Coast first),
kids activities (Thursday to Sunday), Melbourne headlines and sport, and weather.

## Files
- `morning_tab.py` builds the page into `site/index.html`
- `demo_data.py` sample content for `python morning_tab.py --demo`
- `.github/workflows/morning-tab.yml` the daily schedule

## Secrets (repo Settings > Secrets and variables > Actions)
- `ANTHROPIC_API_KEY` required, from platform.claude.com
- `YOUTUBE_API_KEY` optional, adds YouTube to the paranormal section

## Cost
Each run prints an estimated cost and shows it in the page footer. Expect roughly
US$0.50 to US$1 a day. If the monthly credit runs out, runs simply stop until it refreshes
(as long as auto-reload is off in the Console).

## Change things
- Run time: edit the `cron` line in the workflow (UTC).
- Models: `FAST_MODEL` and `SMART_MODEL` near the top of `morning_tab.py`.
- Card searches: `CARD_SEARCHES` near the top of `morning_tab.py`.
