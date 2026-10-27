# Domain docs

## Layout

This repo uses a single-context layout:

- `CONTEXT.md` at the repo root: domain terms and their definitions.
- `docs/adr/`: architecture decision records.

## Before exploring the codebase

Read the root `CONTEXT.md` and ADRs relevant to the area of work.

If these files do not exist, proceed silently. Domain modeling creates
them when terms or decisions are resolved.

## Use the glossary's vocabulary

Use domain terms as defined in `CONTEXT.md` in issue titles, proposals,
hypotheses, and test names.

When a needed concept is absent, reconsider the terminology or note
the gap for domain modeling.

## Flag ADR conflicts

Explicitly identify proposals that contradict an existing ADR.
Name the ADR and explain why its decision should be reconsidered.
