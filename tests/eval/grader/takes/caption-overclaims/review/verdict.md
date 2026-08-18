# Two derivations of where each clause is

0 disagreement · 1 cannot tell · 0 no reading · 0 not demonstrated · 1 agreement

One derivation is the `ac=` tags the storyboard author typed. The other is a reader who was given the clause text and the frames and none of the rest — not the storyboard, not the tags, not this table. Where they disagree, the disagreement is the finding, and it is printed first.

**Agreement is a cross-check, not a verification. Two readers can share a bias, and a plausible-looking screen can fool both — and here they are not even fully independent: the caption the storyboard author wrote is burned into every frame both of them read. The reader is not asked to compare the screen with that caption, though. It is handed the ticket's clause text, so a caption overclaiming against the clause is something it can and does disbelieve — measured twice on a take built to defeat it, which is a measurement and not a guarantee. This catches a clause claimed before its evidence arrives and never arriving, a clause whose evidence never arrives at all, a tagged beat showing an error page, a clause the demo never reaches, and — twice measured — a caption asserting what the screen was never shown doing. Wrong-beat tagging has two directions and only one of them is caught: a reading before the first claimed beat agrees, so a clause visible early and gone by the beats that claimed it reads as agreement here and reaches nobody. Tagged too early surfaces; tagged too late does not. What it cannot catch is one level up: a declared clause text that is itself a misreading of the ticket. If the clauses above paraphrase the ticket wrongly and the demo satisfies the paraphrase, both derivations agree and the ticket is still unmet, because every input the reader has is downstream of that paraphrase. Comparing the declared clause with the ticket's own words is the only thing that closes it (issue #276).**

## The rule this page compares under

The reader is asked for the *first* frame in which a clause is visible, so its answer is a lower bound and not the only place the clause can be seen. A reading inside the closed span [first claimed beat, last claimed beat] agrees. A reading before the first claimed beat also agrees, and is marked `before the first claimed beat`: a lower bound earlier than the claim contradicts nothing the storyboard said, and it is what a clause already true when the demo opens has to look like. A reading after the last claimed beat disagrees, and that is the one direction that is evidence: it says the clause was in no frame up to and including the last beat that claimed it. Measured in beats, not seconds: the beat log and the video run on different clocks, so a tolerance in seconds would mean different things in different takes.

*Why a span:* A storyboard tags the beat where the caption goes up, and captions are written before the action they introduce, so the picture that evidences a clause arrives a beat or two after the beat that claims it. On a measured take, clauses claimed on beats [4, 6, 8, 12, 13] and [18, 20, 25, 26, 31] were correctly read at beats 10 and 23 — inside both spans, in neither claimed set.

*Why before the span is not after it:* A reading before the first claimed beat agrees, and says so on its row. The reader is asked for the first frame showing a clause, so its beat is a lower bound: below the claim it contradicts nothing, and it is what a clause already true when the demo opens has to look like — measured on the eval corpus, a queue listing every ticket's id, title and requester was true from the first painted frame, claimed on beats [2, 4, 5, 9], and read at beat 0. Above the claim the same lower bound is a proof against it: no earlier frame showed the clause, so none of the claimed beats did. Only that direction disagrees.

*What it gives up:* Agreement is cheaper the wider the claimed span. A clause claimed on beats 2 and 30 agrees with a reading anywhere between them, so agreement is weaker evidence the more beats a clause claims. Every row below prints its span for exactly this reason. A before-the-span agreement is weaker again: a lower bound says the clause was visible then, not that it was still visible on the beats that claimed it, so a clause shown early and gone by its claimed beats agrees here. Those rows print their position and how many beats early, so the two kinds of agreement can be told apart without reading the frames.

## cannot tell (1)

### AC-3 — Search matches the requester as well as the title — typing part of a name or an address finds that person's tickets.

- **cannot tell** — The reader could not tell from the frames; the storyboard claimed [7, 16]. This is one of the two cases a human is pulled in for.
  *Derived by:* demo-grade, comparing the reader's answer with the beats the storyboard claimed — the rule, including the span it uses when both derivations locate the clause, is stated in this document.
- **Reader:** cannot tell, confidence high — Only two queries are ever typed - 'invoice' (beat-04) and 'webhook' (beat-10) - and both are words from the ticket titles that remain, so matching on a requester's name or address is asserted only by the burned-in caption at beat-06 and is never demonstrated on screen; the later highlight of leo.fontaine@northwind.example at beat-14 merely rings the requester column of a title-matched row.
  *Derived by:* a reader given the clause text and the frame filenames, and neither the storyboard, the ac tags, the coverage table nor the diff.
- **Storyboard:** claimed beats [7, 12, 13, 16], span [7, 16]
  *Derived by:* coverage.claimed in timeline.json — the ac= tags the storyboard author typed, which are evidence of intent and nothing else.

## agreement (1)

### AC-1 — A search box above the queue narrows the list as you type, with no button to press.

- **agreement, inside the claimed span** — The reader located this clause at beat 4 (`beat-04.png`), inside the claimed span [2, 6].
  *Derived by:* demo-grade, comparing the reader's answer with the beats the storyboard claimed — the rule, including the span it uses when both derivations locate the clause, is stated in this document.
- **Reader:** seen, `beat-04.png` (beat 4), confidence high — The search field sitting above the ticket list now contains the typed text 'invoice' with the caret still in it, and the queue has narrowed from 7 rows to the single TQ-101 row (header reads 'Support queue (1)') without any search or submit button existing or being pressed.
  *Derived by:* a reader given the clause text and the frame filenames, and neither the storyboard, the ac tags, the coverage table nor the diff.
- **Storyboard:** claimed beats [2, 6], span [2, 6]
  *Derived by:* coverage.claimed in timeline.json — the ac= tags the storyboard author typed, which are evidence of intent and nothing else.
