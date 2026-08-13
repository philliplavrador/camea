# parked/ — interviewed enough to keep, not enough to build

A parked plan is one nobody should build yet, and the reason is never "it is low
priority" — that is what the bottom of [queued/](../queued/) is for. A plan is parked
when **building it would require inventing answers the author has not given**.

The record is worth keeping anyway. The questions a stub already asks are the most
valuable thing in it: they exist so the eventual `/plan` interview starts informed
instead of from zero. Deleting the file throws that away; leaving it in `queued/`
invites an unattended `/build` to answer those questions by guessing.

## Why a directory and not a `status:` value

**A plan's state is its directory** ([plans/README.md](../README.md)). `/build`
enumerates `workflow/plans/queued/` and `workflow/plans/active/`
([build.md](../../../.claude/commands/build.md)), so a file sitting here is out of the run
*by construction*. A `status: parked` string on a file still in `queued/` would be a
comment — something every reader has to notice and honour — rather than a guarantee the
machine enforces.

`done/` would be a lie in both directions: a parked plan is not shipped and it is not
abandoned. It is a conversation that has not happened yet.

## How a plan leaves

**By being interviewed back into `queued/`** — `/plan <NNN>` asks the questions, records
the answers, and the file moves to `queued/` with `status: queued`. That is the only exit.
A parked plan is never built from where it sits.

If the idea is dropped instead, it follows the normal rule: it moves to `done/` with
`status: abandoned` and a line saying why. Nothing is deleted.

## What the tooling already knows

- [scripts/claim-number.js](../../../scripts/claim-number.js) scans this directory when it
  hands out the next plan number, so a parked number is spent and can never be re-issued.
- `/build all` skips it, because it enumerates `queued/` and `active/` and nothing else.
