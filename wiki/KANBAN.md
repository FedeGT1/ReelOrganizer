---
authors:
  - "fedegt1"
created_at: "2026-10-09"
updated_at: "2026-10-16"
tags:
  - kind/meta
  - status/authoritative
connected files: ["change-requests/business-requests/tiktok-import", "CHANGELOG", "governance/INDEX"]
---

> **Governance** — posture: delivery · focus: Delivery C_01 group-reels-by-place: C_01_01 done, prossimo task C_01_02 · design: [[current-system-design]]

# Kanban

Seeded 2026-10-09 from `docs/todo-next-step.md` (the only open backlog item in the repo;
the file was removed in `5f16827`, so [[tiktok-import]] is now the only record) and the
git history on `dev`. Nothing else open was found in this pass.

## TODO

- [ ] C_01_02 — Raggruppamento e ordinamento lato server in _reel_list_context | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_01
- [ ] C_01_03 — Template a gruppi con intestazione per luogo | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_02
- [ ] C_01_04 — Paginazione per gruppi in reel-list.js | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_03
- [ ] C_01_05 — Stile dell intestazione di gruppo | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_03
- [ ] C_01_06 — Test dei consumatori della lista reel | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_03
- [ ] C_01_07 — Verifica dal vivo e conferma dell owner | unit: C_01 | status: planned | branch: — | merged: no | depends_on: C_01_04, C_01_05, C_01_06
- [[group-reels-by-place]] — group reels by place in the reel list. Parked until the Bootstrap closes; becomes the first Delivery unit.
- [[tiktok-import]] — import from TikTok in addition to Instagram. Not started.

## WIP

*(none)*

## TEST

*(none)*

## DONE

- [x] C_01_01 — Refresh baseline: consumatori della lista reel nel design | unit: C_01 | status: done | branch: governance/C_01_01-refresh-baseline-reel-list | merged: yes | depends_on: —
- [x] bootstrap-brownfield-04 — Inizializza governance/adrs/README.md | unit: BOOT | status: done | branch: — | merged: n/a | depends_on: bootstrap-brownfield-01, bootstrap-brownfield-02
- [x] bootstrap-brownfield-03 — Aggiorna CLAUDE.md con stack, comandi, convenzioni, guardrail | unit: BOOT | status: done | branch: — | merged: n/a | depends_on: bootstrap-brownfield-01, bootstrap-brownfield-02
- [x] bootstrap-brownfield-02 — Formalizza ADR-002: lista completa dal server, paginazione solo client | unit: BOOT | status: done | branch: — | merged: n/a | depends_on: —
- [x] bootstrap-brownfield-01 — Formalizza ADR-001: un luogo, una Location | unit: BOOT | status: done | branch: — | merged: n/a | depends_on: —
- Multiuser retrofit (accounts, per-user scoping, additive migration) — see
  [[03-the-multiuser-retrofit]] and the `CHANGELOG` row dated 2026-10-09.

## ARCHIVED

*(none — nothing found in this pass that was explicitly decided against)*
