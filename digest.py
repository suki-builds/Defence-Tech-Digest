import os
import smtplib
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

# ── Fetch articles ─────────────────────────────────────────────────────────────
def fetch_articles():
    articles = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
            articles.append({
                "title":   entry.get("title", "No title"),
                "summary": entry.get("summary", entry.get("description", "")),
                "url":     entry.get("link", ""),
                "source":  feed.feed.get("title", url),
            })
    return articles

# ── Ask Claude to filter and summarise ────────────────────────────────────────
def generate_digest(articles):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += f"\n[{i}] {a['source']}: {a['title']}\nURL: {a['url']}\n{a['summary'][:500]}\n"

prompt = f"""You are a defence tech news editor for a UK and European audience.

From the articles below, select only those relevant to defence technology in the UK or EU — 
including AI and autonomy, cyber, procurement reform, defence industrial policy, C-UAS, 
electronic warfare, and space. Ignore US-only stories, personnel announcements, 
and general military operations news.

Translate any non-English headlines into English.

Return a numbered list of headlines only, ranked by likelihood of generating engagement 
on Reddit's r/Defence_Tech_UK community. Most engagement-worthy first.
Include the URL after each headline.

Format as clean HTML for an email.

Articles:
{articles_text}"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    result = message.content[0].text
    result = result.replace("```html", "").replace("```","").strip()
    return result

# ── Send email ─────────────────────────────────────────────────────────────────
def send_email(html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Daily Defence Tech Digest"
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
    articles = fetch_articles()
    print(f"Fetched {len(articles)} articles. Sending to Claude...")
    digest = generate_digest(articles)
    print("Digest generated. Sending email...")
    send_email(digest)
