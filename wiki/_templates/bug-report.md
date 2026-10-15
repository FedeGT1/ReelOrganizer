---
authors:
  - "{{author}}"
created_at: "{{date:YYYY-MM-DD}}"
updated_at: "{{date:YYYY-MM-DD}}"
tags:
  - kind/bug-report
  - status/draft
connected files: []
---

# {{title}}

| | |
|---|---|
| Reported by | The person, and how — meeting, ticket, mail |
| Reported on | |
| Environment | which deployed environment, and the version or commit running there |
| Severity | blocker / major / minor / cosmetic |
| Status | reported / reproduced / **not a bug** / fixed / won't fix |
| Fixed in | branch, then CHANGELOG row once delivered |

## Observed vs expected

What happens, and what should happen instead. State where the expectation comes from —
the agreed requirements, a wiki page, the component's documented interface. A bug is a
gap against a stated expectation; without one this is a [[change-request]], not a bug.

## Reproduction

Smallest sequence that shows it. If you could not reproduce it, say so and say what you
tried — that is the finding.

## Root cause

Only once verified in the code, cited as repo-relative paths in backticks. Until then
leave this blank rather than guessing; a guessed cause sends the next reader to the
wrong file.

## Open questions
