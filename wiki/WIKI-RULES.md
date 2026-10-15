---
taxonomy: _meta/tags.md
required_frontmatter: [authors, created_at, updated_at, tags, connected files]
branch_of_truth: dev
absent_ok: ["bug-reports"]
skip: []
---

# Wiki rules — ReelOrganizer

The conventions for this wiki. **This file outranks the skill that generated it.**
Where they disagree, this wins — it records decisions made for this project.

The frontmatter above is also read by `check_wiki.py`; keep it accurate.

## The one rule everything else serves

**Code on `dev` is the source of truth.** `main` exists and, as of 2026-10-15, trails `dev` by
one commit; active work lands on `dev` — do not treat `main` as the branch of truth. Where this wiki and the code disagree, the wiki is wrong — fix
the wiki. Verify a claim before writing it.

Authority order when sources conflict:

1. Code on `dev`
2. The repo's own `README.md` (the single source for env vars, Docker commands, and
   operational runbooks — this wiki links to it, never copies its tables)
3. This wiki
4. Anything older — `docs/japan-reel-organizer-specifiche.md` (the original pre-build
   brief; superseded on most points, see `_meta/doc-map.md`), `.superpowers/sdd/*`
   (historical implementation logs)

## One component, not several

ReelOrganizer is a single FastAPI process — there is no service boundary to document
per-service. `components/reel-organizer/README.md` is the only component page, and it
covers the whole `app/` tree. Don't create a second component folder for `app/ai`,
`app/ingest`, etc. — those are internal modules, documented as sections of that one page
or as `concepts/`/`explainers/`, not components.

## Frontmatter

Every note carries all five properties. No exceptions; `check_wiki.py` enforces it.

| Property | Meaning |
|---|---|
| `authors` | **Who wrote the note**, not who requested the work. A requester belongs in the note's own table |
| `created_at` | ISO `YYYY-MM-DD`. Never changes |
| `updated_at` | ISO `YYYY-MM-DD`. **Bump on every edit**, including edits to other people's notes |
| `tags` | From `_meta/tags.md` only. Three to six is healthy — advisory, not enforced |
| `connected files` | Wikilinks to related notes. Also bump the *other* note if the relationship is real |

## What `status/` asserts

| Tag | Means |
|---|---|
| `status/authoritative` | **Verified against code on `dev`** by whoever last set it |
| `status/draft` | Written but not verified — or verified against a branch that is not the truth |
| `status/superseded` | Kept for the record. Do not act on it |

If you could not read the code, the note is `status/draft`. Say what you could not
verify rather than guessing a value; a blank table with a note beats an invented one.

## Naming

One pattern per folder. Pick and keep:

| Folder | Pattern | Example |
|---|---|---|
| `explainers/` | `NN-kebab-title.md`, two-digit prefix = reading order | `02-the-ai-categorization-flow.md` |
| `concepts/` | `kebab-term.md`, the term itself, singular | `hub-satellite-location.md` |
| `components/<name>/` | `README.md`, folder named exactly as this skill's convention (one folder: `reel-organizer`) | `reel-organizer/README.md` |
| `change-requests/business-requests/` | `kebab-slug.md`, undated — `created_at` carries the date | `tiktok-import.md` |
| `change-requests/specs/` | `spec-<same-slug>.md` | `spec-tiktok-import.md` |
| `bug-reports/` | `kebab-slug.md`, undated — `created_at` carries the date | *(folder exists, empty as of 2026-10-09)* |

Do not renumber explainers to insert one in the middle — it breaks every inbound link.
Append instead.

## Which register fires when

| Trigger | CHANGELOG | KANBAN | RELEASES | Notes |
|---|---|---|---|---|
| Code shipped | **Yes** — a row with code evidence | Move the card | No | Also update the notes the change makes wrong |
| Documenting existing behaviour | **No** — nothing was built | Only if it reveals a defect | No | This is the common mistake |
| Change request arrives | No | Yes — a card | No | Write the request; the spec follows only if work is agreed |
| Bug reported | No — nothing shipped | Yes — a card | No | A bug contradicts a *stated* expectation; without one it is a change request |
| Bug fixed | **Yes** — a row with code evidence | Move the card | No | Link the bug report from the row |
| Deployed to an environment | No | Move the card | **Yes** — at the moment of deployment | Merging to `dev` is not a deployment |
| Decided against something | No | Move to ARCHIVED **with the reason** | No | Rows are never deleted |

## Content rules

- **Curate, do not copy.** What the system *is* belongs here; how it got there stays in
  the repo — `.superpowers/sdd/*` implementation logs, the original
  `docs/japan-reel-organizer-specifiche.md` brief. Copying makes this wiki the next thing
  to go stale.
- **No code blocks in notes.** Name things inline in backticks. Diagrams are Mermaid.
- **Cite code as repo-relative paths in backticks** — never as a wikilink. Obsidian
  cannot resolve outside the vault, and the failure is silent.
- **Backlinks are bidirectional.** Adding `[[x]]` to a page is half the job.
- **Business terms, acronyms and external system names go in `glossary.md`** with their
  definitions, not re-explained per note. It is a flat table — term, definition, where it
  appears — in Italian where that's the project's own language (e.g. "hub", "gita"). A
  term with its own `concepts/` note is *linked* from the glossary, not duplicated into it.
- **A closed bug report stays in `bug-reports/`.** Set its status — including `not a bug`
  — rather than deleting the file; the reason it was closed is the valuable part.
- **RELEASES.md deploy dates are operator knowledge, not something derivable from the
  repo.** Only the person who ran `docker run`/`docker restart` on the VM knows what is
  live and when it went live — verify with them before writing a row, don't infer it
  from a commit date.

## Before you finish

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/writing-project-wikis/scripts/check_wiki.py" wiki --repo-root .
```

Run from the repo root. Clean means the mechanical rules hold. It says nothing about
whether the content is true — that is what verifying against `dev` is for.
