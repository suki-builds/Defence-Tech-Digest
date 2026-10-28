"""Fetch the full text of source articles, for the writer only.

RSS feeds carry a teaser of a paragraph or two; the writer needs the whole
article to produce a full news piece. Pages that fail, are paywalled or
yield only a teaser return None, and the writer falls back to the feed text.
"""
import requests
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FoxAndLionNews/1.0)"}
TIMEOUT_SECONDS = 20
MIN_WORDS = 150        # less than this is a teaser or a paywall stub, not an article
MAX_CHARS = 10_000     # caps the cost of very long pieces


def fetch_full_text(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=False,
                               favor_precision=True)
    if not text or len(text.split()) < MIN_WORDS:
        return None
    return text[:MAX_CHARS]


def add_full_text(clusters):
    """Sets `full_text` (str or None) on every article in `clusters`."""
    for c in clusters:
        for a in c["articles"]:
            a["full_text"] = fetch_full_text(a["url"]) if a["url"] else None
