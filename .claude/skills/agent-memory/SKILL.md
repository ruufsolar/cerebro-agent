---
name: agent-memory
description: >-
  Ruuf's agents remember things about the code they own that the code does not
  say. Use before editing a file that an agent owns, and after learning
  something non-obvious about one of their domains.
---

# Agent memory

Ruuf's agents each own paths in a repository and know things about them that are
not written down anywhere else: what ops asked for, what broke last time, what a
number means, which of two similar-looking functions is the one that matters.
That knowledge is one store, read the same way from Slack and from here.

## Before you edit

Call `agents_for_paths` with the paths you are about to touch.

- If it names an agent **that has a subagent file**, delegate the task to it.
  It is briefed on that code and you are not.
- If it names an agent with no subagent file, call `agent_brief` for it and read
  that before you read the code.
- If it names nobody, carry on.

## When you are done

Call `remember` once per non-obvious learning, on the agent that owns the code:

- `kind: procedure` for how to do something, `kind: fact` for how something
  behaves.
- One thing per call, under 1500 characters.
- **Never** a client's name, RUT, phone or email. Every Ruufian reads these.

A learning lands in short-term memory and is consolidated overnight. If nothing
surprised you, do not write anything — an agent's memory is worth what its worst
row is worth.

## Asking it questions

`recall` searches an agent's memory and Ruuf's shared knowledge together. Use it
when the question is about past behaviour rather than about code: why a
threshold is what it is, what happened the last time somebody changed this, what
Ops actually mean by a word. Nothing below a similarity floor comes back, so an
empty answer means the store does not know — not that you asked badly.

## Tools

`mcp__ruuf-agents__agents_for_paths`, `mcp__ruuf-agents__agent_brief`,
`mcp__ruuf-agents__recall`, `mcp__ruuf-agents__remember`,
`mcp__ruuf-agents__list_agents`.

None of them runs a model on Ruuf's account beyond a single embedding call, so
they cost effectively nothing and the reasoning stays on your own subscription.
