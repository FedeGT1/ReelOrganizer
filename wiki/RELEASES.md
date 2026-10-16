---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-16"
tags:
  - kind/meta
  - topic/deployment
  - status/draft
connected files: ["components/reel-organizer/README", "CHANGELOG"]
---

# Releases

What is deployed where, with dates. **Unlike the CHANGELOG, this cannot be derived from
`git log`** — only the person who actually ran `docker build`/`docker run`/`docker
restart` on the VM knows what's live and when it went live. This page is `status/draft`
until that's confirmed.

## Known environments

| Environment | Host | Notes |
|---|---|---|
| Production (self-hosted) | A `sslip.io` hostname on the operator's own VPS (EOL Ubuntu 20.10, Apache reverse-proxying two other sites alongside this one) | Per `README.md` / `docs/deployment-apache-tls.md`. Exact hostname and current running commit not recorded here. |

## Deploy history

| Date | Environment | Commit / version | Who / how |
|---|---|---|---|
| 2026-10-16 | Production | `dev` @ `048875c` (C_01 group-reels-by-place) | fedegt1, push + Docker rebuild and container recreate (confirmed by the owner) |

Fill this in the next time a deploy happens (or retroactively, from whoever remembers),
using the verification steps in the root `README.md`'s "Updating after a code change"
section (`docker images` + `docker inspect -f '{{.Image}}'`) to pin down which commit is
actually live right now, rather than guessing from the latest `dev` commit.

## See also

- [[CHANGELOG]]
- [[components/reel-organizer/README]]
