# Harness Framework

Harness Framework is a lightweight workflow layer for agent-assisted software work.
It keeps long-lived project rules small, moves the detailed workflow into a Claude
skill, and records feature work as explicit phases and steps.

## Why This Exists

LLM coding sessions fail most often when they start implementing before they have
understood the codebase, success criteria, and verification path. This framework
adds a repeatable workflow:

1. read the relevant project context
2. create a phase plan
3. split the work into small steps
4. execute each step with verification
5. save structured output for the next step or phase

## Structure

```text
.
├─ CLAUDE.md
├─ .claude/
│  ├─ commands/
│  │  └─ harness.md
│  ├─ settings.json
│  └─ skills/
│     └─ harness/
│        ├─ SKILL.md
│        └─ templates/
│           ├─ phase-index.json
│           ├─ step.md
│           └─ top-index.json
├─ docs/
│  ├─ ADR.md
│  ├─ ARCHITECTURE.md
│  └─ PRD.md
└─ scripts/
   ├─ execute.py
   └─ test_execute.py
```

## Recommended Usage

For complex work:

```text
/harness 를 사용해서 결제내역 기능을 구현해줘.
먼저 phase/step 계획을 보여주고 승인 후 진행해줘.
```

For small edits:

```text
하네스 없이 바로 수정해줘.
```

## Phase Layout

```text
phases/
├─ index.json
└─ 1-payment-history/
   ├─ index.json
   ├─ step0.md
   ├─ step1.md
   ├─ step0-output.json
   └─ step1-output.json
```

Completed phases are kept as project memory. New features should normally create
new phases instead of editing old phase plans.

## Execute A Phase

Run a phase from the project root:

```bash
python scripts/execute.py 1-payment-history
```

By default the executor is conservative:

- it does not inject every document into every prompt
- it does not skip Claude permissions
- it does not commit automatically
- it does not push automatically

Opt in when desired:

```bash
python scripts/execute.py 1-payment-history --branch --commit
python scripts/execute.py 1-payment-history --branch --commit --push
python scripts/execute.py 1-payment-history --unsafe-auto
```

## Tests

```bash
python -m unittest scripts.test_execute
```

