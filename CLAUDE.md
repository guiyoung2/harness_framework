# CRITICAL (절대 규칙)

- 불확실하면 구현 전에 질문한다.
- 요청 범위 밖 리팩토링·"개선"을 하지 않는다.
- 95% 확신 전에는 변경하지 않는다. 부족하면 질문한다.
- 기능 단위 작업은 `/harness`로 phase/step 계획을 만든 뒤 진행한다.
- 모든 step 파일은 자기완결적이어야 한다 — "이전 대화에서…" 같은 외부 참조 금지.

# 프로젝트

- 이름: {프로젝트명}
- 기술 스택: {예: Next.js 15, TypeScript strict, Tailwind}

# 토큰 절약 규칙

- 이미 읽은 파일은 다시 읽지 않는다.
- 도구 호출은 가능한 한 병렬로 실행한다.
- 20줄 이상 분석은 서브에이전트에 위임한다.
- 사용자가 이미 설명한 내용은 반복하지 않는다.
- `@`로 500줄 초과 파일 전체 참조 금지 (필요한 구간·심볼만 지정).

# 명령어

- 빌드: {예: npm run build}
- 테스트: {예: npm test -- --run}
- 린트: {예: npm run lint:fix}
- 타입체크: {예: tsc --noEmit}

# 상세 가이드 (필요할 때만 읽음)

@.claude/rules/coding-principles.md
@.claude/rules/token-saving.md

# 참고 문서 (직접 읽기)

- `docs/ARCHITECTURE.md` — 디렉토리·아키텍처 규칙
- `docs/ADR.md` — 기술 스택 결정
- `docs/PRD.md` — 제품 요구사항
- `docs/UI_GUIDE.md` — UI 디자인 가이드 + AI 슬롭 안티패턴
