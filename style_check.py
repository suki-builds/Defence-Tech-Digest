"""Mechanical checks for the Fox and Lion news rules (style/fox-and-lion-writing-style.md).

Pure functions, no API calls. Each check returns human-readable violation
strings, which are fed back to the model verbatim on the repair call - so
they say what is wrong and quote the offending text.
"""
import re

TITLE_MAX_CHARS = 59          # "under 60 characters"
DESCRIPTION_MAX_CHARS = 149   # "under 150 characters"
DESCRIPTION_SENTENCES = 2
MAX_BULLETS = 3
BULLET_MAX_WORDS = 25
OVERLAP_WORDS = 8             # this many consecutive words shared with a source = copied
# A shared run only counts as copied if it has at least this many ordinary
# words, so names and titles ("U.S. Secretary of War Pete Hegseth") pass.
MIN_ORDINARY_WORDS = 3

# Words that do not count towards MIN_ORDINARY_WORDS: function words, and
# lower-case words that commonly appear inside official titles.
STOPWORDS = frozenset(
    "a an the of and or to in on for at by with from as into its their his her "
    "is was are were be been has have had will would that this which who".split()
)
TITLE_WORDS = frozenset(
    "chief scientific adviser advisor secretary minister deputy general director head "
    "officer executive chair chairman president vice state commander staff".split()
)

CONTRACTION = re.compile(
    r"\b\w+n[’']t\b"                                    # don't, isn't, won't
    r"|\b\w+[’'](?:re|ve|ll|d|m)\b"                       # they're, we've, it'll
    r"|\b(?:it|that|there|here|what|who|where|let|he|she)[’']s\b",
    re.IGNORECASE,
)
BARE_US = re.compile(r"\bUS\b(?!\.)")
THINK_TANK = re.compile(r"\bthink[- ]?tanks?\b", re.IGNORECASE)
# "It is not A, it is B" and close variants ("This was not X, it was Y").
NOT_A_BUT_B = re.compile(
    r"\b(?:is|was|are|were)\s+not\b[^.;!?]*?,\s*(?:it|this|that|they)\s+(?:is|was|are|were)\b",
    re.IGNORECASE,
)

# American spellings that have no place in British news copy. Lower-case and
# case-sensitive on purpose, so proper nouns ("U.S. Department of Defense",
# "Center for Naval Analyses") pass.
AMERICAN_SPELLINGS = re.compile(
    r"\b(?:"
    r"(?:organi|recogni|priori|moderni|militari|authori|characteri|emphasi|reali|"
    r"standardi|maximi|minimi|optimi|mobili|stabili|digiti|subsidi|petroli)z\w*"
    r"|\w+yz(?:e|es|ed|ing)"
    r"|defense|offense|centers?|centered|colors?|colored|favors?|favored|favorable"
    r"|honors?|honored|labor|armor|armored|harbors?|maneuvers?|fueled|fueling"
    r"|traveled|traveling|catalog|programs?"
    r")\b"
)
PROGRAM_OK_BEFORE = re.compile(r"(?:computer|software)\s+$", re.IGNORECASE)

# Phrases that point at our sources or at missing information. News copy
# states facts directly, as our own reporting.
META_REFERENCE = re.compile(
    r"\breportedly\b"
    r"|\baccording to (?:the )?(?:reports?|reporting|media|coverage)\b"
    r"|\bit (?:was|has been|is) reported\b"
    r"|\bno further details?\b",
    re.IGNORECASE,
)

# Abbreviations whose full stop does not end a sentence.
ABBREVIATIONS = re.compile(r"\b(?:U\.S|U\.K|Mr|Mrs|Ms|Dr|No|St|Gen|Lt|Col|Adm|Capt|approx|vs|e\.g|i\.e)\.")
SENTENCE_END = re.compile(r"[.!?](?=[\"'’”)]*(?:\s|$))")


def _words(text):
    return re.findall(r"[a-z0-9]+(?:['’][a-z]+)?", text.lower())


