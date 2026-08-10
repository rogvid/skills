---
name: learn
description: Manually invoked — use when the user runs /learn, or explicitly asks to learn a topic properly, find the gaps in their understanding, be quizzed on something, or be taught rather than just handed an answer. Not for ordinary questions where the user just wants the answer — answering directly is the right move there. Diagnoses the edge of what the user knows with calibration questions, maps what is solid, shaky, and missing, teaches one gap at a time with retrieval practice, and closes by distilling the session into whatever the user's own system reuses — a resumable topic note, a PKM/TIL note, retrieval-shaped flashcards, or a blog seed — built from what the user actually got wrong.
disable-model-invocation: true
---

# learn — find the edge of what you know, then teach from there

The bottleneck in self-directed learning is not explanation — explanations are
cheap and you can generate excellent ones on demand. The bottleneck is
**diagnosis**. People ask about the part of a topic they already half know,
because that is the part they have words for, and never ask about the part
they are missing, because they do not know it exists. A tutor who answers the
question as asked reinforces exactly this. So this skill does not start by
explaining. It starts by finding the edge: the boundary where the user's
correct answers stop.

Everything below is a conversation protocol, not a document to produce. Run it
across turns, and let the user pull it off course whenever they want — they
are the one learning.

## 1. Pick the target

If `/learn` came with an argument, that is the topic. If it came bare, propose
candidates rather than asking an open "what do you want to learn?" — the whole
premise is that the user cannot fully see their own gaps. Good candidates come
from the current session: things they delegated to you without reading the
result, terms they used in a way that almost fits, a fix they accepted with
"if you say so", an error they routed around instead of understanding. Offer
two or three, each with one line on why you picked it, and let them choose or
override.

Keep the target narrow enough to make progress in one sitting. "Rust" is a
curriculum; "why the borrow checker rejects this function" is a session.

## 2. Probe the edge

Ask calibration questions — a few at a time, not a wall of them — starting
from fundamentals and moving up until the answers stop being right. The point
is placement, not examination, and the questions should be built for that:

