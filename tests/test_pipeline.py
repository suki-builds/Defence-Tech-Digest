from types import SimpleNamespace

import prismic
from cluster import ClusterResult, StoryCluster, select_and_cluster
from rewrite import Story, load_news_style_guide


def test_style_guide_keeps_news_sections_only():
    guide = load_news_style_guide()
    assert "## 1. Rules for both analysis and news" in guide
    assert "## 3. News" in guide
    assert "## 5. Pre-publication check" in guide
    assert "## 2. Analysis" not in guide
    assert "## 4. Unconfirmed" not in guide
    assert "HMS Dragon" not in guide  # analysis reference paragraphs stay out


def test_slugify():
    assert prismic.slugify("U.S. Navy’s new drone – first flight!") == "us-navys-new-drone-first-flight"


def test_build_document_maps_news_post_fields():
    story = Story(title="Navy orders drones", description="One. Two.", bullets=["A.", "B."],
                  body=["First paragraph.", "Second paragraph."])
    taken = set()
    doc = prismic.build_document(story, "UK", True, "2026-10-28", taken)
    assert doc["type"] == "news_post" and doc["lang"] == "en-us"
    assert doc["uid"] == "navy-orders-drones-20261028"
    assert doc["tags"] == ["UK", "auto-draft", "needs-edit"]
    assert doc["data"]["meta_description"] == "One. Two."
    assert doc["data"]["source_url"] == ""
    assert doc["data"]["commentary"] == [
        {"type": "list-item", "text": "A.", "spans": []},
        {"type": "list-item", "text": "B.", "spans": []},
        {"type": "paragraph", "text": "First paragraph.", "spans": []},
        {"type": "paragraph", "text": "Second paragraph.", "spans": []},
    ]
    # A second story with the same headline gets a distinct uid.
    assert prismic.build_document(story, "UK", False, "2026-10-28", taken)["uid"] == "navy-orders-drones-20261028-2"


class FakeMessages:
    def __init__(self, result):
        self.result = result

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=self.result)


def test_select_and_cluster_rehydrates_and_guards_ids():
    articles = [{"title": f"t{i}", "summary": "s", "url": f"u{i}", "source": "src", "published": "2026-10-28"}
                for i in range(1, 5)]
    result = ClusterResult(clusters=[
        StoryCluster(article_ids=[2, 1, 2, 99], category="UK", event_label="A", already_covered_by=None),
        StoryCluster(article_ids=[1, 3], category="EU", event_label="B", already_covered_by=None),
        StoryCluster(article_ids=[4], category="World", event_label="C", already_covered_by="old-uid"),
    ])
    client = SimpleNamespace(messages=FakeMessages(result))
    clusters, skipped = select_and_cluster(client, "m", articles, history=[])
    assert [a["url"] for a in clusters[0]["articles"]] == ["u2", "u1"]   # dupes and 99 dropped
    assert [a["url"] for a in clusters[1]["articles"]] == ["u3"]         # 1 already claimed
    assert [c["event_label"] for c in skipped] == ["C"]


def test_full_text_falls_back_to_none(monkeypatch):
    import requests
    import fulltext

    def fail(*args, **kwargs):
        raise requests.ConnectionError("blocked")
    monkeypatch.setattr(fulltext.requests, "get", fail)
    clusters = [{"articles": [{"url": "https://example.com/a"}, {"url": ""}]}]
    fulltext.add_full_text(clusters)
    assert [a["full_text"] for a in clusters[0]["articles"]] == [None, None]
