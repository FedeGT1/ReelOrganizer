---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-15"
tags:
  - kind/change-request
  - topic/ingest
  - vendor/yt-dlp
  - component/reel-organizer
  - status/draft
connected files: ["components/reel-organizer/README", "_meta/doc-map"]
---

# Import from TikTok, not just Instagram

| | |
|---|---|
| Requested by | The operator (fedegt1), as a backlog idea in `docs/todo-next-step.md` (since deleted in `5f16827`; this page is now the only record) |
| Requested on | Recorded there no earlier than 2026-10-09 (the file's `is_instagram_link` reference matches current code) |
| Status | backlog — not started, not scheduled |
| Spec | none yet |
| Branches | none yet |

## The request

Today pasting a link only works for Instagram — the auto-import flow (download +
transcribe + AI-categorize) should accept TikTok links too, with the same flow.

## Is it actually a change request?

Checked against `dev`: it is not already built. `app/routers/instagram_import.py`'s
`_is_instagram_link` only matches the `instagram.com`/`www.instagram.com` hostnames —
pasting a TikTok link today is rejected by that check before it ever reaches the
download step. Not in the original agreed scope either — the founding brief
(`docs/japan-reel-organizer-specifiche.md`) only ever named Instagram. Genuinely open.

## Impact

- `app/ingest/instagram.py` — `yt-dlp` (the actual downloader) already supports TikTok
  natively, so the fetch/transcribe mechanics likely need few changes.
- `app/routers/instagram_import.py` — `_is_instagram_link` needs to accept TikTok
  hostnames too (or be replaced with a broader check).
- Naming — `app/ingest/instagram.py`'s module name, and the "Cookie Instagram" tool at
  `/instagram-cookies`, are Instagram-specific; whether to generalize them is an open
  question below, not a decision made yet.

## Open questions

- Does TikTok require an authenticated-cookie workaround the way Instagram does from
  datacenter IPs (see `app/ingest/instagram.py::cookies_path`), or does anonymous
  `yt-dlp` access work fine?
- Is TikTok's caption metadata shape compatible with how `fetch()` currently reads
  `info.get("description")`?
- Worth renaming `app/ingest/instagram.py` / generalizing `_is_instagram_link` now, or
  defer the rename until a second platform is actually wired up?