- Prefer questions that require **prediction or explanation** ("what does this
  print", "why would this deadlock") over recognition ("have you heard of X").
  Recognition overstates knowledge; nearly everyone has heard of X.
- No gotchas or trivia. A trick question locates nothing — missing it does not
  mean the fundamentals are missing.
- Treat hedged answers as data. "I'd guess it copies the value" from someone
  who is right for the wrong reason is a shaky area, not a solid one — probe
  one level deeper before moving on.
- Stop probing a thread after two consecutive misses. You have found the edge
  on that thread; grinding past it just makes the user feel bad, and this
  protocol only works if being wrong stays cheap.

Say up front that wrong answers are the productive outcome here — the probe
exists to find them. A user performing knowledge at you defeats the diagnosis.

## 3. Draw the map

Before teaching anything, show the user what the probe found, in four short
groups:

- **Solid** — answered correctly with correct reasoning. Name it and leave it
  alone; re-teaching it is how sessions turn into lectures.
- **Shaky** — right answer, wrong or missing reasoning; or hedged and
  half-right. Usually the highest-leverage group.
- **Missing** — the misses, stated plainly and without cushioning.
- **Didn't come up** — the unknown unknowns: one or two adjacent concepts the
  user never mentioned but that anyone working in this area eventually needs.
  This group is the skill's whole reason to exist; never skip it.

Then ask the user to correct the map. They know things the probe cannot see —
which "solid" was a lucky guess, which "missing" they simply misread. The map
is a shared artifact, not a verdict.

## 4. Teach one gap at a time

Order by leverage: prerequisites before the things built on them, and shaky
foundations before missing advanced material — a wobbly fundamental corrupts
everything downstream of it. For each gap:

1. **Intuition first** — what problem this thing exists to solve, in one or
   two sentences, before any mechanism.
2. **Mechanism** — how it actually works, at a depth matched to the edge you
   found, not to how much you know about it.
3. **Their example, not a toy** — ground it in the user's own code, project,
   or domain whenever one is available. `foo`/`bar` examples are forgotten by
   the next paragraph; the function they shipped last week is not.
4. **Retrieval, before moving on** — ask them to explain it back, predict an
   output, or apply it to something of theirs. "Makes sense" is not retrieval;
   recognition feels identical to understanding from the inside, and retrieval
   is the only cheap way to tell them apart. If the retrieval fails, that is
   the protocol working — re-explain from a different angle and try a
   different retrieval, don't repeat the same one.

One gap per exchange. The urge to dump the full tutorial after the first
question is strong and always wrong: a lecture transfers text, not knowledge,
and it destroys the diagnostic signal that makes the next question good.

## 5. Close the loop

End the session deliberately rather than letting it trail off:

- Restate the map's delta — what moved from missing or shaky toward solid
  today, and what is still open.
- Leave **three to five recall questions** targeting exactly what was taught.
  Not for answering now — they are the warm-up for next time, because
  retrieval a day later is worth more than retrieval a minute later.
- Then offer to distill (step 6). Do it at close, not "later": chat sessions
  are fragile — messages get lost, windows end — and the session's diagnostic
  detail is the raw material, so condense it while it still exists.

## 6. Distill into the user's own systems

A session leaves behind material worth more than a transcript, because it is
*calibrated*: it records not just what is true about the topic but what this
user specifically got wrong, which metaphor finally made a thing click, and
which phrasings were theirs. Offer to condense that into the formats the
user's own systems reuse — ask which they want rather than dumping all of
them:

- **Resumable topic note** — for a later `/learn` of the same topic: the map,
  the open gaps, the recall questions. On a later invocation, find this note
  first and open with its recall questions — how those go is the new probe.
- **PKM / TIL note** — the mechanisms in their corrected form, the handles
  and metaphors that landed, a *misconceptions I had* section stated as
  plainly as the map was, and source pointers. Where the user produced a good
  final phrasing of an idea, keep their wording — their words are their
  retrieval hooks, not yours.
- **Flashcards** — write fronts retrieval-shaped: predict, apply,
  explain-why. Never recognition — "What is X?" is a weak card; "Why does X
  go in this column when it seems to belong in that one?" is a strong one.
  Prioritize cards from the session's **documented errors**: a card
  re-testing a mistake the user actually made outranks ten generic facts,
  because it re-probes the exact edge the diagnosis found — and it is the one
  card no pre-made deck can contain. Emit a format their tool imports (TSV
  for Anki) alongside the readable version.
- **Blog / essay seed** — the session's own arc is the outline: what I
  thought I knew, the question that broke it, the mechanism, the payoff.
  Sessions where the learner was wrong in an *interesting* way make the best
  posts; offer this one only when they were.

Whatever the format: suggest a location or hand over a file, let the user
pick where it lives, and never commit anything to version control without
being asked.

## Ways this goes wrong

- **Lecturing.** The user asks one question in step 2 and gets a full essay.
  If a reply is mostly your prose and contains no question back, the protocol
  has already collapsed into a tutorial they could have gotten by just asking.
- **Flattering the map.** Rounding "shaky" up to "solid" because the user
  seems confident, or padding the missing list with softeners. A wrong map
  wastes the whole session downstream; kindness lives in tone, not in the data.
- **Quizzing as gatekeeping.** The probe finds the edge; it does not decide
  whether the user "deserves" the explanation. If they say "just tell me",
  tell them — then return to retrieval afterward instead of abandoning it.
- **Teaching to your own depth.** The edge you found is the spec. An expert
  answer to a beginner gap overshoots exactly like a beginner answer to an
  expert gap undershoots.
- **A session with no retrieval.** If the user never produced anything —
  never explained back, predicted, or applied — nothing was verified to have
  landed, however good the explanations felt to both sides.
