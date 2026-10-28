import os
import re
import html
import json
import socket
import smtplib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

from cluster import select_and_cluster
from rewrite import load_news_style_guide, build_system_prompt, write_story
from style_check import check_story
from costs import Tally
import prismic

# ── Configuration ──────────────────────────────────────────────────────────────
# One model per step; swap either by editing one line.
CLUSTER_MODEL = "claude-haiku-5-5"   # select relevant articles and group same-event ones
REWRITE_MODEL = "claude-sonnet-5-5"  # write each story in the house style

# DRY_RUN=1 writes everything to out/ and sends, pushes and saves nothing.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
OUT_DIR = Path("out")
STATE_PATH = Path("state/history.json")
HISTORY_KEEP_DAYS = 7      # how long drafted events are remembered
HISTORY_PROMPT_DAYS = 3    # how far back the clustering call looks for repeats

RSS_FEEDS = [
    "https://breakingdefense.com/feed/",
    "https://www.defensenews.com/arc/outboundfeeds/rss/",
    "https://euro-sd.com/feed/",
    "https://www.rusi.org/rss.xml",
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

socket.setdefaulttimeout(20)  # one stuck feed must not hang the run


def strip_html(text):
    """Remove HTML tags and decode entities (e.g. &#8217; -> ') from RSS
    summaries so snippets render as clean plain text."""
    stripped = re.sub(r"<[^<]+?>", "", text or "")
    return html.unescape(stripped).strip()


# ── Fetch articles ─────────────────────────────────────────────────────────────
def fetch_articles():
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if not published:
                continue  # undated items cannot be checked against the 24h window
            pub_date = datetime(*published[:6], tzinfo=timezone.utc)
            if pub_date < cutoff:
                continue
            articles.append({
                "title":     strip_html(entry.get("title", "No title")),
                "summary":   strip_html(entry.get("summary", entry.get("description", ""))),
                "url":       entry.get("link", ""),
                "source":    feed.feed.get("title", url),
                "published": pub_date.strftime("%Y-%m-%d"),
            })
    return articles


# ── Dedupe near-identical headlines across sources ────────────────────────────
def dedupe_articles(articles):
    """Drop articles whose normalised titles have already been seen.
    Catches exact re-syndication; differently-worded headlines about the
    same story are grouped later by the clustering call."""
    seen = set()
    deduped = []
    for a in articles:
        key = re.sub(r"[^a-z0-9\s]", "", a["title"].lower()).strip()[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped


# ── History of drafted events (persisted between runs by actions/cache) ────────
def load_history():
    if not STATE_PATH.exists():
        print("No history found; treating every event as new.")
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    history = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return [h for h in history if h["date"] >= cutoff]


def save_history(history):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Write and check each story ────────────────────────────────────────────────
def write_stories(client, clusters, run_tally):
    """Returns (stories, failures). Each story carries its cluster, the final
    text, any style violations left after one repair attempt, and its cost.
    Every call, including those for failed stories, is added to `run_tally`."""
    system_prompt = build_system_prompt(load_news_style_guide())
    stories, failures = [], []
    for c in clusters:
        sources = [f"{a['title']}\n{a['summary']}" for a in c["articles"]]
        tally = Tally()
        try:
            story = write_story(client, REWRITE_MODEL, system_prompt, c["articles"], tally=tally)
            problems = check_story(story.title, story.description, story.bullets, sources)
            if problems:
                story = write_story(client, REWRITE_MODEL, system_prompt, c["articles"],
                                    previous=story, violations=problems, tally=tally)
                problems = check_story(story.title, story.description, story.bullets, sources)
        except (anthropic.APIError, RuntimeError) as e:
            print(f"Skipping '{c['event_label']}': {e}")
            failures.append((c, str(e)))
            continue
        finally:
            run_tally.add(tally)
        print(f"  {story.title}: {tally.describe()}")
        stories.append({**c, "story": story, "problems": problems, "cost": tally})
    return stories, failures


# ── Build the private preview email ───────────────────────────────────────────
FONT = "font-family:Arial,sans-serif;"


def build_email_html(stories, skipped, failures, push_errors, cost_summary):
    e = html.escape
    out = [f'<h2 style="color:#1a1a2e;{FONT}">Fox and Lion news drafts</h2>',
           f'<p style="{FONT}">{len(stories)} drafts are waiting in Prismic under Migration Releases: '
           f'<a href="{prismic.DASHBOARD_URL}">{prismic.DASHBOARD_URL}</a>. '
           'Source links below are for checking only and are not published.</p>']

    for category in CATEGORIES:
        items = [s for s in stories if s["category"] == category]
        if not items:
            continue
        out.append(f'<h3 style="color:#1a1a2e;{FONT}">{category}</h3>')
        for s in items:
            st = s["story"]
            out.append(f'<div style="{FONT}margin-bottom:22px;">')
            out.append(f'<p style="margin:0;font-weight:bold;">{e(st.title)}</p>')
            out.append(f'<p style="margin:4px 0;">{e(st.description)}</p>')
            out.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in st.bullets) + "</ul>")
            if s.get("push_error"):
                out.append(f'<p style="color:#b00020;">Not created in Prismic: {e(s["push_error"])}</p>')
            if s["problems"]:
                out.append('<p style="color:#b00020;margin:4px 0;">Needs edit:</p><ul style="color:#b00020;">'
                           + "".join(f"<li>{e(p)}</li>" for p in s["problems"]) + "</ul>")
            out.append('<p style="color:#666;font-size:13px;margin:4px 0;">Sources: ' + " · ".join(
                f'<a href="{e(a["url"], quote=True)}" style="color:#666;">{e(a["source"])}</a>'
                for a in s["articles"]) + "</p>")
            out.append("</div>")

    if skipped:
        out.append(f'<h3 style="{FONT}color:#666;">Skipped as already covered</h3><ul style="{FONT}color:#666;">'
                   + "".join(f"<li>{e(c['event_label'])}</li>" for c in skipped) + "</ul>")
    if failures:
        out.append(f'<h3 style="{FONT}color:#b00020;">Could not be written</h3><ul style="{FONT}">'
                   + "".join(f"<li>{e(c['event_label'])}: {e(err)}</li>" for c, err in failures) + "</ul>")
    if push_errors:
        out.append(f'<p style="{FONT}color:#b00020;">{push_errors} draft(s) failed to reach Prismic; see above.</p>')
    out.append(f'<p style="{FONT}color:#666;font-size:13px;">API cost of this run: {e(cost_summary)}</p>')
    return "".join(out)


