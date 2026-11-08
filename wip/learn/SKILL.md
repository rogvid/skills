---
name: learn
description: Manually invoked — use when the user runs /learn, or explicitly asks to learn a topic properly, find the gaps in their understanding, be quizzed on something, or be taught rather than just handed an answer. Not for ordinary questions where the user just wants the answer — answering directly is the right move there. Diagnoses the edge of what the user knows, sorts each gap into a misconception, a missing mental model, or missing information, secures fundamentals before building on them, teaches with diagrams, runnable checks, and verified sources, and distills the session into reusable notes, flashcards, and blog seeds built from what the user actually got wrong.
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
correct answers stop — and then works out *what kind* of gap sits there,
because different gaps need different teaching.

Everything below is a conversation protocol, not a document to produce. Run it
across turns, and let the user pull it off course whenever they want — they
are the one learning. Their questions mid-session are often the best
diagnosis you will get: a learner asking "where is that stored, then?" has
just pointed at their own gap.

## 1. Pick the target

If `/learn` came with an argument, that is the topic. If it came bare, propose
candidates rather than asking an open "what do you want to learn?" — the whole
premise is that the user cannot fully see their own gaps. Good candidates come
from the current session: things they delegated to you without reading the
result, terms they used in a way that almost fits, a fix they accepted with
"if you say so", an error they routed around instead of understanding. Offer
two or three, each with one line on why you picked it, and let them choose or
override. If they want something outside their own work, prefer mature,
well-documented topics they use daily — those have the most hidden gaps and
the best sources.

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
When the topic is executable, also say that predictions will be settled by
running them; it turns the probe into an experiment rather than a test.

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

Tag every shaky and missing item with **what kind of gap** it is, because each
kind needs different teaching (step 5):

- **Missing information** — they simply don't know the fact, and nothing wrong
  sits in its place. Cheapest to fix.
- **Missing or weak model** — they have pieces but no structure connecting
  them. The signature: answers that are right in isolation but fail when
  composed or used to predict, and errors that keep coming back in new forms.
- **Misconception** — they confidently believe something false. The signature:
  a confident, specific, wrong answer ("git stores diffs"). Telling them the
  truth is not enough; the old belief survives right next to the new one.

Then ask the user to correct the map. They know things the probe cannot see —
which "solid" was a lucky guess, which "missing" they simply misread, which
wording you took too literally. The map is a shared artifact, not a verdict.

## 4. Fundamentals first

Order by leverage: prerequisites before the things built on them, and shaky
foundations before missing advanced material — a wobbly fundamental corrupts
everything downstream of it.

When an answer about advanced material fails, **look one layer down before
re-teaching the advanced thing.** Several wrong answers about the same
advanced topic usually share one missing fundamental: in one git session,
three wrong answers about rebase all traced back to not knowing that a
commit's parent ID lives inside the commit. An error that recurs in new forms
is a model gap, not a string of separate fact gaps — go down a layer and fix
the model. Do not move up while a fundamental is shaky; confirm it holds with
a retrieval question that cannot be answered without it.

## 5. Teach one gap at a time

For each gap:

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
   the protocol working — re-explain **from a different angle**, and use a
   **different retrieval shape** (prediction, sorting, fill-in-the-diagram,
   explain-back), not the same question again.

Match the teaching to the kind of gap:

- **Missing information:** say it plainly, connect it to something they
  already hold, cite where it comes from. Don't dress a fact up as a lesson.
- **Missing model:** give them a picture — a diagram, an analogy, a physical
  handle ("a branch is a 41-byte file: room for one ID") — then make them use
  the model to predict something they haven't seen.
- **Misconception:** make the wrong belief predict something concrete, show
  the prediction fail with evidence, then install the replacement and explain
  why the wrong version felt right (where "git stores diffs" comes from).
  Re-test it later in the session; misconceptions come back.

Four habits run through all of it:

