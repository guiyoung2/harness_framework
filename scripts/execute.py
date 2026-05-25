#!/usr/bin/env python3
"""Execute harness phase steps with minimal, explicit context."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path.cwd()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def truncate(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first valid JSON object from plain text or a fenced block."""
    decoder = json.JSONDecoder()
    stripped = text.strip()

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def normalize_step_result(raw_text: str, returncode: int) -> dict[str, Any]:
    parsed = extract_json_object(raw_text)
    if parsed:
        parsed.setdefault("status", "completed" if returncode == 0 else "error")
        parsed.setdefault("summary", truncate(raw_text, 400))
        parsed.setdefault("changed_files", [])
        parsed.setdefault("decisions", [])
        parsed.setdefault("verification", [])
        parsed.setdefault("blockers", [])
        return parsed

    return {
        "status": "completed" if returncode == 0 else "error",
        "summary": truncate(raw_text.strip() or "No output.", 400),
        "changed_files": [],
        "decisions": [],
        "verification": [],
        "blockers": [],
    }


@dataclass
class StepExecutor:
    phase_name: str
    unsafe_auto: bool = False
    use_branch: bool = False
    commit: bool = False
    push: bool = False

    @property
    def phase_dir(self) -> Path:
        return ROOT / "phases" / self.phase_name

    @property
    def index_path(self) -> Path:
        return self.phase_dir / "index.json"

    def run(self) -> int:
        if not self.index_path.exists():
            print(f"Missing phase index: {self.index_path}", file=sys.stderr)
            return 1

        if self.use_branch:
            self.checkout_branch()

        index = load_json(self.index_path)
        for step in index.get("steps", []):
            if step.get("status") == "completed":
                continue
            if step.get("status") == "blocked":
                print(f"Blocked step remains unresolved: {step.get('file')}", file=sys.stderr)
                return 2
            result = self.run_step(index, step)
            step.update(
                {
                    "status": result["status"],
                    "summary": result["summary"],
                    "changed_files": result["changed_files"],
                    "decisions": result["decisions"],
                    "verification": result["verification"],
                    "blockers": result["blockers"],
                    "updated_at": now_iso(),
                    "output_file": f"{Path(step['file']).stem}-output.json",
                }
            )
            save_json(self.index_path, index)

            if result["status"] != "completed":
                return 2 if result["status"] == "blocked" else 1

            if self.commit:
                self.commit_step(step)

        index["status"] = "completed"
        index["completed_at"] = now_iso()
        save_json(self.index_path, index)

        if self.commit:
            self.commit_metadata()
        if self.push:
            self.push_branch()
        return 0

    def run_step(self, index: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        step_path = self.phase_dir / step["file"]
        output_path = self.phase_dir / f"{step_path.stem}-output.json"
        prompt = self.build_prompt(index, step, step_path)
        command = ["claude", "-p", prompt, "--output-format", "json"]
        if self.unsafe_auto:
            command.append("--dangerously-skip-permissions")

        completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8")
        raw = completed.stdout.strip() or completed.stderr.strip()

        claude_payload = extract_json_object(raw)
        agent_text = raw
        if claude_payload and isinstance(claude_payload.get("result"), str):
            agent_text = claude_payload["result"]

        result = normalize_step_result(agent_text, completed.returncode)
        payload = {
            "phase": self.phase_name,
            "step": step.get("id"),
            "step_file": step["file"],
            "returncode": completed.returncode,
            "captured_at": now_iso(),
            "result": result,
            "raw_output": raw,
        }
        save_json(output_path, payload)
        return result

    def build_prompt(self, index: dict[str, Any], step: dict[str, Any], step_path: Path) -> str:
        root_rules = read_optional(ROOT / "CLAUDE.md")
        previous = [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "changed_files": item.get("changed_files", []),
                "decisions": item.get("decisions", []),
            }
            for item in index.get("steps", [])
            if item.get("status") == "completed"
        ]
        return "\n\n".join(
            [
                "# Harness Step Execution",
                "Follow the project rules and execute only the current step.",
                "Read files listed in the step before editing. Do not load every docs file unless the step asks for it.",
                "End with the JSON output contract requested by the step.",
                "## Project Rules",
                root_rules or "(No CLAUDE.md found.)",
                "## Phase Index",
                json.dumps(index, ensure_ascii=False, indent=2),
                "## Previous Completed Steps",
                json.dumps(previous, ensure_ascii=False, indent=2),
                "## Current Step",
                step_path.read_text(encoding="utf-8"),
            ]
        )

    def checkout_branch(self) -> None:
        branch = f"harness/{self.phase_name}"
        result = subprocess.run(["git", "checkout", "-B", branch], text=True)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    def commit_step(self, step: dict[str, Any]) -> None:
        subprocess.run(["git", "add", "-A"], check=True)
        title = step.get("title") or step.get("file")
        subprocess.run(["git", "commit", "-m", f"feat({self.phase_name}): {title}"], check=False)

    def commit_metadata(self) -> None:
        subprocess.run(["git", "add", str(self.phase_dir)], check=True)
        subprocess.run(["git", "commit", "-m", f"chore({self.phase_name}): complete phase metadata"], check=False)

    def push_branch(self) -> None:
        current = subprocess.run(["git", "branch", "--show-current"], text=True, capture_output=True, check=True)
        branch = current.stdout.strip()
        subprocess.run(["git", "push", "-u", "origin", branch], check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute a harness phase.")
    parser.add_argument("phase", help="Phase directory name under phases/.")
    parser.add_argument("--unsafe-auto", action="store_true", help="Pass --dangerously-skip-permissions to Claude.")
    parser.add_argument("--branch", action="store_true", help="Create/reset a harness/<phase> branch before execution.")
    parser.add_argument("--commit", action="store_true", help="Commit after each completed step.")
    parser.add_argument("--push", action="store_true", help="Push the current branch after completion. Implies --commit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    executor = StepExecutor(
        phase_name=args.phase,
        unsafe_auto=args.unsafe_auto,
        use_branch=args.branch,
        commit=args.commit or args.push,
        push=args.push,
    )
    return executor.run()


if __name__ == "__main__":
    raise SystemExit(main())

