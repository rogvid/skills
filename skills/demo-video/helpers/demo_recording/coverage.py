"""Acceptance criteria, what a storyboard claimed against them, and whose
ticket they were copied out of.

A pure function of the declared criteria and the beat list, so a stitched demo
merges the same way a single take builds it, and a consumer can re-run the
report over a committed timeline.json without re-recording.
"""

from __future__ import annotations

import re

# -- acceptance criteria and coverage (issue #12) -----------------------------
#
# A demo can be perfectly clear and demonstrate the wrong thing. The reviewer
# this skill already asks for answers *"is this story clear?"*; a review gate
# has to answer *"does this show what the ticket asked for?"*, which is a
# different question with a different answer.
#
# So a take can be recorded **against a ticket**: the criteria are declared on
# the recorder, individual beats tag themselves with the criterion they are
# there to show, and the timeline carries a coverage report naming any
# criterion no beat claimed.
#
# **The report records what the storyboard CLAIMED, never what it proved, and
# every name in it says so.** `claimed` and `unclaimed`, not `demonstrated` and
# `missing`. This is the whole honesty of the feature and it is worth being
# explicit about why:
#
#   * An `ac=` tag is a string the storyboard author typed. It is evidence of
#     intent and nothing else. A beat tagged `AC-3` whose frames show an error
#     page is still tagged `AC-3`.
#   * The failure this exists to catch is the *tautology* — a storyboard
#     derived from the diff rather than from the ticket, which produces a
#     polished, convincing demo of a misread requirement. If this file said
#     "AC-3 demonstrated", a conformance reviewer reading it would be taking
#     the author's word for exactly the thing it was convened to check. It
#     would share the blind spot of the bug it exists to find.
#   * So the artifact's job is to put the reviewer in front of the right
#     frames — which beats claim which criterion, at what timestamp, with
#     which still — and the verdict stays with the reviewer.
#
# `unclaimed` is the one machine-checkable finding here, and it is safe to
# automate precisely because it needs no judgement: nobody even asserted it.
#
# A claim's `error` is the second, and it needs no judgement either: it is the
# beat's own record of the verb raising. A claim made by a beat that threw is
# not a claim the take kept, and rendering it like one is the artifact lying
# (issue #278).

# How a criterion id may be written. Deliberately narrow — these become table
# rows, filenames in a reviewer's prompt and keys in a JSON object, and an id
# holding a pipe or a newline breaks the first two silently.
_AC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def _checked_criteria(criteria: dict[str, str] | None) -> dict[str, str]:
    """Validate a declared criteria map, or `{}` when none was declared.

    Raises rather than dropping a bad entry: a criterion silently missing from
    this map is a criterion that can never be reported `unclaimed`, which is
    the one finding the coverage report exists to produce.
    """
    if criteria is None:
        return {}
    if not isinstance(criteria, dict):
        raise TypeError(
            f"criteria must be a dict of {{id: text}}, got {type(criteria).__name__}"
        )
    checked: dict[str, str] = {}
    for key, text in criteria.items():
        if not isinstance(key, str) or not _AC_ID.match(key):
            raise ValueError(
                f"criterion id {key!r} is not usable: ids are 1-40 characters "
                f"of letters, digits, dot, dash or underscore, starting with a "
                f"letter or digit (e.g. 'AC-3')"
            )
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"criterion {key!r} has no text. The text is what a reviewer "
                f"judges the frames against — an id on its own says nothing."
            )
        checked[key] = text.strip()
    return checked


# -- the ticket the clauses came out of (issue #275) --------------------------
#
# `criteria={...}` declares four sentences and, until this existed, nothing
# anywhere recorded which ticket they were copied out of — in the reference
# storyboard it lived in a Python docstring. A manifest that quotes four
# clauses but cannot name their source cannot be checked against that source by
# anything, and a reviewer cannot click through from the demo to the
# requirement.
#
# **Never fetched and never resolved.** The recorder refuses a public target at
# construction, before a browser opens; a call to a tracker inside a take is
# exactly the coupling that machinery exists to avoid. It would also put a
# network dependency and a credential inside a take, and make re-running a
# committed storyboard produce a *different* manifest whenever somebody edited
# the issue — the artifact would stop being a function of the file in git.
# Whether the quoted clauses actually appear in the named ticket is a separate,
# non-fatal step with a network and a token, and it is not this file's.


