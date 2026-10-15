---
authors:
  - "{{author}}"
created_at: "{{date:YYYY-MM-DD}}"
updated_at: "{{date:YYYY-MM-DD}}"
tags:
  - kind/change-request
  - status/draft
connected files: []
---

# {{title}}

| | |
|---|---|
| Requested by | The person, and how — meeting, ticket, mail |
| Requested on | |
| Status | proposed / under analysis / approved / in development / delivered / rejected / **already in scope** |
| Spec | `[[spec-...]]` once one exists |
| Branches | branch name per repo — often the only key grouping one change across repos |

## The request

In the requester's own terms. Business language, not implementation.

## Is it actually a change request?

**Check before writing anything else.** Two things disqualify it:

- **It is already in scope** — named in the agreed requirements. Then it is not a change
  request; set the status accordingly and record where it is specified.
- **It already works** — verify against the code. If it ships today, the useful output
  is *why the requester did not see it*, not a request.

Either way keep the file: it stops the same ask returning in six months.

## Impact

Which components, and which existing behaviour changes. "None" is a valid answer.

## Open questions
