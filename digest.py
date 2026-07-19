import os
import re
import json
import smtplib
from datetime import datetime, timedelta, timezone
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

# ── Configuration ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS     = os.environ["GMAIL_ADDRESS"]      # your Gmail address
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"] # 16-char app password
RECIPIENT_EMAIL   = os.environ["RECIPIENT_EMAIL"]    # who receives the digest

RSS_FEEDS = [
    "https://breakingdefense.com/feed/",
    "https://www.defensenews.com/arc/outboundfeeds/rss/",
    "https://euro-sd.com/feed/",
    "https://www.rusi.org/rss.xml",
    "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/",
    "https://ukdefencejournal.org.uk/feed/",
    "https://warontherocks.com/feed/",
    "https://navaltoday.com/feed/",
    "https://defence-blog.com/feed/",
    "https://www.gov.uk/government/organisations/ministry-of-defence.atom",
    "https://twz.com/feed/",
    "https://euractiv.com/?feed=mcfeed",
    "https://feeds.feedburner.com/euronews/en/news/",
    "https://www.independent.co.uk/news/world/rss",
    "https://www.dw.com/en/top-stories/s-9097/rss",
    "https://www.lemonde.fr/rss/une.xml",
    "https://www.theguardian.com/uk/technology/rss",
    "https://rss.libsyn.com/shows/580325/destinations/5030860.xml",
]

MAX_ARTICLES_PER_FEED = 3  # keeps Claude token usage low
CATEGORIES = ["UK", "EU", "Korea", "World"]


def strip_html(text):
    """Remove HTML tags from RSS summaries so snippets render as plain text."""
    return re.sub(r"<[^<]+?>", "", text or "").strip()


# ── Fetch articles ─────────────────────────────────────────────────────────────
def fetch_articles():
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_iso = None
            if published:
                pub_date = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_date < cutoff:
                    continue
                pub_iso = pub_date.strftime("%Y-%m-%d")
            articles.append({
                "title":     entry.get("title", "No title"),
                "summary":   strip_html(entry.get("summary", entry.get("description", ""))),
                "url":       entry.get("link", ""),
                "source":    feed.feed.get("title", url),
                "published": pub_iso,
            })
    return articles


# ── Dedupe near-identical headlines across sources ────────────────────────────
def dedupe_articles(articles):
    """Drop articles whose normalised titles have already been seen.
    Catches exact re-syndication; does not catch differently-worded
    headlines about the same story (a fuzzy-match upgrade for later)."""
    seen = set()
    deduped = []
    for a in articles:
        key = re.sub(r"[^a-z0-9\s]", "", a["title"].lower()).strip()[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped


# ── Ask Claude to filter and categorise ────────────────────────────────────────
def categorize_articles(articles):
    """Ask Claude which articles are relevant and how to categorise/rank them.
    Claude returns only index + category (never re-types URLs or titles),
    so we pull the authoritative title/url/source/summary back from our own
    `articles` list rather than trusting model-generated text for links."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += f"\n[{i}] {a['source']}: {a['title']}\n{a['summary'][:500]}\n"

    prompt = f"""You are a defence tech news editor for a UK, European, and Korean audience.

From the numbered articles below, select only those relevant to defence technology —
including AI and autonomy, cyber, procurement reform, defence industrial policy, C-UAS,
electronic warfare, and space. Ignore personnel announcements and general military
operations news.

Assign each selected article to one category: UK, EU, Korea, or World (everything else,
including the US and other regions).

Return ONLY a JSON array, no other text, no markdown fences. Each element:
{{"index": <number from the list above>, "category": "UK"}}

Order the array by category grouping, and within each category by likelihood of
generating engagement on Reddit's r/Defence_Tech_UK community, most engagement-worthy
first. Omit irrelevant articles entirely.

Articles:
{articles_text}"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    selections = json.loads(raw)

    categorized = []
    for sel in selections:
        idx = sel["index"] - 1
        if 0 <= idx < len(articles):
            a = articles[idx]
            categorized.append({**a, "category": sel["category"]})
    return categorized


# ── Build the email HTML from categorised data ────────────────────────────────
def build_email_html(categorized):
    html = '<h2 style="color:#1a1a2e;font-family:Arial,sans-serif;">🛡️ Daily Defence Tech Digest</h2>'
    for category in CATEGORIES:
        items = [a for a in categorized if a["category"] == category]
        if not items:
            continue
        html += f'<h3 style="color:#1a1a2e;font-family:Arial,sans-serif;">{category}</h3>'
        html += '<ol style="font-family:Arial,sans-serif;line-height:2;">'
        for a in items:
            html += f'<li><a href="{a["url"]}" style="color:#0066cc;text-decoration:none;">{a["title"]}</a></li>'
        html += '</ol>'
    return html


# ── Write the flat JSON feed for the Wix news section ─────────────────────────
def write_news_json(categorized):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    feed = []
    for a in categorized:
        feed.append({
            "title":   a["title"],
            "url":     a["url"],
            "source":  a["source"],
            "snippet": a["summary"][:200],
            "date":    a.get("published") or today,
            "tag":     a["category"],
        })
    os.makedirs("public", exist_ok=True)
    with open("public/news.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(feed)} stories to public/news.json")


# ── Send email ─────────────────────────────────────────────────────────────────
def send_email(html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Daily Defence Tech Digest {datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    print("Digest sent.")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching articles...")
    articles = dedupe_articles(fetch_articles())
    print(f"Fetched {len(articles)} unique articles. Sending to Claude...")
    categorized = categorize_articles(articles)
    print(f"{len(categorized)} articles categorised. Building email and feed...")
    send_email(build_email_html(categorized))
    write_news_json(categorized)
