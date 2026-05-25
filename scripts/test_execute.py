import json
import tempfile
import unittest
from pathlib import Path

import scripts.execute as execute
from scripts.execute import extract_json_object, normalize_step_result, StepExecutor


class ExtractJsonObjectTest(unittest.TestCase):
    def test_extracts_plain_json(self):
        self.assertEqual(extract_json_object('{"status": "completed"}'), {"status": "completed"})

    def test_extracts_fenced_json(self):
        text = """```json
{"summary": "done"}
```"""
        self.assertEqual(extract_json_object(text), {"summary": "done"})

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_json_object("no structured output"))


class NormalizeStepResultTest(unittest.TestCase):
    def test_fills_defaults_for_structured_output(self):
        result = normalize_step_result('{"summary": "done"}', 0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"], "done")
        self.assertEqual(result["changed_files"], [])

    def test_uses_error_status_for_unstructured_failure(self):
        result = normalize_step_result("command failed", 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["summary"], "command failed")


class BuildPromptTest(unittest.TestCase):
    def test_prompt_does_not_inline_docs_by_default(self):
        original_root = execute.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            execute.ROOT = Path(tmp)
            phase_dir = execute.ROOT / "phases/example"
            phase_dir.mkdir(parents=True, exist_ok=True)
            step_path = phase_dir / "step0.md"
            step_path.write_text("# Step 0\n\nRead `docs/ARCHITECTURE.md`.", encoding="utf-8")
            (execute.ROOT / "docs").mkdir(exist_ok=True)
            (execute.ROOT / "docs/ARCHITECTURE.md").write_text("large architecture document", encoding="utf-8")
            index = {
                "steps": [
                    {"id": 0, "file": "step0.md", "status": "pending"},
                    {"id": 1, "file": "step1.md", "status": "completed", "summary": "prior"},
                ]
            }

            prompt = StepExecutor("example").build_prompt(index, index["steps"][0], step_path)

            self.assertIn("Read `docs/ARCHITECTURE.md`.", prompt)
            self.assertIn('"summary": "prior"', prompt)
            self.assertNotIn("large architecture document", prompt)
        execute.ROOT = original_root


if __name__ == "__main__":
    unittest.main()