def _checked_ticket(ticket: str | None) -> str | None:
    """The ticket this take was recorded against, or None when there is none.

    Checked for exactly one thing: that it is a non-empty string. A private
    tracker's id is not this recorder's business to have opinions about, and a
    shape rule here would refuse takes rather than catch mistakes — the
    consumers that *can* use a shape (linking `owner/repo#N`) try it and print
    the string verbatim when it does not fit.
    """
    if ticket is None:
        return None
    if not isinstance(ticket, str):
        raise TypeError(
            f"ticket must be a string — the ticket this take demonstrates, as "
            f"you write it ('rogvid/skills#129', or a URL) — got "
            f"{type(ticket).__name__}"
        )
    stripped = ticket.strip()
    if not stripped:
        raise ValueError(
            "ticket is empty. Name the ticket this take was recorded against, "
            "or leave the parameter off — a blank string is a take that "
            "claims to have a source and cannot say what it is."
        )
    return stripped


def _ticket_field(ticket: object) -> dict:
    """`{"ticket": ...}` when there is one, `{}` when there is not.

    Absent-rather-than-null for the reason `error` is absent on a beat that
    returned (issue #24): a take recorded before this key existed then reads
    exactly like a take recorded outside a ticket, which is what it is.
    """
    return {"ticket": ticket} if ticket else {}


def _merged_ticket_fields(docs: list[dict]) -> dict:
    """What a stitched demo says about the ticket(s) its segments named.

    Every distinct ticket, in the order the segments named them. One of them —
    including the case where only some segments named one, since silence is not
    disagreement — is the merged demo's `ticket`.

    Two or more is a **conflict**, and it is named rather than resolved, the
    same treatment `coverage.conflicts` gives segments that disagree about a
    clause's wording. `ticket` is then absent: a merged demo half of which
    demonstrates another ticket has no single honest answer, and writing one of
    them there would be the artifact stating something no segment said.
    """
    named: list[str] = []
    for doc in docs:
        ticket = doc.get("ticket")
        if isinstance(ticket, str) and ticket.strip():
            if ticket.strip() not in named:
                named.append(ticket.strip())
    if len(named) > 1:
        return {"ticket_conflicts": named}
    return _ticket_field(named[0] if named else None)


def _ac_field(claims: list[str]) -> dict:
    """`{"ac": [...]}` when a beat claims something, `{}` when it does not.

    Absent-rather-than-empty for the reason `error` is absent on a beat that
    returned (issue #24): a take recorded before this key existed then reads
    exactly like an untagged beat, and `"ac": []` on all 28 beats of an
    untagged demo is noise in a file this skill tells people to commit.
    """
    return {"ac": claims} if claims else {}


#: What a beat's `ac=` tag says about the clause it names. `MET` is the
#: default and is **never written down**: every `ac=` tag before #374 meant
#: it, so writing it now would change every timeline this skill has produced
#: and hand a reader `shows: "met"` to interpret on a beat that always meant
#: exactly that. `UNMET` is the whole signal — the #24 rule, as `error`,
#: `failure` and `mode` all follow it.
MET = "met"
UNMET = "unmet"
SHOWS = (MET, UNMET)


def _checked_shows(shows: object, claims: list[str], where: str) -> str:
    """Which way this beat's claim points, refused at the call if it is neither.

    **`shows="unmet"` with no `ac=` is refused**, and that is the important
    half. Unmet *what*? A beat marked as evidence against nothing in
    particular is a storyboard author's slip, and letting it through produces
    the one artifact this feature must not produce: a take that reads as
    reporting a problem while naming no clause anybody can check.
    """
    if shows is None:
        return MET
    if shows not in SHOWS:
        raise ValueError(
            f"{where} was given shows={shows!r}: it is one of "
            f"{', '.join(repr(s) for s in SHOWS)}. "
            f"{MET!r} is the default and needs no saying."
        )
    if shows == UNMET and not claims:
        raise ValueError(
            f"{where} was given shows={UNMET!r} with no ac=. A beat marked as "
            f"evidence a criterion is not met has to name the criterion — "
            f"without one it reports a problem nobody can check. Add "
            f"ac=\"AC-n\", or drop shows=."
        )
    return str(shows)


def _shows_field(shows: str) -> dict:
    """`{"shows": "unmet"}` on a beat that claims the opposite, `{}` otherwise.

    See `MET`. Absent-rather-than-default, so a take recorded before this key
    existed reads exactly as it always did.
    """
    return {"shows": shows} if shows == UNMET else {}


