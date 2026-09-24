"""The run processes leave no bytecode beside the customer's own modules.

traigent-first-run#565. The free mock plumbing check and both paid phases import
the customer's preserved agent and evaluator, and an ordinary import writes
`__pycache__/*.pyc` next to the module it loads. Those files sit outside
`traigent-runs/`, deleting that folder leaves them behind, and the close's list
of what the run wrote never named them. The guide's answer is one verbatim line
in each entry point it hands the assistant: the generated wrapper in
`references/sdk-execution.md` and the mock activation prelude in
`references/run-safety.md` both open with `sys.dont_write_bytecode = True`,
ahead of every other import.

Run rather than read. Each test writes a three-module project, builds the entry
point from the document's own fence, imports the preserved modules at the
earliest place an assistant could put them, and runs it as a real process with
the reproduction's no-spend setup: no provider or Traigent key, a scratch `HOME`
so no stored login exists, and every proxy pointed at a discard port. The
wrapper places no provider call while it loads, and says so on its exit line;
the mock check runs under the SDK's mock responses. The environment is built
from nothing, so an inherited `PYTHONDONTWRITEBYTECODE` or `PYTHONPYCACHEPREFIX`
cannot pass a test on the developer's behalf.

The third test redirects the bytecode cache into a directory of its own, so a
write into the installed packages is seen too: an environment installed without
compiled bytecode is written to by the SDK's own imports if they come first.

Each test runs a control: the same program with the line switched off. It has
to leave bytecode behind, which is what shows this harness can see the defect
at all - an empty result from a fixture that never imported anything would read
exactly like a fix.

What this proves: the guide's own lines, run as the guide gives them, keep the
customer's project, and every other directory, free of bytecode. What it does
not: that an assistant keeps the line when it writes its copy, or anything about
a subprocess the customer's agent starts - the flag is per-process, and a child
interpreter reads only its own flags and environment.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "skills" / "traigent-first-run" / "references"
REQUIREMENTS = (
    ROOT / "skills" / "traigent-first-run" / "assets" / "requirements-first-run.txt"
)
THE_LINE = "sys.dont_write_bytecode = True"
SWITCHED_OFF = "sys.dont_write_bytecode = False"

# The customer's project: an agent that imports a helper module of its own,
# and an evaluator. Three modules, so a write beside a transitively imported
# helper is seen as well as one beside the module named directly.
PRESERVED_MODULES = {
    "prompts.py": 'SYSTEM = "Classify the query as billing or technical."\n',
    "support_agent.py": textwrap.dedent("""\
        import litellm

        from prompts import SYSTEM


        def classify(message, model="gpt-4o-mini", temperature=0.0):
            response = litellm.completion(
                model=model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": message},
                ],
            )
            return response.choices[0].message.content
        """),
    "grading.py": textwrap.dedent("""\
        def exact(output, expected):
            return float(str(output).strip().lower() == str(expected).strip().lower())
        """),
}
PRESERVED_BYTECODE = {
    f"__pycache__/{Path(name).stem}.{sys.implementation.cache_tag}.pyc"
    for name in PRESERVED_MODULES
}
TUNING_ROWS = (
    {"input": {"message": "I was charged twice"}, "output": "billing"},
    {"input": {"message": "The API returns 500"}, "output": "technical"},
)

# The preserved imports, placed at the earliest point each entry point allows:
# the wrapper's first `# ADAPT:` site, and straight after the mock prelude.
# `sys` is imported here as well, so a document without the line fails on the
# bytecode, never on a NameError.
IMPORT_THE_CUSTOMER_MODULES = textwrap.dedent("""\
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import grading  # noqa: E402
    import support_agent  # noqa: E402
    """)

FREE_MOCK_CHECK_BODY = textwrap.dedent("""\
    import traigent  # noqa: E402
    from traigent import Choices  # noqa: E402


    @traigent.optimize(
        eval_dataset=str(Path(__file__).resolve().parent / "tuning.jsonl"),
        objectives=["accuracy"],
        model=Choices(["gpt-4o-mini"]),
        temperature=Choices([0.0]),
        scoring_function=grading.exact,
    )
    def agent(message: str) -> str:
        config = traigent.get_config()
        return support_agent.classify(
            message, model=config["model"], temperature=config["temperature"]
        )


    results = agent.optimize_sync(max_trials=1, algorithm="grid")
    print("free mock check trials", len(results.trials))
    """)


def fence_holding(document: Path, marker: str) -> str:
    """The one python fence in `document` that contains `marker`, dedented."""
    fences = [
        textwrap.dedent(block)
        for block in re.findall(
            r"```python\n(.*?)\n\s*```", document.read_text(encoding="utf-8"), re.DOTALL
        )
        if marker in block
    ]
    if len(fences) != 1:
        raise AssertionError(
            f"{document.name} has {len(fences)} python fences containing "
            f"{marker!r}; this test runs exactly one"
        )
    return fences[0]


def bytecode_under(project: Path) -> set[str]:
    """Every `__pycache__` file and stray `.pyc` beneath the project."""
    return {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.suffix == ".pyc" or path.parent.name == "__pycache__"
    }


def run_entry_point(
    source: str,
    name: str,
    extra_environment: dict[str, str],
    *,
    pycache_prefix: bool = False,
) -> tuple[subprocess.CompletedProcess[str], set[str], set[str]]:
    """Run `source` as `traigent-runs/<name>` in a fresh project, from its root.

    Returns the process, the bytecode under the project, and - only with
    `pycache_prefix` - every bytecode file the process wrote anywhere, named by
    the source path it caches. The prefix redirects every write, the pinned
    stack's site-packages included, into one directory this test owns, and
    makes the interpreter ignore the caches already installed, so an import
    that is allowed to write does write.
    """
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        runs = project / "traigent-runs"
        runs.mkdir(parents=True)
        home = Path(directory) / "home"
        home.mkdir()
        prefix = Path(directory) / "pycache-prefix"
        for module, text in PRESERVED_MODULES.items():
            (project / module).write_text(text, encoding="utf-8")
        (runs / "tuning.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in TUNING_ROWS), encoding="utf-8"
        )
        (runs / name).write_text(source, encoding="utf-8")
        environment = {
            "HOME": str(home),
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "TRAIGENT_RESULTS_FOLDER": str(runs / "results"),
            # The interpreter's own installation is found without this; it is
            # here for a contributor whose pinned stack sits on a path entry
            # the scratch HOME would otherwise hide.
            "PYTHONPATH": os.pathsep.join(
                str(Path(entry).resolve()) for entry in sys.path if entry
            ),
            **({"PYTHONPYCACHEPREFIX": str(prefix)} if pycache_prefix else {}),
            **extra_environment,
        }
        process = subprocess.run(
            [sys.executable, str(Path("traigent-runs") / name)],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        # Named by the cached source's path, with this run's own temporary
        # directory taken out, so two runs can be compared file for file.
        anywhere = {
            "/"
            + path.relative_to(prefix)
            .as_posix()
            .replace(Path(directory).as_posix().lstrip("/"), "<run>")
            for path in (prefix.rglob("*.pyc") if prefix.exists() else ())
        }
        return process, bytecode_under(project), anywhere


def at_the_first_adapt_site(wrapper: str, block: str) -> str:
    """`block` inserted where the assistant first edits the wrapper.

    The guide imports a preserved module after the door, but the earliest place
    an assistant may put one is the first `# ADAPT:` site - adapting
    `build_request` from the customer's own agent is the ordinary reason. A
    line that only precedes the door would pass a test importing at the end.
    """
    lines = wrapper.splitlines(keepends=True)
    sites = [index for index, line in enumerate(lines) if line.startswith("# ADAPT:")]
    if not sites:
        raise AssertionError("the wrapper fence has no top-level `# ADAPT:` site")
    return "".join(lines[: sites[0]]) + block + "\n" + "".join(lines[sites[0] :])


BASELINE_PHASE = {
    "TRAIGENT_FIRST_RUN_PHASE": "baseline",
    "TRAIGENT_FIRST_RUN_COST_CEILING_USD": "5.00",
    "TRAIGENT_FIRST_RUN_COST_SPENT_USD": "0",
    "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD": "0.05",
    "TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS": "60",
    "TRAIGENT_FIRST_RUN_CURRENT_MODEL": "openai/current",
    "TRAIGENT_FIRST_RUN_ALTERNATIVE_MODEL": "openai/alternative",
    "TRAIGENT_FIRST_RUN_STRONG_MODEL": "openai/strong",
    "TRAIGENT_FIRST_RUN_CURRENT_PROVIDER": "openai",
}
NOTHING_PLACED = "this process placed 0 provider call(s)"
MOCK_MODE = {"TRAIGENT_OFFLINE_MODE": "true"}
MOCK_CHECK_RAN = "free mock check trials 1"


def wrapper_entry_point() -> str:
    wrapper = fence_holding(REFERENCES / "sdk-execution.md", "TRACKED_RUN = agent")
    return at_the_first_adapt_site(wrapper, IMPORT_THE_CUSTOMER_MODULES)


def mock_check_entry_point() -> str:
    prelude = fence_holding(
        REFERENCES / "run-safety.md", "enable_mock_mode_for_quickstart"
    )
    return f"{prelude}\n{IMPORT_THE_CUSTOMER_MODULES}\n{FREE_MOCK_CHECK_BODY}"


class RunProcessesWriteNoBytecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        missing = [
            name
            for name in ("litellm", "traigent")
            if importlib.util.find_spec(name) is None
        ]
        if not missing:
            return
        message = (
            f"{', '.join(missing)} is not installed; install {REQUIREMENTS} to run "
            "the guide's entry points against the pinned SDK"
        )
        if os.environ.get("CI"):
            self.fail(f"{message}. Under CI this must fail, never skip.")
        self.skipTest(message)

    def assertRan(
        self, process: subprocess.CompletedProcess[str], evidence: str
    ) -> None:
        self.assertEqual(
            process.returncode,
            0,
            f"the entry point did not run: stdout={process.stdout!r} "
            f"stderr={process.stderr!r}",
        )
        self.assertIn(evidence, process.stdout)

    def test_the_paid_wrapper_leaves_no_bytecode_beside_the_customer_modules(
        self,
    ) -> None:
        """The whole wrapper fence, loaded as a baseline process that spends nothing.

        Loading it is the part of every paid phase that imports the customer's
        modules, and it places no provider call - the exit line the wrapper
        prints on the way out says `placed 0 provider call(s)`, and the test
        requires it. The customer's modules are imported at the first `# ADAPT:`
        site, the earliest an assistant edits, so a line placed anywhere below
        it lets their bytecode through.
        """
        source = wrapper_entry_point()

        process, bytecode, _ = run_entry_point(source, "run_phase.py", BASELINE_PHASE)
        self.assertRan(process, NOTHING_PLACED)
        self.assertEqual(
            bytecode,
            set(),
            "the wrapper imported the customer's modules and left bytecode in "
            "their project",
        )

        control, written, _ = run_entry_point(
            source.replace(THE_LINE, SWITCHED_OFF), "run_phase.py", BASELINE_PHASE
        )
        self.assertRan(control, NOTHING_PLACED)
        self.assertLessEqual(PRESERVED_BYTECODE, written)

    def test_the_free_mock_check_leaves_no_bytecode_beside_the_customer_modules(
        self,
    ) -> None:
        """The documented mock prelude, then the issue's free check on top of it."""
        source = mock_check_entry_point()

        process, bytecode, _ = run_entry_point(source, "mock_check.py", MOCK_MODE)
        self.assertRan(process, MOCK_CHECK_RAN)
        self.assertEqual(
            bytecode,
            set(),
            "the free mock check imported the customer's modules and left "
            "bytecode in their project",
        )

        control, written, _ = run_entry_point(
            source.replace(THE_LINE, SWITCHED_OFF), "mock_check.py", MOCK_MODE
        )
        self.assertRan(control, MOCK_CHECK_RAN)
        self.assertLessEqual(PRESERVED_BYTECODE, written)

    def test_nothing_either_entry_point_imports_writes_bytecode_anywhere(
        self,
    ) -> None:
        """The line comes before every import, not only before the customer's.

        An environment installed without compiled bytecode - `pip install
        --no-compile`, or a `.venv` inside their project - is written to by the
        SDK's own imports if they run first. A redirected cache makes that
        visible for every package: whatever the interpreter writes before the
        entry point starts is the same for an empty file, so anything beyond
        that was written by an import the line should have preceded.
        """
        entry_points = (
            ("run_phase.py", wrapper_entry_point(), BASELINE_PHASE, NOTHING_PLACED),
            ("mock_check.py", mock_check_entry_point(), MOCK_MODE, MOCK_CHECK_RAN),
        )
        _, _, startup = run_entry_point("", "empty.py", {}, pycache_prefix=True)
        for name, source, environment, evidence in entry_points:
            with self.subTest(entry_point=name):
                process, _, written = run_entry_point(
                    source, name, environment, pycache_prefix=True
                )
                self.assertRan(process, evidence)
                self.assertEqual(sorted(written - startup), [])

        # One control, because what it proves is a property of the redirected
        # cache and not of either entry point: switched off, the same prelude
        # has to write the SDK's own bytecode, or an empty result above would
        # read exactly like a guarded run.
        name, source, environment, evidence = entry_points[1]
        control, _, unguarded = run_entry_point(
            source.replace(THE_LINE, SWITCHED_OFF),
            name,
            environment,
            pycache_prefix=True,
        )
        self.assertRan(control, evidence)
        sdk_init = ("traigent", f"__init__.{sys.implementation.cache_tag}.pyc")
        self.assertTrue(
            any(Path(path).parts[-2:] == sdk_init for path in unguarded - startup),
            "the redirected cache saw no SDK import, so this harness cannot "
            "tell a guarded run from one that wrote nothing",
        )


if __name__ == "__main__":
    unittest.main()
