# Harness Framework

Harness Framework는 에이전트(LLM) 기반 소프트웨어 작업을 위한 경량 워크플로우 레이어다. 프로젝트 규칙은 짧게 유지하고, 상세 워크플로우는 Claude 스킬로 옮기며, 기능 작업을 명시적인 phase·step으로 기록한다.

## 왜 필요한가

LLM 코딩 세션이 가장 자주 실패하는 지점은 **코드베이스·성공 기준·검증 경로를 이해하기 전에 구현을 시작할 때**다. 이 프레임워크는 반복 가능한 워크플로우를 더해 그 실패를 막는다:

1. 관련 프로젝트 컨텍스트를 읽는다
2. phase 계획을 만든다
3. 작업을 작은 step으로 쪼갠다
4. 각 step을 검증과 함께 실행한다
5. 다음 step·phase를 위한 구조화된 출력을 저장한다

## 구조

```text
.
├─ CLAUDE.md
├─ .claudeignore
├─ .claude/
│  ├─ commands/
│  │  ├─ harness.md
│  │  └─ review.md
│  ├─ rules/
│  │  ├─ coding-principles.md
│  │  └─ token-saving.md
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
│  ├─ PRD.md
│  └─ UI_GUIDE.md
└─ scripts/
   ├─ execute.py
   └─ test_execute.py
```

## 사용법

복잡한 작업:

```text
/harness 를 사용해서 결제내역 기능을 구현해줘.
먼저 phase/step 계획을 보여주고 승인 후 진행해줘.
```

간단한 수정:

```text
하네스 없이 바로 수정해줘.
```

## phase 디렉토리 레이아웃

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

완료된 phase는 프로젝트 메모리로 보존된다. 새 기능은 기존 phase를 수정하지 않고 새 phase로 만든다.

## phase 실행

프로젝트 루트에서 실행:

```bash
python scripts/execute.py 1-payment-history
```

기본 동작은 보수적이다:

- 모든 문서를 매 프롬프트에 주입하지 않는다
- Claude 권한 확인을 건너뛰지 않는다
- 자동 커밋하지 않는다
- 자동 push 하지 않는다

원할 때 opt-in:

```bash
python scripts/execute.py 1-payment-history --branch --commit
python scripts/execute.py 1-payment-history --branch --commit --push
python scripts/execute.py 1-payment-history --unsafe-auto
```

## 테스트

```bash
python -m unittest scripts.test_execute
```

## 참고 자료

- [Andrej Karpathy 스킬 모음](https://github.com/multica-ai/andrej-karpathy-skills) — Karpathy가 평소 쓰는 워크플로우와 컨벤션을 스킬 형태로 정리한 모음집. 전역(`~/.claude/CLAUDE.md`) 적용 권장
- [claude-plugins-official](https://github.com/anthropics/claude-plugins-official) — Anthropic 공식 플러그인. `/revise-claude-md`, `/claude-md-improver`로 CLAUDE.md 자동 다이어트
