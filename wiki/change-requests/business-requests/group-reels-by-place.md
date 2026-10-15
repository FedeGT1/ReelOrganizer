---
authors:
  - "fedegt1"
created_at: "2026-10-16"
updated_at: "2026-10-16"
tags:
  - kind/change-request
  - status/draft
connected files: ["components/reel-organizer/README", "concepts/hub-satellite-location"]
---

# Group reels by place in the reel list

| | |
|---|---|
| Requested by | The operator (fedegt1), directly in chat |
| Requested on | 2026-10-16 |
| Status | under analysis — in Delivery brainstorm as [[C_01-group-reels-by-place]] |
| Spec | [[C_01-group-reels-by-place]] (draft) |
| Branches | none yet |

## The request

Today, adding several reels about the same place merges them under a single place
(no duplicate places are created — this was the earlier request and works as intended).
The reel list, however, is ordered by insertion time, so two reels of the same place
can be very far apart in the list. The operator wants the list grouped, so reels of
the same place appear together.

## Is it actually a change request?

To be verified against `dev` during the brainstorm: the merge-by-place behaviour is
confirmed by the operator as working; grouping in the list is not said to exist and the
operator describes the list as insertion-ordered. Genuinely open until the brainstorm
re-checks the list view and its query.

## Impact

*(to be filled by the brainstorm — expected: the reel list query/ordering and its
template; possibly the place-merge logic if grouping needs a stable key.)*

## Open questions

- Visible group headers per place, or just adjacent ordering?
- Order between groups (by place name, by most recent reel, by first added)?
- Order of reels inside a group?
- Where do reels with no place go?
- Does grouping apply to every list/filter view, or only the default one?
