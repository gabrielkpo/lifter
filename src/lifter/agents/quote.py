"""The quote check: a change applied by the coach must cite the athlete's own words.

ADR 0002, Decision 2: every write cites a passage of the athlete's message, checked word for
word by code. The message is read from the database (`conversation_message`, written by the
conversation endpoint before the model runs), never from a copy the model supplies, so a model
that invents "the athlete said ..." cannot pass.

Only formatting is normalised, never the words: Unicode NFC, typographic quotes and apostrophes,
runs of whitespace. Case is kept: a quote is a copy, not a paraphrase.
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


class QuoteError(ValueError):
    """The quote is not the athlete's words: refused, nothing is applied."""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return _SPACES.sub(" ", text).strip()


def check_quote(quote: str, message: str, *, short_ok: bool = False) -> None:
    """Raise QuoteError unless `quote` appears in `message` once both are normalised."""
    cited = normalize(quote)
    if not cited:
        raise QuoteError("the change cites nothing from the athlete's message")
    if not short_ok and len(_WORD.findall(cited)) < MIN_WORDS:
        raise QuoteError(
            f"the quote must contain at least {MIN_WORDS} words of the athlete's message"
        )
    if cited not in normalize(message):
        raise QuoteError("the quote is not in the athlete's message")


def verify_quote(
    conn: psycopg.Connection, message_id: int, quote: str, *, short_ok: bool = False
) -> None:
    """Check `quote` against the athlete's message `message_id`, read from the database."""
    row = conn.execute(
        "select role, text from conversation_message where id = %s", (message_id,)
    ).fetchone()
    if row is None:
        raise QuoteError(f"message {message_id} does not exist")
    role, text = row
    if role != "athlete":
        raise QuoteError(f"message {message_id} is not from the athlete")
    check_quote(quote, text, short_ok=short_ok)
