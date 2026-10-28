"""Select relevant articles and group the ones that report the same event.

One Claude call over the whole day's batch. The model only ever returns
article ids, never titles or URLs, so everything downstream is rehydrated
from our own fetched data rather than from model-typed text.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["UK", "EU", "Korea", "World"]


class StoryCluster(BaseModel):
    article_ids: list[int] = Field(description="Ids of every article reporting this one event.")
    category: Category
    event_label: str = Field(description="One plain sentence naming the event, for internal tracking.")
    already_covered_by: Optional[str] = Field(
        description="Id of a previously drafted story that already covers this event, "
                    "or null if it is new or carries materially new facts."
    )


class ClusterResult(BaseModel):
    clusters: list[StoryCluster] = Field(description="Most engagement-worthy first.")


SYSTEM_PROMPT = """You are the news desk editor for Fox and Lion, which covers defence technology for a UK, European and Korean audience.

You receive a numbered batch of articles from many outlets, plus a list of stories we drafted in recent days. Your job:

1. Select only articles relevant to defence technology: AI and autonomy, cyber, procurement reform, defence industrial policy, C-UAS, electronic warfare, space and similar. Ignore personnel announcements and general military operations news.
2. Drop opinion, analysis, commentary, podcast and interview pieces. We only rewrite reported news.
3. Drop sponsored or advertorial pieces. A general "Sponsored by" or "Underwritten by" banner on a show does not by itself make an article sponsored.
4. Drop exclusives: articles where the outlet presents its own original reporting, for example "exclusive", "has learned", "obtained by", "documents seen by" or unnamed sources speaking to that outlet. We cannot republish another outlet's reporting without credit. Announcements, contract awards, official statements and events reported by several outlets are fine.
5. Group the remaining articles so that each group reports one single event (the same contract award, the same test, the same announcement). Different outlets covering the same event belong in one group. Related but separate events stay in separate groups. Every selected article belongs to exactly one group.
6. Give each group one category: UK, EU, Korea, or World (everything else, including the United States and other regions).
7. If a group reports an event that matches one of the previously drafted stories, set already_covered_by to that story's id, unless the new articles carry materially new facts (a new figure, a decision, a next stage), in which case leave it null.
8. Order groups by likely engagement on the r/Defence_Tech_UK community, most engagement-worthy first."""


def _format_articles(articles):
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"[{i}] {a['source']} | {a['published']}\n{a['title']}\n{a['summary'][:600]}")
    return "\n\n".join(lines)


def _format_history(history):
    if not history:
        return "(none)"
    return "\n".join(f"{h['id']} | {h['date']} | {h['event_label']}" for h in history)


def select_and_cluster(client, model, articles, history, tally=None):
    """Returns (clusters, skipped): new-event clusters in rank order, each with an
    `articles` list rehydrated from `articles`, and the clusters dropped as
    already covered. Token usage is added to `tally` (costs.Tally) if given."""
    if not articles:
        return [], []

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        output_format=ClusterResult,
        messages=[{
            "role": "user",
            "content": f"Previously drafted stories:\n{_format_history(history)}\n\n"
                       f"Today's articles:\n\n{_format_articles(articles)}",
        }],
    )
    if tally is not None:
        tally.record(response)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Clustering call was refused: {response.stop_details}")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError(f"Clustering call returned no usable output (stop_reason={response.stop_reason})")

    clusters, skipped, used = [], [], set()
    for c in response.parsed_output.clusters:
        # Guard against out-of-range ids and an article claimed by two groups.
        ids = [i for i in dict.fromkeys(c.article_ids) if 1 <= i <= len(articles) and i not in used]
        if not ids:
            continue
        used.update(ids)
        entry = {
            "category": c.category,
            "event_label": c.event_label,
            "articles": [articles[i - 1] for i in ids],
        }
        (skipped if c.already_covered_by else clusters).append(entry)
    return clusters, skipped
