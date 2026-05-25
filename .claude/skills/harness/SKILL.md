---
name: harness
description: Use for feature-sized or risky software work that should be planned, split into phases/steps, verified, and recorded before or during implementation.
---

# Harness Workflow

Use this skill when the user asks for `/harness`, "하네스", phase/step planning,
or any feature-sized change where planning and verification matter.

## Principles

- Keep `CLAUDE.md` short. It is always-on memory, not a long manual.
- Read only the files needed for the current decision.
- Treat completed phases as history. Create a new phase for each new feature or
  meaningful work stream.
- Do not edit unrelated files.
- Do not execute destructive commands without explicit human approval.

## Workflow

1. Inspect the current project structure.
2. Read `CLAUDE.md`.
3. Read only relevant docs from `docs/`.
4. Ask clarifying questions if requirements are ambiguous.
5. Create a phase under `phases/<phase-name>/`.
6. Write `index.json` and focused `stepN.md` files.
7. Show the phase/step plan to the user before execution unless they explicitly
   asked you to execute immediately.
8. Execute steps with `python scripts/execute.py <phase-name>` when approved.
9. Verify the result with the project's own lint, build, and test commands.
10. Summarize changed files, decisions, and verification.

## Phase Naming

Use a short ordered slug:

```text
1-payment-history
2-login
3-admin-dashboard
```

## Step Size

Each step should be independently reviewable. Prefer:

- one investigation step
- one data/API step
- one UI or integration step
- one verification and cleanup step

Avoid one giant "implement everything" step.

## Required Step Sections

Each `stepN.md` must include:

- Objective
- Files to inspect
- Implementation constraints
- Success criteria
- Verification commands
- Expected output contract

Use `templates/step.md` as the base.

## Output Contract

Every step should end with a concise JSON object:

```json
{
  "status": "completed",
  "summary": "One sentence summary.",
  "changed_files": ["path/to/file.ts"],
  "decisions": ["Important implementation decision."],
  "verification": ["npm run build"],
  "blockers": []
}
```

Use `status: "blocked"` if credentials, product decisions, or external access are
required.