- **Draw it.** Anything with structure — pointers, layers, flows, before and
  after — gets a diagram (Mermaid or ASCII in chat). Many learners think in
  pictures, and a recurring error is often a missing picture.
- **Check it by running it.** When the topic is executable, settle predictions
  — the user's and your own — by running real commands in a scratch space and
  showing the output. That includes your own scripts: output that surprises
  you (a count of zero, an impossible value) is a bug to fix before you rely
  on it, not a result.
- **Ground it in sources.** Back each load-bearing claim with an authoritative
  source, primary first: official documentation at the version in use, the
  original text, the standard. Verify against the source text where you can
  (a blocked website often has its source on a reachable mirror or
  repository), and label anything you could not verify. When a source
  contradicts something you said earlier, correct it out loud.
- **Watch your own wording.** A misconception that appears right after one of
  your explanations may have been caused by it. Own it, then rephrase the
  explanation; don't treat it as the user's error.

One gap per exchange. The urge to dump the full tutorial after the first
question is strong and always wrong: a lecture transfers text, not knowledge,
and it destroys the diagnostic signal that makes the next question good.

## 6. Close the loop

End the session deliberately rather than letting it trail off — and end it
when answers start getting vaguer, not only when the map is finished; a tired
learner's answers stop being diagnostic.

- Restate the map's delta — what moved from missing or shaky toward solid
  today, and what is still open.
- Leave **three to five recall questions** targeting exactly what was taught.
  Not for answering now — they are the warm-up for next time, because
  retrieval a day later is worth more than retrieval a minute later.
- Then offer to distill (step 7). Do it at close, not "later": chat sessions
  are fragile — messages get lost, windows end — and the session's diagnostic
  detail is the raw material, so condense it while it still exists.

## 7. Distill into the user's own systems

A session leaves behind material worth more than a transcript, because it is
*calibrated*: it records not just what is true about the topic but what this
user specifically got wrong, what kind of gap each error was, which picture
finally made a thing click, and which phrasings were theirs. Offer to condense
that into the formats the user's own systems reuse — ask which they want
rather than dumping all of them:

- **Resumable topic note** — for a later `/learn` of the same topic: the map,
  the open gaps, the recall questions. On a later invocation, find this note
  first and open with its recall questions — how those go is the new probe.
- **PKM / TIL note** — the mechanisms in their corrected form, with the
  diagrams that landed (Mermaid renders in most note tools); a table of
  *what I believed / kind of gap / what's true*, stated as plainly as the map
  was; the handles and metaphors; try-it-yourself commands for executable
  topics; and a sources table saying which claims were verified against which
  source. Where the user produced a good final phrasing of an idea, keep their
  wording — their words are their retrieval hooks, not yours.
- **Flashcards** — write fronts retrieval-shaped: predict, apply,
  explain-why. Never recognition — "What is X?" is a weak card; "Why does X
  go in this column when it seems to belong in that one?" is a strong one.
  Prioritize cards from the session's **documented errors**: a card
  re-testing a mistake the user actually made outranks ten generic facts,
  because it re-probes the exact edge the diagnosis found — and it is the one
  card no pre-made deck can contain. Tag cards by gap kind. Emit a format
  their tool imports (TSV for Anki) alongside the readable version.
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
- **Building on a shaky fundamental.** Re-teaching the advanced topic a third
  time when the real gap is one layer down. If the same kind of error keeps
  coming back, stop and look underneath it.
- **Correcting a misconception by assertion.** Stating the right answer and
  moving on. The wrong belief was evidence-shaped; it needs evidence to
  dislodge it, or it resurfaces next session.
- **Unverified authority.** Presenting facts from memory as settled. Check
  what you can, cite what you checked, and say what you didn't.
- **A session with no retrieval.** If the user never produced anything —
  never explained back, predicted, or applied — nothing was verified to have
  landed, however good the explanations felt to both sides.
