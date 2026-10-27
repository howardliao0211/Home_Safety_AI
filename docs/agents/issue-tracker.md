# Issue tracker: Local Markdown

Issues and specs live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`.
- The spec is `.scratch/<feature-slug>/spec.md`.
- Each implementation ticket has its own file:
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Record triage state as a `Status:` line near the top of each issue.
  Use the role strings in `triage-labels.md`.
- Append comments and conversation history under `## Comments`.

## Publish to the issue tracker

Create the appropriate spec or issue file under
`.scratch/<feature-slug>/`, creating directories as needed.

## Fetch the relevant ticket

Read the referenced file. Resolve a ticket number within its feature's
`issues/` directory; ask for the feature when the number is ambiguous.

## Wayfinding operations

Used by `/wayfinder`.

- Map: `.scratch/<effort>/map.md`, containing Notes,
  Decisions-so-far, and Fog.
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`.
  Record its question in the body and its type in a `Type:` line:
  `research`, `prototype`, `grilling`, or `task`.
- Blocking: record `Blocked by: NN, NN` near the top.
  A ticket is unblocked when every listed ticket is resolved.
- Frontier: select open, unblocked, unclaimed tickets in number order.
- Claim: set `Status: claimed` and save before starting work.
- Resolve: append the answer under `## Answer`, set `Status: resolved`,
  and append a gist plus link to the map's Decisions-so-far section.

For wayfinding tickets, `claimed` and `resolved` are workflow statuses
in addition to the triage roles.
