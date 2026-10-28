"""Create news_post drafts in Prismic through the Migration API.

Documents land as drafts in the repository's Migration Release, where they
are reviewed, edited and published by hand. Nothing here publishes.
Field names follow customtypes/news_post/index.json in the website repo.
"""
import re
import time
import unicodedata

import requests

MIGRATION_API = "https://migration.prismic.io/documents"
REPOSITORY = "fox-and-lion"
DASHBOARD_URL = f"https://{REPOSITORY}.prismic.io/"
DOCUMENT_TYPE = "news_post"
LANG = "en-us"
SECONDS_BETWEEN_REQUESTS = 1.1   # Migration API allows one request per second
MAX_ATTEMPTS = 3


def slugify(text, max_len=60):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"['.]", "", text)   # "U.S. Navy's" -> "US Navys", not "u-s-navy-s"
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def build_document(story, category, needs_edit, date_str, taken_uids):
    """The Migration API request body for one story. `taken_uids` (a set) keeps
    uids unique within a run and is updated in place."""
    base = f"{slugify(story.title)}-{date_str.replace('-', '')}"
    uid, n = base, 2
    while uid in taken_uids:
        uid, n = f"{base}-{n}", n + 1
    taken_uids.add(uid)

    tags = [category, "auto-draft"] + (["needs-edit"] if needs_edit else [])
    return {
        "title": story.title,
        "type": DOCUMENT_TYPE,
        "uid": uid,
        "lang": LANG,
        "tags": tags,
        "data": {
            "title": story.title,
            "meta_title": story.title,
            "meta_description": story.description,
            "commentary": [{"type": "list-item", "text": b, "spans": []} for b in story.bullets],
            # source_url left empty: no attribution. published_at left empty so the
            # site falls back to the date the post is actually published in Prismic.
            "source_url": "",
        },
    }


def create_documents(documents, write_token, repository=REPOSITORY):
    """POSTs each document, one per second. Returns a list of (uid, id, error),
    with id None and error set for any document that failed."""
    headers = {
        "Authorization": f"Bearer {write_token}",
        "repository": repository,
        "Content-Type": "application/json",
    }
    results = []
    for i, doc in enumerate(documents):
        if i:
            time.sleep(SECONDS_BETWEEN_REQUESTS)
        doc_id, error = _post_with_retry(doc, headers)
        results.append((doc["uid"], doc_id, error))
    return results


def _post_with_retry(doc, headers):
    error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(MIGRATION_API, json=doc, headers=headers, timeout=30)
        except requests.RequestException as e:
            error = str(e)
        else:
            if resp.status_code == 201:
                return resp.json().get("id"), None
            error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code != 429 and resp.status_code < 500:
                return None, error   # a client error will not fix itself on retry
        if attempt < MAX_ATTEMPTS:
            time.sleep(2 * attempt)
    return None, error