def count_sentences(text):
    masked = ABBREVIATIONS.sub(lambda m: m.group(0)[:-1] + "_", text.strip())
    return len(SENTENCE_END.findall(masked))


def _american_spellings(text):
    found = []
    for m in AMERICAN_SPELLINGS.finditer(text):
        word = m.group(0)
        if word.startswith("program") and PROGRAM_OK_BEFORE.search(text[: m.start()]):
            continue
        found.append(word)
    return found


def check_text(label, text):
    """Rules that apply to any piece of news copy."""
    problems = []
    for m in CONTRACTION.finditer(text):
        problems.append(f'{label}: contraction "{m.group(0)}" - write it out in full.')
    if "—" in text:
        problems.append(f"{label}: contains an em dash (—). Em dashes are not allowed.")
    if "–" in text:
        problems.append(f"{label}: contains an en dash (–). In news, avoid en dashes; rephrase.")
    if BARE_US.search(text):
        problems.append(f'{label}: write "U.S." not "US".')
    if THINK_TANK.search(text):
        problems.append(f'{label}: never use "think tank".')
    m = NOT_A_BUT_B.search(text)
    if m:
        problems.append(f'{label}: avoid the "it is not A, it is B" construction ("{m.group(0)}").')
    for word in _american_spellings(text):
        problems.append(f'{label}: American spelling "{word}" - use the British form.')
    for m in META_REFERENCE.finditer(text):
        problems.append(f'{label}: "{m.group(0)}" refers to sources or missing detail - state facts directly or leave it out.')
    return problems


def _is_ordinary(word):
    """A lower-case word that is not a function word or part of a job title.
    Capitalised words, acronyms and numbers are names, not phrasing."""
    return word[0].islower() and word.lower() not in STOPWORDS | TITLE_WORDS


def find_copied_phrases(text, source_texts, n=OVERLAP_WORDS):
    """Runs of `n`+ consecutive words in `text` that also appear in a source,
    ignoring runs that are mostly names and titles."""
    source_grams = set()
    for src in source_texts:
        w = _words(src)
        source_grams.update(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    original = re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?", text)
    w = [o.lower() for o in original]
    copied, i = [], 0
    while i <= len(w) - n:
        if tuple(w[i:i + n]) in source_grams:
            j = i + n
            while j < len(w) and tuple(w[j - n + 1:j + 1]) in source_grams:
                j += 1
            if sum(_is_ordinary(o) for o in original[i:j]) >= MIN_ORDINARY_WORDS:
                copied.append(" ".join(w[i:j]))
            i = j
        else:
            i += 1
    return copied


def check_story(title, description, bullets, source_texts):
    """All news rules for one story. Returns a list of violations (empty = clean)."""
    problems = []

    if len(title) > TITLE_MAX_CHARS:
        problems.append(f"Title is {len(title)} characters; it must be under 60.")
    if len(description) > DESCRIPTION_MAX_CHARS:
        problems.append(f"Description is {len(description)} characters; it must be under 150.")
    n = count_sentences(description)
    if n != DESCRIPTION_SENTENCES:
        problems.append(f"Description has {n} sentence(s); it must have exactly two.")
    if not 1 <= len(bullets) <= MAX_BULLETS:
        problems.append(f"There are {len(bullets)} bullets; there must be one to three.")
    for i, b in enumerate(bullets, 1):
        words = len(b.split())
        if words > BULLET_MAX_WORDS:
            problems.append(f"Bullet {i} is {words} words; the maximum is 25.")

    problems += check_text("Title", title)
    problems += check_text("Description", description)
    for i, b in enumerate(bullets, 1):
        problems += check_text(f"Bullet {i}", b)

    for part in (title, description, *bullets):
        for phrase in find_copied_phrases(part, source_texts):
            problems.append(f'Copied wording from a source: "{phrase}". Rewrite it in our own words.')

    return problems
