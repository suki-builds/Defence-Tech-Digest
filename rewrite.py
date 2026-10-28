"""Write one Fox and Lion news item from a cluster of source articles."""
import re
from pathlib import Path

from pydantic import BaseModel, Field

STYLE_GUIDE_PATH = Path(__file__).parent / "style" / "fox-and-lion-writing-style.md"
# Sections of the guide that apply to news. §2 (analysis) is left out so its
# long, measured sentences do not leak into news copy.
NEWS_SECTIONS = ("1.", "3.", "5.")

FALLBACK_BETAS = ["server-side-fallback-2026-07-01"]


class Story(BaseModel):
    title: str = Field(description="Headline, under 60 characters.")
    description: str = Field(description="Exactly two sentences, under 150 characters in total.")
    bullets: list[str] = Field(description="One to three bullets, each 25 words or fewer, no labels.")


def load_news_style_guide(path=STYLE_GUIDE_PATH):
    """The guide's preamble plus the sections that apply to news, verbatim."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=## )", text)
    keep = [parts[0]] + [p for p in parts[1:] if p[3:].startswith(NEWS_SECTIONS)]
    return "".join(keep).strip()


def build_system_prompt(style_guide):
    return f"""You write news items for Fox and Lion, a defence technology analysis network. Every item is published under the Fox and Lion name, so it must read as our own reporting.

Follow the house style guide below exactly. Where it says News, it applies to you; ignore anything marked Unconfirmed.

<style_guide>
{style_guide}
</style_guide>

How to write each item:
- You receive one or more source articles about a single event. Combine their facts into one item.
- Use only facts present in the sources. Never invent figures, names, dates or quotes. If the sources are thin, write fewer bullets rather than pad.
- Write entirely in your own words. Do not reuse phrasing from the sources, and do not quote them.
- Do not mention or credit the source outlets or their reporters.
- Sources in other languages are written up in British English.
- State facts directly, as our own reporting. Never refer to reporting, sources or missing information: no "reportedly", "according to reports", "it was reported" or "no further detail was provided".
- Keep facts that matter to a defence technology reader: what happened, who, how much, when and why it matters. Leave out trivia such as how long a meeting lasted, and vague filler such as "work began some time ago".
- title: the headline, under 60 characters.
- description: exactly two sentences, under 150 characters in total. Aim for 120 to 140 characters so it stays safely under the limit.
- bullets: one to three, each 25 words or fewer, plain language, no labels or lead-in words. Every bullet must add a fact that is not already in the title or description; never restate them. If no new facts remain, one bullet is enough."""


def _format_sources(articles):
    return "\n\n".join(
        f"Source {i} | {a['published']}\nTitle: {a['title']}\n{a['summary']}"
        for i, a in enumerate(articles, 1)
    )


def write_story(client, model, system_prompt, articles, previous=None, violations=None, tally=None):
    """One call. With `previous` and `violations`, asks for a corrected version.
    The repair is a fresh single-turn request, not a replayed conversation.
    Token usage is added to `tally` (costs.Tally) if given."""
    content = _format_sources(articles)
    if previous is not None:
        content += (
            f"\n\nA draft of this item was written already:\n{previous.model_dump_json(indent=1)}"
            "\n\nIt breaks these rules:\n- " + "\n- ".join(violations)
            + "\n\nReturn a corrected version that fixes every one and changes nothing else."
        )
    messages = [{"role": "user", "content": content}]

    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        betas=FALLBACK_BETAS,
        fallbacks="default",
        # Cache the style-guide system prompt: identical across every story in a run.
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "medium"},
        output_format=Story,
        messages=messages,
    )
    if tally is not None:
        tally.record(response)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Rewrite was refused: {response.stop_details}")
    if response.parsed_output is None:
        raise RuntimeError(f"Rewrite returned no usable output (stop_reason={response.stop_reason})")
    return response.parsed_output
