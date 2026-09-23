---
name: goal
description: What this repo is for and how success is measured. Read before planning any work here.
---

# What this repo is for

Read this before planning work here.
It is the thing every change is judged against.

## The problem

Showing someone what a change does is still the fastest way to explain it.
A short video of the feature working answers "what did you build?" in a minute, where a diff or a paragraph takes ten.
Making that video by hand is slow, so it rarely happens.

An agent can make it: drive the app, caption each step, and hand back an mp4.
The first version of `demo-video` proved that works, but it cost too much.
A single demo could use most of a session's tokens, the takes ran in real time, and the finished video could sit on a frozen screen for a minute while the app worked.

## What `demo-video` is for

**A person asks an agent for a demo, and gets a short, polished video back quickly and cheaply.**

The person is in the loop: they say what to show, look at the result, and ask for changes.
The input can be anything that describes a feature - a user story, a pull request description, a ticket, or a sentence in chat.
The skill turns that into a storyboard and a video that shows each point working.

It is not an automated verification pipeline, a CI gate, or a grader.
That was the first version's aim, and it is dropped.

## Success

Measured on a real demo of a real app, from the request to a video the person accepts:

- **Tokens:** the demo work fits comfortably in a session, well under 100k tokens of context at the end.
- **Speed:** a take (record plus render) of a one-minute demo finishes in about a minute of wall-clock time, not several.
- **Watchability:** no stretch of the video sits on an unchanging screen for more than about three seconds, and a viewer with no context can follow it from the captions.
- **Iterations:** the person asks for few changes, and each change is a small edit and a re-run.

## Rules that follow from this

- **The recorder does the polish, not the storyboard.** Anything every demo needs - dead-time removal, cursor handling, caption timing, framing - is built into the recorder, so a storyboard is short and an agent never writes it by hand.
- **Every output an agent reads is small.** Summaries are a few lines, review happens on one contact sheet, and failures print what to fix.
- **Prefer less.** Every verb, option and reference page costs tokens on every use. Remove what the default path does not need.
- **Secrets: the skill has no masking, no scrubbing and no redaction.** Record fixtures and example data only. `skills/demo-video/SKILL.md` states it.
