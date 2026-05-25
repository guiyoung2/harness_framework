# Step N: Title

## Objective

Describe the one outcome this step must produce.

## Files To Inspect

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`

## Implementation Constraints

- Keep the change scoped to this step.
- Follow existing project style.
- Do not refactor unrelated code.

## Success Criteria

- The requested behavior is implemented.
- Verification commands pass.
- The final output follows the output contract.

## Verification Commands

```bash
npm run build
```

## Output Contract

Return a JSON object:

```json
{
  "status": "completed",
  "summary": "One sentence summary.",
  "changed_files": [],
  "decisions": [],
  "verification": [],
  "blockers": []
}
```

