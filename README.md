# Defence-Tech-Digest

Drafts Fox and Lion news items from defence-tech RSS feeds and puts them in Prismic for review.

## What a run does

1. Fetches the last 24 hours of articles from the feeds in `digest.py`.
2. **Selects and groups** (`cluster.py`, Claude Haiku). This drops irrelevant, opinion and sponsored pieces, and groups articles that report the same event. Events already drafted in the last 3 days are skipped.
3. **Writes** one news item per event (`rewrite.py`, Claude Sonnet), following the news rules in `style/fox-and-lion-writing-style.md`. Each item has a headline, a two-sentence description and up to three bullets.
4. **Checks** each item (`style_check.py`): contractions, dashes, "U.S.", British spelling, length limits, and any wording copied from a source. A failing item gets one automatic repair attempt. If problems remain, it is tagged `needs-edit`.
5. **Creates drafts** in Prismic (`prismic.py`) as `news_post` documents in the Migration Release. Nothing is published automatically.
6. **Emails a preview** to `RECIPIENT_EMAIL`, with source links for fact-checking. These links are not published.
7. **Reports cost** (`costs.py`): tokens and dollars per story and for the whole run, in the run log and at the foot of the email.

To publish, review the drafts in Prismic under **Migration Releases**, edit as needed, then publish.

## Running it

From the **Actions** tab, choose **Daily Defence Tech Digest**, then **Run workflow**.

- **Dry run** (ticked by default) writes the drafts, the email and the Prismic payloads to a downloadable `drafts` artifact. It sends, pushes and saves nothing.
- **Untick it** for a real run.

Secrets used: `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`, `PRISMIC_WRITE_TOKEN`.

Locally:

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python -m pytest
DRY_RUN=1 ANTHROPIC_API_KEY=... .venv/Scripts/python digest.py           # output in out/
```

## Changing things

- **House style:** edit `style/fox-and-lion-writing-style.md`. Sections 1, 3 and 5 are sent to the writer. Mechanical rules also live in `style_check.py`.
- **Models:** `CLUSTER_MODEL` and `REWRITE_MODEL` at the top of `digest.py`. Model prices for the cost report are in `costs.py`.
- **Feeds:** `RSS_FEEDS` in `digest.py`.