def _claim_row(beat: dict) -> dict:
    """One row of `claimed[id]`: where the claim was made, and whether it held.

    `error` is present **only** when the beat's verb raised, and absent
    otherwise — the #24 rule, so a take recorded before this key existed reads
    exactly like one whose beats all returned.

    It is copied here rather than left for a consumer to look up in `beats`
    because every renderer of this report reads the row and never the beat.
    Without it a claim made by a beat that threw is indistinguishable from one
    that worked, and a `shot("07-x", ac="AC-3")` whose screenshot raised
    produces a row naming a still the take never wrote — an artifact reporting
    success on failure, inside the feature whose whole purpose is honesty about
    claims (issue #278).
    """
    row = {
        "index": beat.get("index"),
        "segment": beat.get("segment"),
        "segment_index": beat.get("segment_index"),
        "t_start": beat.get("t_start"),
        "still": beat.get("still"),
    }
    # Which way this claim points (#374), copied here for the same reason
    # `error` is: every renderer of this report reads the row and never the
    # beat, and a row that does not carry the polarity renders a beat saying
    # "this clause is not met" identically to one saying it is. Absent on an
    # ordinary claim.
    if beat.get("shows") == UNMET:
        row["shows"] = UNMET
    error = beat.get("error")
    if isinstance(error, dict):
        # `type` and `message`, not the beat's dict by reference: a renderer
        # that mutated this row would otherwise reach into `beats`.
        row["error"] = {
            "type": error.get("type"),
            "message": error.get("message"),
        }
    return row


def coverage_report(criteria: dict[str, str], beats: list[dict]) -> dict | None:
    """Which criteria the storyboard **claimed**, and which nothing claimed.

    None when no criteria were declared: a take recorded outside a ticket has
    no coverage to report, and an empty report would read as a take that
    covered nothing.

    A pure function of the two inputs, so a stitched demo merges the same way a
    single take builds it, and so a consumer can re-run it over a committed
    `timeline.json` without re-recording.
    """
    if not criteria:
        return None
    claimed: dict[str, list[dict]] = {key: [] for key in criteria}
    tagged = 0
    for beat in beats:
        ids = beat.get("ac") or []
        if not isinstance(ids, list) or not ids:
            continue
        tagged += 1
        for key in ids:
            if key in claimed:
                claimed[key].append(_claim_row(beat))
    return {
        "criteria": dict(criteria),
        # Every declared id is a key here, including the ones with an empty
        # list. A consumer iterating `claimed` sees the whole ticket rather
        # than only its demonstrated half.
        "claimed": claimed,
        "unclaimed": [key for key, beats_ in claimed.items() if not beats_],
        # The clauses at least one beat marks as **not** met (#374). A
        # roll-up rather than something every consumer derives by walking the
        # rows: "which clauses does this take say are broken" is the first
        # question a reviewer has, and a derived answer is one each renderer
        # can get subtly differently.
        #
        # Separate from `unclaimed`, and the two mean different things. A
        # clause here was claimed — a storyboard author pointed a frame at it
        # and said it does not hold. A clause in `unclaimed` had no beat at
        # all. Merging them would report "nobody showed this" for the case
        # where somebody showed it failing, which is the more useful evidence
        # of the two.
        "unmet": [
            key
            for key, rows in claimed.items()
            if any(row.get("shows") == UNMET for row in rows)
        ],
        "tagged_beats": tagged,
        "untagged_beats": len(beats) - tagged,
    }


def _merged_coverage(docs: list[dict], beats: list[dict]) -> dict | None:
    """The coverage report for a demo stitched out of several segments.

    `docs` supplies the declared criteria — the union of what each segment was
    recorded against — and `beats` is the *merged*, renumbered beat list the
    report has to point at.

    A demo whose segments were recorded against different halves of one ticket
    is the ordinary case: the web part shows AC-1 and AC-2, the terminal part
    shows AC-3. Taking the union is what lets the joined timeline report AC-4
    unclaimed when no segment claimed it — which neither segment's own report
    could say, since neither knew the other's criteria.
    """
    criteria, conflicts = _declared_criteria(docs)
    report = coverage_report(criteria, beats)
    if report is not None and conflicts:
        # Named rather than resolved: two segments recorded against different
        # wordings of the same id is a storyboard mistake somebody has to see,
        # and silently keeping the first text would hide it behind a report
        # that looks complete.
        report["conflicts"] = conflicts
    return report


def _declared_criteria(docs: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Every criterion the segments declared, and any id they disagree on.

    A conflict is kept rather than resolved — first text wins in the map, and
    the id is named in `conflicts` so the merged document says the segments
    were recorded against different wordings instead of quietly picking one.
    """
    merged: dict[str, str] = {}
    conflicts: list[str] = []
    for doc in docs:
        coverage = doc.get("coverage")
        if not isinstance(coverage, dict):
            continue
        for key, text in (coverage.get("criteria") or {}).items():
            if key in merged and merged[key] != text:
                if key not in conflicts:
                    conflicts.append(key)
                continue
            merged.setdefault(key, text)
    return merged, conflicts
