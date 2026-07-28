"""Acceptance criteria, and what a storyboard claimed against them.

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


def _ac_field(claims: list[str]) -> dict:
    """`{"ac": [...]}` when a beat claims something, `{}` when it does not.

    Absent-rather-than-empty for the reason `error` is absent on a beat that
    returned (issue #24): a take recorded before this key existed then reads
    exactly like an untagged beat, and `"ac": []` on all 28 beats of an
    untagged demo is noise in a file this skill tells people to commit.
    """
    return {"ac": claims} if claims else {}


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
                claimed[key].append(
                    {
                        "index": beat.get("index"),
                        "segment": beat.get("segment"),
                        "segment_index": beat.get("segment_index"),
                        "t_start": beat.get("t_start"),
                        "still": beat.get("still"),
                    }
                )
    return {
        "criteria": dict(criteria),
        # Every declared id is a key here, including the ones with an empty
        # list. A consumer iterating `claimed` sees the whole ticket rather
        # than only its demonstrated half.
        "claimed": claimed,
        "unclaimed": [key for key, beats_ in claimed.items() if not beats_],
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