# ── Send email ─────────────────────────────────────────────────────────────────
def send_email(html_body):
    gmail_address = os.environ["GMAIL_ADDRESS"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Fox and Lion news drafts {datetime.now(timezone.utc).strftime('%Y/%m/%d')}"
    msg["From"]    = gmail_address
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, os.environ["GMAIL_APP_PASSWORD"])
        server.sendmail(gmail_address, recipient, msg.as_string())
    print("Preview email sent.")


def write_out(name, content):
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / name).write_text(content, encoding="utf-8")
    print(f"Wrote {OUT_DIR / name}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = anthropic.Anthropic(max_retries=4)

    print("Fetching articles...")
    articles = dedupe_articles(fetch_articles())
    print(f"Fetched {len(articles)} unique articles. Selecting and grouping...")

    history = load_history()
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_PROMPT_DAYS)).strftime("%Y-%m-%d")
    recent = [h for h in history if h["date"] >= recent_cutoff]
    cluster_tally = Tally()
    clusters, skipped = select_and_cluster(client, CLUSTER_MODEL, articles, recent, tally=cluster_tally)
    print(f"{len(clusters)} new events, {len(skipped)} already covered ({cluster_tally.describe()}). "
          "Writing stories...")

    run_tally = Tally()
    run_tally.add(cluster_tally)
    stories, failures = write_stories(client, clusters, run_tally)
    per_story = f", ${run_tally.dollars / len(stories):.4f} per story" if stories else ""
    cost_summary = f"{run_tally.describe()}{per_story}"
    print(f"Run cost: {cost_summary}")
    taken = set()
    documents = [prismic.build_document(s["story"], s["category"], bool(s["problems"]), today, taken)
                 for s in stories]

    push_errors = 0
    if DRY_RUN:
        write_out("prismic_payloads.json", json.dumps(documents, ensure_ascii=False, indent=2))
    else:
        results = prismic.create_documents(documents, os.environ["PRISMIC_WRITE_TOKEN"])
        for s, (uid, doc_id, error) in zip(stories, results):
            s["uid"], s["push_error"] = uid, error
            if error:
                push_errors += 1
                print(f"Prismic rejected {uid}: {error}")
        print(f"Created {len(results) - push_errors} of {len(results)} drafts in Prismic.")

    body = build_email_html(stories, skipped, failures, push_errors, cost_summary)
    if DRY_RUN:
        write_out("email.html", body)
        write_out("stories.json", json.dumps([
            {"category": s["category"], "event_label": s["event_label"],
             **s["story"].model_dump(), "problems": s["problems"], "cost": s["cost"].describe(),
             "sources": [{k: a[k] for k in ("source", "title", "url", "summary")} for a in s["articles"]]}
            for s in stories
        ] + [{"skipped_as_covered": c["event_label"]} for c in skipped]
          + [{"failed": c["event_label"], "error": err} for c, err in failures]
          + [{"run_cost": cost_summary}],
            ensure_ascii=False, indent=2))
        print("Dry run: nothing sent, pushed or saved.")
        return

    send_email(body)
    history += [{"id": s["uid"], "date": today, "event_label": s["event_label"],
                 "urls": [a["url"] for a in s["articles"]]}
                for s in stories if not s.get("push_error")]
    save_history(history)


if __name__ == "__main__":
    main()
