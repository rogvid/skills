"""The two secret types, and the constants that bound them.

`Secret` is a value a demo types but must never show; `SecretLeak` is what a
take raises when one reaches something that leaves the machine. Both live here
rather than in a medium's module because every medium needs them and nothing
here needs a browser — which is what lets a test exercise the rules directly.
"""

from __future__ import annotations

# -- secrets -----------------------------------------------------------------
#
# Demos run against seeded-but-realistic data, and a published video leaks
# permanently. Two registries, both living here in the base rather than in a
# medium's module, because every medium needs them and the terminal recorder's
# PTY scrubber (issue #5) is meant to read the same one the web recorder does:
#
#   register_secret(...)  literal text that must never be captioned, spoken,
#                         or written into the beat log
#   redact(...)           where the secret *renders* — a web selector today;
#                         medium-specific, so each medium defines its own
#
# What `register_secret` buys is deliberately blunt: a caption or an interlude
# line containing a registered secret raises SecretLeak and **fails the take**.
# It does not quietly mask the line, because a secret in a caption is an
# authoring bug — the storyboard said to put it on screen and speak it aloud,
# and the only safe answer is to stop and make the author fix the words.
# `scrub()` is the softer sibling, for output nobody authored (a shell's stdout
# on the terminal path).

# What `scrub()` leaves behind. Fixed-width-ish and obviously deliberate, so a
# reader of a scrubbed line can tell "something was removed here" from "the
# tool mangled my output".
SECRET_MASK = "[redacted]"

# Shortest value `register_secret()` will accept.
#
# The floor is not a guess about what a secret looks like — it is a bound on
# what registering one *costs everything else*. A registered value is replaced
# by `scrub()` wherever it appears: in a beat's `selector`, in a still's
# filename, in caption text, in every line of terminal output, and in every
# evidence file. `register_secret("1234")` therefore rewrites a `:nth-child(1234)`
# selector, an account number in an unrelated table, and the `1234` in a
# timestamp — and the damage reads exactly like redaction working, which is the
# one failure mode that never gets noticed.
#
# Eight, because that is where a literal stops colliding with ordinary output by
# accident and starts being a value somebody chose. Below it the honest control
# is `redact()`, which covers the pixels an element paints and touches no text
# at all — so a four-digit PIN is still hideable, just not by find-and-replace.
SECRET_MIN_LEN = 8


class SecretLeak(RuntimeError):
    """A registered secret reached something that leaves the machine.

    Raised out of the storyboard, so the take dies before the mp4 is written
    (`__exit__` skips conversion when an exception is in flight). Never carries
    the secret in its message.
    """


class Secret:
    """A value the demo must type but must never show, speak, or log.

        rec.type_into("#token", Secret("sk-live-..."))

    Registering happens as a side effect of using it, so there is no way to
    type one and forget to register it.

    Deliberately **not** a `str` subclass, which would be more convenient and
    considerably more dangerous: `_verb_target` below picks the first string
    argument of a verb as that beat's `selector`, so a str-subclassed Secret
    handed to any verb would be written into timeline.json verbatim — a file
    this skill tells people to commit. Being a distinct type also makes
    `isinstance` the test for "this needs redacting", and makes an accidental
    f-string print the mask instead of the value.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("Secret() takes a non-empty string")
        self._value = value

    def reveal(self) -> str:
        """The real value. The only way to get it, and named so that reading
        the storyboard shows exactly where the plaintext is used."""
        return self._value

    def __repr__(self) -> str:
        return f"Secret(<{len(self._value)} chars>)"

    def __str__(self) -> str:
        return SECRET_MASK
