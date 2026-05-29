#!/usr/bin/env python3
"""
Harness Step Executor — phase 내 step을 순차 실행하고 자가 교정한다.

Usage:
    python3 scripts/execute.py <phase-dir> [--push]
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

# Python 최소 버전 체크 (3.8+)
if sys.version_info < (3, 8):
    print(f"ERROR: Python 3.8 이상이 필요합니다. 현재: {sys.version}")
    sys.exit(1)

# Windows cp949 콘솔에서 한글/유니코드 출력 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_config(root: Path) -> dict:
    config_file = root / "harness.config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    return {"engine": "claude"}


class ClaudeAdapter:
    """claude -p 로 step을 실행하는 어댑터."""

    def run(self, prompt: str, cwd: str, timeout: int = 1800) -> tuple[int, str, str]:
        result = subprocess.run(
            ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "json", prompt],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr


class CodexAdapter:
    """codex CLI로 step을 실행하는 어댑터.

    NOTE: Codex CLI 비대화형 실행은 현재 `codex exec`를 사용한다.
    """

    def run(self, prompt: str, cwd: str, timeout: int = 1800) -> tuple[int, str, str]:
        # Windows에서 npm shim(.cmd) 우선 탐색
        if sys.platform == "win32":
            codex_bin = shutil.which("codex.cmd") or shutil.which("codex") or "codex"
        else:
            codex_bin = shutil.which("codex") or "codex"
        result = subprocess.run(
            [codex_bin, "exec", "--dangerously-bypass-approvals-and-sandbox", "-"],
            input=prompt, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr


def create_adapter(engine: str) -> ClaudeAdapter | CodexAdapter:
    if engine == "codex":
        return CodexAdapter()
    return ClaudeAdapter()


@contextlib.contextmanager
def progress_indicator(label: str):
    """터미널 진행 표시기. with 문으로 사용하며 .elapsed 로 경과 시간을 읽는다."""
    frames = "|/-\\"
    stop = threading.Event()
    t0 = time.monotonic()

    def _animate():
        idx = 0
        while not stop.wait(0.12):
            sec = int(time.monotonic() - t0)
            sys.stderr.write(f"\r{frames[idx % len(frames)]} {label} [{sec}s]")
            sys.stderr.flush()
            idx += 1
        sys.stderr.write("\r" + " " * (len(label) + 20) + "\r")
        sys.stderr.flush()

    th = threading.Thread(target=_animate, daemon=True)
    th.start()
    info = types.SimpleNamespace(elapsed=0.0)
    try:
        yield info
    finally:
        stop.set()
        th.join()
        info.elapsed = time.monotonic() - t0


class StepExecutor:
    """Phase 디렉토리 안의 step들을 순차 실행하는 하네스."""

    MAX_RETRIES = 3
    FEAT_MSG = "feat({phase}): step {num} — {name}"
    CHORE_MSG = "chore({phase}): step {num} output"
    TZ = timezone(timedelta(hours=9))

    def __init__(self, phase_dir_name: str, *, auto_push: bool = False):
        self._root = str(ROOT)
        self._phases_dir = ROOT / "phases"
        self._phase_dir = self._phases_dir / phase_dir_name
        self._phase_dir_name = phase_dir_name
        self._top_index_file = self._phases_dir / "index.json"

        config = load_config(ROOT)
        engine = config.get("engine", "claude")
        self._adapter = create_adapter(engine)
        self._engine_name = engine
        self._auto_push = auto_push or config.get("auto_push", False)

        if not self._phase_dir.is_dir():
            print(f"ERROR: {self._phase_dir} not found")
            sys.exit(1)

        self._index_file = self._phase_dir / "index.json"
        if not self._index_file.exists():
            print(f"ERROR: {self._index_file} not found")
            sys.exit(1)

        idx = self._read_json(self._index_file)
        self._project = idx.get("project", "project")
        self._phase_name = idx.get("phase", phase_dir_name)
        self._total = len(idx["steps"])

    def run(self):
        self._print_header()
        self._print_progress_on_start()
        self._check_blockers()
        self._checkout_branch()
        guardrails = self._load_guardrails()
        self._ensure_created_at()
        self._execute_all_steps(guardrails)
        self._finalize()

    # --- timestamps ---

    def _stamp(self) -> str:
        return datetime.now(self.TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

    # --- JSON I/O ---

    @staticmethod
    def _read_json(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(p: Path, data: dict):
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- git ---

    def _run_git(self, *args) -> subprocess.CompletedProcess:
        cmd = ["git"] + list(args)
        return subprocess.run(cmd, cwd=self._root, capture_output=True, text=True, encoding="utf-8")

    def _checkout_branch(self):
        branch = f"feat-{self._phase_name}"

        r = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if r.returncode != 0:
            print(f"  ERROR: git을 사용할 수 없거나 git repo가 아닙니다.")
            print(f"  {r.stderr.strip()}")
            sys.exit(1)

        if r.stdout.strip() == branch:
            return

        r = self._run_git("rev-parse", "--verify", branch)
        r = self._run_git("checkout", branch) if r.returncode == 0 else self._run_git("checkout", "-b", branch)

        if r.returncode != 0:
            print(f"  ERROR: 브랜치 '{branch}' checkout 실패.")
            print(f"  {r.stderr.strip()}")
            print(f"  Hint: 변경사항을 stash하거나 commit한 후 다시 시도하세요.")
            sys.exit(1)

        print(f"  Branch: {branch}")

    def _commit_step(self, step_num: int, step_name: str):
        output_rel = f"phases/{self._phase_dir_name}/step{step_num}-output.json"
        index_rel = f"phases/{self._phase_dir_name}/index.json"

        self._run_git("add", "-A")
        self._run_git("reset", "HEAD", "--", output_rel)
        self._run_git("reset", "HEAD", "--", index_rel)

        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = self.FEAT_MSG.format(phase=self._phase_name, num=step_num, name=step_name)
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  Commit: {msg}")
            else:
                print(f"  WARN: 코드 커밋 실패: {r.stderr.strip()}")

        self._run_git("add", "-A")
        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = self.CHORE_MSG.format(phase=self._phase_name, num=step_num)
            r = self._run_git("commit", "-m", msg)
            if r.returncode != 0:
                print(f"  WARN: housekeeping 커밋 실패: {r.stderr.strip()}")

    # --- top-level index ---

    def _update_top_index(self, status: str):
        if not self._top_index_file.exists():
            return
        top = self._read_json(self._top_index_file)
        ts = self._stamp()
        for phase in top.get("phases", []):
            if phase.get("dir") == self._phase_dir_name:
                phase["status"] = status
                ts_key = {"completed": "completed_at", "error": "failed_at", "blocked": "blocked_at"}.get(status)
                if ts_key:
                    phase[ts_key] = ts
                break
        self._write_json(self._top_index_file, top)

    # --- guardrails & context ---

    def _load_guardrails(self) -> str:
        sections = []
        agents_md = ROOT / "AGENTS.md"
        if agents_md.exists():
            sections.append(f"## 프로젝트 규칙 (AGENTS.md)\n\n{agents_md.read_text(encoding='utf-8')}")
        docs_dir = ROOT / "docs"
        if docs_dir.is_dir():
            for doc in sorted(docs_dir.glob("*.md")):
                sections.append(f"## {doc.stem}\n\n{doc.read_text(encoding='utf-8')}")
        return "\n\n---\n\n".join(sections) if sections else ""

    @staticmethod
    def _build_step_context(index: dict) -> str:
        lines = [
            f"- Step {s['step']} ({s['name']}): {s['summary']}"
            for s in index["steps"]
            if s["status"] == "completed" and s.get("summary")
        ]
        if not lines:
            return ""
        return "## 이전 Step 산출물\n\n" + "\n".join(lines) + "\n\n"

    def _build_preamble(self, guardrails: str, step_context: str,
                        prev_error: Optional[str] = None) -> str:
        commit_example = self.FEAT_MSG.format(
            phase=self._phase_name, num="N", name="<step-name>"
        )
        retry_section = ""
        if prev_error:
            retry_section = (
                f"\n## ⚠ 이전 시도 실패 — 아래 에러를 반드시 참고하여 수정하라\n\n"
                f"{prev_error}\n\n---\n\n"
            )
        return (
            f"당신은 {self._project} 프로젝트의 개발자입니다. 아래 step을 수행하세요.\n\n"
            f"{guardrails}\n\n---\n\n"
            f"{step_context}{retry_section}"
            f"## 절대 수정 금지 파일\n\n"
            f"아래 파일은 어떤 이유로도 수정하지 마라:\n"
            f"- `scripts/` 디렉토리 내 모든 파일 (execute.py 포함)\n"
            f"- `harness.config.json`\n\n"
            f"---\n\n"
            f"## 작업 규칙\n\n"
            f"1. 이전 step에서 작성된 코드를 확인하고 일관성을 유지하라.\n"
            f"2. 이 step에 명시된 작업만 수행하라. 추가 기능이나 파일을 만들지 마라.\n"
            f"3. 기존 테스트를 깨뜨리지 마라.\n"
            f"4. AC(Acceptance Criteria) 검증을 직접 실행하라.\n"
            f"5. /phases/{self._phase_dir_name}/index.json의 해당 step status를 업데이트하라:\n"
            f"   - AC 통과 → \"completed\" + \"summary\" 필드에 이 step의 산출물을 한 줄로 요약\n"
            f"   - {self.MAX_RETRIES}회 수정 시도 후에도 실패 → \"error\" + \"error_message\" 기록\n"
            f"   - 사용자 개입이 필요한 경우 (API 키, 인증, 수동 설정 등) → \"blocked\" + \"blocked_reason\" 기록 후 즉시 중단\n"
            f"6. 모든 변경사항을 커밋하라:\n"
            f"   {commit_example}\n"
            f"7. 이 step 완료 후 반드시 다음 두 파일을 업데이트하라:\n"
            f"   a. phases/{self._phase_dir_name}/progress.md — '다음 할 일'과 '주의사항' 섹션을 현재 상태 기준으로 갱신\n"
            f"      ('다음 할 일': 다음 step에서 해야 할 것, 필요한 준비사항)\n"
            f"      ('주의사항': 이 step에서 발견한 트랩, 외부 의존성, 중요 설정값 등)\n"
            f"   b. phases/{self._phase_dir_name}/feature_list.json — 이 step에서 완료된 feature를 업데이트:\n"
            f"      passes: true, verified_at: ISO-8601 현재 시각, verified_by_step: <현재 step 번호>\n"
            f"   (두 파일이 없으면 스킵)\n\n---\n\n"
        )

    @staticmethod
    def _check_rate_limit(output: dict) -> tuple[bool, str]:
        """output JSON에서 rate limit(429) 여부 감지. (is_rate_limit, message)"""
        try:
            data = json.loads(output.get("stdout", "{}"))
            if data.get("api_error_status") == 429:
                return True, data.get("result", "session limit reached")
        except (json.JSONDecodeError, TypeError):
            pass
        return False, ""

    # --- 엔진 호출 ---

    def _invoke_engine(self, step: dict, preamble: str) -> dict:
        step_num, step_name = step["step"], step["name"]
        step_file = self._phase_dir / f"step{step_num}.md"

        if not step_file.exists():
            print(f"  ERROR: {step_file} not found")
            sys.exit(1)

        prompt = preamble + step_file.read_text(encoding='utf-8')
        returncode, stdout, stderr = self._adapter.run(prompt, self._root)

        if returncode != 0:
            print(f"\n  WARN: {self._engine_name}이 비정상 종료됨 (code {returncode})")
            if stderr:
                print(f"  stderr: {stderr[:500]}")

        output = {
            "step": step_num, "name": step_name,
            "exitCode": returncode,
            "stdout": stdout, "stderr": stderr,
        }
        out_path = self._phase_dir / f"step{step_num}-output.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output

    # --- 헤더 & 검증 ---

    def _print_header(self):
        print(f"\n{'='*60}")
        print(f"  Harness Step Executor")
        print(f"  Phase: {self._phase_name} | Steps: {self._total}")
        print(f"  Engine: {self._engine_name}")
        if self._auto_push:
            print(f"  Auto-push: enabled")
        print(f"{'='*60}")

    def _check_blockers(self):
        index = self._read_json(self._index_file)
        for s in reversed(index["steps"]):
            if s["status"] == "error":
                print(f"\n  ✗ Step {s['step']} ({s['name']}) failed.")
                print(f"  Error: {s.get('error_message', 'unknown')}")
                print(f"  Fix and reset status to 'pending' to retry.")
                sys.exit(1)
            if s["status"] == "blocked":
                print(f"\n  ⏸ Step {s['step']} ({s['name']}) blocked.")
                print(f"  Reason: {s.get('blocked_reason', 'unknown')}")
                print(f"  Resolve and reset status to 'pending' to retry.")
                sys.exit(2)
            if s["status"] != "pending":
                break

    def _ensure_created_at(self):
        index = self._read_json(self._index_file)
        if "created_at" not in index:
            index["created_at"] = self._stamp()
            self._write_json(self._index_file, index)

    # --- 실행 루프 ---

    def _execute_single_step(self, step: dict, guardrails: str) -> bool:
        """단일 step 실행 (재시도 포함). 완료되면 True, 실패/차단이면 False."""
        step_num, step_name = step["step"], step["name"]
        done = sum(1 for s in self._read_json(self._index_file)["steps"] if s["status"] == "completed")
        prev_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            index = self._read_json(self._index_file)
            step_context = self._build_step_context(index)
            preamble = self._build_preamble(guardrails, step_context, prev_error)

            tag = f"Step {step_num}/{self._total - 1} ({done} done): {step_name}"
            if attempt > 1:
                tag += f" [retry {attempt}/{self.MAX_RETRIES}]"

            with progress_indicator(tag) as pi:
                output = self._invoke_engine(step, preamble)
                elapsed = int(pi.elapsed)

            # 비정상 종료 시 재시도 없이 즉시 error 처리 (토큰 소모, 프로세스 크래시 등)
            if output["exitCode"] != 0:
                index = self._read_json(self._index_file)
                cur_status = next((s.get("status", "pending") for s in index["steps"] if s["step"] == step_num), "pending")
                if cur_status == "pending":
                    ts = self._stamp()
                    for s in index["steps"]:
                        if s["step"] == step_num:
                            s["status"] = "error"
                            s["error_message"] = f"엔진 비정상 종료 (code {output['exitCode']})"
                            s["failed_at"] = ts
                    self._write_json(self._index_file, index)
                    self._update_progress_skeleton()
                    self._commit_step(step_num, step_name)
                    self._update_top_index("error")
                    print(f"  ✗ Step {step_num}: {step_name} 비정상 종료 (code {output['exitCode']}) [{elapsed}s]")
                    print(f"    토큰 소모 또는 오류로 중단됨. status를 'pending'으로 리셋 후 재실행하세요.")
                    sys.exit(1)

            # Rate limit 감지: LLM이 실행 자체가 안 된 경우 즉시 blocked 처리
            is_rate_limit, rate_msg = self._check_rate_limit(output)
            if is_rate_limit:
                ts = self._stamp()
                index = self._read_json(self._index_file)
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["status"] = "blocked"
                        s["blocked_reason"] = f"rate-limit (429): {rate_msg}"
                        s["blocked_at"] = ts
                self._write_json(self._index_file, index)
                self._update_top_index("blocked")
                print(f"\n  ⏸ Step {step_num}: rate limited [{elapsed}s]")
                print(f"    {rate_msg}")
                print(f"    세션 한도 리셋 후 status를 'pending'으로 바꾸고 재실행하세요.")
                sys.exit(2)

            index = self._read_json(self._index_file)
            status = next((s.get("status", "pending") for s in index["steps"] if s["step"] == step_num), "pending")
            ts = self._stamp()

            if status == "completed":
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["completed_at"] = ts
                self._write_json(self._index_file, index)
                self._update_progress_skeleton()
                self._commit_step(step_num, step_name)
                print(f"  ✓ Step {step_num}: {step_name} [{elapsed}s]")
                return True

            if status == "blocked":
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["blocked_at"] = ts
                self._write_json(self._index_file, index)
                reason = next((s.get("blocked_reason", "") for s in index["steps"] if s["step"] == step_num), "")
                print(f"  ⏸ Step {step_num}: {step_name} blocked [{elapsed}s]")
                print(f"    Reason: {reason}")
                self._update_top_index("blocked")
                sys.exit(2)

            err_msg = next(
                (s.get("error_message", "") for s in index["steps"] if s["step"] == step_num),
                "",
            )
            if not err_msg:
                try:
                    out_data = self._read_json(self._phase_dir / f"step{step_num}-output.json")
                    stdout_data = json.loads(out_data.get("stdout", "{}"))
                    result = stdout_data.get("result", "")
                    err_msg = (
                        f"LLM이 status를 업데이트하지 않음. result: {result[:200]}"
                        if result else "Step did not update status"
                    )
                except Exception:
                    err_msg = "Step did not update status"

            if attempt < self.MAX_RETRIES:
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["status"] = "pending"
                        s.pop("error_message", None)
                self._write_json(self._index_file, index)
                prev_error = err_msg
                print(f"  ↻ Step {step_num}: retry {attempt}/{self.MAX_RETRIES} — {err_msg}")
            else:
                for s in index["steps"]:
                    if s["step"] == step_num:
                        s["status"] = "error"
                        s["error_message"] = f"[{self.MAX_RETRIES}회 시도 후 실패] {err_msg}"
                        s["failed_at"] = ts
                self._write_json(self._index_file, index)
                self._commit_step(step_num, step_name)
                print(f"  ✗ Step {step_num}: {step_name} failed after {self.MAX_RETRIES} attempts [{elapsed}s]")
                print(f"    Error: {err_msg}")
                self._update_top_index("error")
                sys.exit(1)

        return False  # unreachable

    def _execute_all_steps(self, guardrails: str):
        while True:
            index = self._read_json(self._index_file)
            pending = next((s for s in index["steps"] if s["status"] == "pending"), None)
            if pending is None:
                print("\n  All steps completed!")
                return

            step_num = pending["step"]
            for s in index["steps"]:
                if s["step"] == step_num and "started_at" not in s:
                    s["started_at"] = self._stamp()
                    self._write_json(self._index_file, index)
                    break

            self._execute_single_step(pending, guardrails)

    # --- 진행 현황 & 완료 게이트 ---

    def _print_progress_on_start(self):
        """이전 진행 현황을 출력해 새 세션에서 빠르게 컨텍스트를 파악한다."""
        progress_path = self._phase_dir / "progress.md"
        if progress_path.exists():
            print(f"\n{'='*60}")
            print("  이전 진행 현황")
            print(f"{'='*60}")
            print(progress_path.read_text(encoding="utf-8"))
            print(f"{'='*60}\n")

    def _update_progress_skeleton(self):
        """progress.md의 자동 섹션(타임스탬프, step 목록)을 갱신. LLM 섹션은 보존."""
        progress_path = self._phase_dir / "progress.md"
        index = self._read_json(self._index_file)
        steps = index["steps"]

        completed = [s for s in steps if s["status"] == "completed"]
        pending = next((s for s in steps if s["status"] == "pending"), None)
        done_count = len(completed)
        total = len(steps)

        # LLM이 작성한 섹션 보존
        llm_todo = "(LLM이 각 step 종료 시 작성)"
        llm_notes = "(LLM이 각 step 종료 시 작성)"
        if progress_path.exists():
            content = progress_path.read_text(encoding="utf-8")
            todo_marker = "\n## 다음 할 일\n"
            notes_marker = "\n## 주의사항\n"
            if todo_marker in content:
                after_todo = content[content.index(todo_marker) + len(todo_marker):]
                if notes_marker in after_todo:
                    llm_todo = after_todo[:after_todo.index(notes_marker)].strip()
                    llm_notes = after_todo[after_todo.index(notes_marker) + len(notes_marker):].strip()
                else:
                    llm_todo = after_todo.strip()

        completed_lines = "\n".join(
            f"- Step {s['step']}: {s['name']} — {s.get('summary', '완료')}"
            for s in completed
        ) or "- 없음"
        current = (
            f"- Step {pending['step']}: {pending['name']}" if pending else "- 모든 step 완료"
        )

        new_content = (
            f"# {self._phase_name} 진행 현황\n\n"
            f"## 마지막 업데이트\n"
            f"{self._stamp()} — Step {done_count}/{total} 완료\n\n"
            f"## 완료된 작업\n{completed_lines}\n\n"
            f"## 현재 진행 중\n{current}\n\n"
            f"## 다음 할 일\n{llm_todo}\n\n"
            f"## 주의사항\n{llm_notes}\n"
        )
        progress_path.write_text(new_content, encoding="utf-8")

    def _check_completion_gate(self):
        """feature_list.json의 모든 feature가 passes: true인지 확인. 미통과 시 중단."""
        feature_list_path = self._phase_dir / "feature_list.json"
        if not feature_list_path.exists():
            return
        data = self._read_json(feature_list_path)
        remaining = [f for f in data.get("features", []) if not f.get("passes", False)]
        if remaining:
            print(f"\n{'='*60}")
            print(f"  ⚠️  완료 선언 불가: {len(remaining)}개 feature 미통과")
            for f in remaining:
                print(f"  - [{f['id']}] {f['name']}")
            print(f"{'='*60}")
            sys.exit(1)

    def _finalize(self):
        self._check_completion_gate()
        index = self._read_json(self._index_file)
        index["completed_at"] = self._stamp()
        self._write_json(self._index_file, index)
        self._update_top_index("completed")

        self._run_git("add", "-A")
        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = f"chore({self._phase_name}): mark phase completed"
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  ✓ {msg}")

        if self._auto_push:
            branch = f"feat-{self._phase_name}"
            r = self._run_git("push", "-u", "origin", branch)
            if r.returncode != 0:
                print(f"\n  ERROR: git push 실패: {r.stderr.strip()}")
                sys.exit(1)
            print(f"  ✓ Pushed to origin/{branch}")

        print(f"\n{'='*60}")
        print(f"  Phase '{self._phase_name}' completed!")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Harness Step Executor")
    parser.add_argument("phase_dir", help="Phase directory name (e.g. 0-mvp)")
    parser.add_argument("--push", action="store_true", help="Push branch after completion")
    args = parser.parse_args()

    StepExecutor(args.phase_dir, auto_push=args.push).run()


if __name__ == "__main__":
    main()
