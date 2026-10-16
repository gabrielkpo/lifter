"""The quote check: a change applied by the coach must cite the athlete's own words.

ADR 0002, Decision 2: every write cites a passage of the athlete's message, checked word for
word by code. The message is read from the database (`conversation_message`, written by the
conversation endpoint before the model runs), never from a copy the model supplies, so a model
that invents "the athlete said ..." cannot pass.

Only formatting is normalised, never the words: Unicode NFC, typographic quotes and apostrophes,
runs of whitespace. Matching is on whole words: the quote's words must appear in the message as
a contiguous run (case kept, punctuation ignored), never as a piece of a word. A one-word quote
("ok", "annule") is accepted only where the operation allows it, and only when it is the whole
message: "ok" inside "pas ok" or "book" never counts.

Known limit: a quote proves the athlete wrote those words, not what he meant ("ne décale pas
jeudi" contains "décale"; quotes of two words or more must still be a contiguous run of his
words). The coach's prompt and the bench's conversation scenarios cover intent.

This module lives outside `lifter.agents`: the operations catalogue imports it, and the domain
does not depend on the agents.
"""

import re
import unicodedata

import psycopg

MIN_WORDS = 2  # a short quote ("ok", "annule") only where the operation allows it
_QUOTES = str.maketrans(
    {
        "‘": "'",  # ‘
        "’": "'",  # ’
        "‚": "'",  # ‚
        "′": "'",  # ′
        "“": '"',  # “
        "”": '"',  # ”
        "„": '"',  # „
        "«": '"',  # «
        "»": '"',  # »
    }
)
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"\w+")


def words(text: str) -> list[str]:
    """The words of `text` once normalised, in order, punctuation dropped."""
    return _WORD.findall(normalize(text))


def _negated_at(text: str, index: int) -> bool:
    """The word before word `index` of `text` is a negation, joined to it by spaces or an
    apostrophe only: "pas ok" or "n'annule", not "non : décale" (a new clause)."""
    if index == 0:
        return False
    spans = list(_WORD.finditer(normalize(text)))
    before, word = spans[index - 1], spans[index]
    gap = normalize(text)[before.end() : word.start()]
    return before.group().lower() in NEGATIONS and gap.strip(" '") == ""


# Words that carry no instruction on their own: two of them ("la semaine", "ok pour") must not be
# enough to justify a change. Compared lower-case, French and English.
FUNCTION_WORDS = frozenset(
    """
    a à au aux avec c ça ce ces cet cette d dans de des du elle elles en est et il ils j je l la
    le les leur lui m ma me mes moi mon n ne nous on ou où par pour qu que qui s sa se ses son
    sur t ta te tes toi ton tu un une vos votre vous y ok okay oui yes
    a an and are at be for from i in is it me my of on or so the then this to we you your
    """.split()
)
# A negation just before the quote turns it around: "pas ok pour la 2" is not "ok pour la 2".
NEGATIONS = frozenset("pas ne n non jamais plus not no never don t".split())


def _content(run: list[str]) -> list[str]:
    return [w for w in run if w.lower() not in FUNCTION_WORDS]


def _occurrences(run: list[str], seq: list[str]) -> list[int]:
    n = len(run)
    return [i for i in range(len(seq) - n + 1) if seq[i : i + n] == run]


class QuoteError(ValueError):
    """The quote is not the athlete's words: refused, nothing is applied."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return _SPACES.sub(" ", text).strip()


def check_quote(quote: str, message: str, *, short_ok: bool = False) -> None:
    """Raise QuoteError unless `quote` is a contiguous run of the words of `message`, not
    preceded by a negation, with at least MIN_WORDS words that are not function words. Where
    the operation allows a short quote (`short_ok`: "ok pour la 2", "annule"), fewer content
    words are enough, and a one-word quote must be the athlete's whole message."""
    cited, said = words(quote), words(message)
    if not cited:
        raise QuoteError("the change cites nothing from the athlete's message")
    if len(cited) == 1 and short_ok:
        if cited != said:
            raise QuoteError("a one-word quote must be the athlete's whole message")
        return
    if len(_content(cited)) < MIN_WORDS and not short_ok:
        raise QuoteError(
            f"the quote must contain at least {MIN_WORDS} words of the athlete's message"
            " besides words such as 'la', 'pour' or 'ok'"
        )
    found = _occurrences(cited, said)
    if not found:
        raise QuoteError("the quote is not in the athlete's message")
    if all(_negated_at(message, i) for i in found):
        raise QuoteError("the athlete's words are negated just before the quote")


def verify_quote(
    conn: psycopg.Connection, message_id: int, quote: str, *, short_ok: bool = False
) -> None:
    """Check `quote` against the athlete's message `message_id`, read from the database."""
    row = conn.execute(
        "select role, text from public.conversation_message where id = %s", (message_id,)
    ).fetchone()
    if row is None:
        raise QuoteError(f"message {message_id} does not exist")
    role, text = row
    if role != "athlete":
        raise QuoteError(f"message {message_id} is not from the athlete")
    check_quote(quote, text, short_ok=short_ok)
