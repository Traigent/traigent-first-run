"""Python source inspection honors source encodings without executing the files."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from test_generate_adapter import AGENT, EVALUATOR, GENERATOR, Project


class AdapterSourceEncodingTests(unittest.TestCase):
    @staticmethod
    def encoded(source: str, encoding: str) -> bytes:
        source = "# café\n" + source
        if encoding == "bom":
            return b"\xef\xbb\xbf" + source.encode("utf-8")
        return (f"# coding: {encoding}\n" + source).encode(encoding)

    def test_generate_and_suggest_preserve_encoded_callables_without_execution(
        self,
    ) -> None:
        for encoding in ("utf-8", "bom", "latin-1"):
            with self.subTest(encoding=encoding):
                project = Project(self)
                for name, source in (("agent.py", AGENT), ("evaluator.py", EVALUATOR)):
                    (project.root / name).write_bytes(
                        self.encoded(
                            "raise RuntimeError('static inspection executed customer source')\n"
                            + source,
                            encoding,
                        )
                    )
                original = {p: p.read_bytes() for p in project.root.glob("*.py")}
                done = project.generate()
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                found = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(GENERATOR),
                        "suggest",
                        "--project-root",
                        str(project.root),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(found.returncode, 0, found.stderr)
                functions = {
                    item["callable"]: item["parameters"]
                    for item in json.loads(found.stdout)["functions"]
                }
                self.assertEqual(
                    functions["agent:answer"],
                    ["text", "model", "temperature", "suffix"],
                )
                self.assertEqual(functions["evaluator:exact"], ["output", "expected"])
                self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_encoded_imports_and_package_initializers_are_statically_inspected(
        self,
    ) -> None:
        for encoding in ("utf-8", "bom", "latin-1"):
            with self.subTest(encoding=encoding):
                project = Project(self, agent="import helper\n" + AGENT)
                helper = project.root / "helper.py"
                helper.write_bytes(
                    self.encoded(
                        "raise RuntimeError('never import helper')\n", encoding
                    )
                )
                package = project.root / "grading"
                package.mkdir()
                (package / "__init__.py").write_bytes(
                    self.encoded(
                        "raise RuntimeError('never import package')\n", encoding
                    )
                )
                (package / "evaluator.py").write_bytes(
                    self.encoded(EVALUATOR, encoding)
                )
                project.config["evaluator"]["callable"] = "grading.evaluator:exact"
                done = project.generate()
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_invalid_encoded_sources_refuse_generation_before_writing(self) -> None:
        for raw in (
            b"# coding: no-such-codec\ndef answer(text, model, temperature): return text\n",
            b"\xef\xbb\xbf# coding: latin-1\ndef answer(text, model, temperature): return text\n",
            b"def answer(text, model, temperature:\n    return text\n",
        ):
            for placement in ("agent", "helper"):
                with self.subTest(source=raw, placement=placement):
                    project = Project(
                        self,
                        agent=(
                            "import helper\n" + AGENT
                            if placement == "helper"
                            else AGENT
                        ),
                    )
                    path = project.root / f"{placement}.py"
                    path.write_bytes(raw)
                    done = project.generate()
                    self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                    self.assertFalse(project.runs.exists())
                    self.assertIn(
                        path.name, " ".join(json.loads(done.stdout)["refused"])
                    )
                    self.assertEqual(path.read_bytes(), raw)
