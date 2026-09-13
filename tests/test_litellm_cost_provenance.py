"""Exercise real LiteLLM response normalization before the guide reads cost."""

from __future__ import annotations

import ast
import contextlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_offline_socket_contract import _credential_stripped_environment

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "skills/traigent-first-run/references/sdk-execution.md"


def probe() -> dict:
    sys.path.insert(0, str(ROOT / "tests/fixtures"))
    from offline_socket_probe import ATTEMPTS, install_guard

    install_guard()
    import httpx
    import litellm
    from openai import OpenAI

    functions = {
        node.name: node
        for source in re.findall(r"```python\n(.*?)\n```", GUIDE.read_text(), re.S)
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
    }
    namespace = {
        "math": math,
        "RUN_CALL_COSTS": [],
        "RUN_SPEND_USD": [],
        "UNTRACKED_CALL_COST_USD": 0.05,
    }
    exec(  # noqa: S102
        compile(
            ast.Module(
                body=[
                    functions["provider_reported_cost"],
                    functions["record_call_spend"],
                ],
                type_ignores=[],
            ),
            "<guide-cost-provenance>",
            "exec",
        ),
        namespace,
    )
    dummy_key = "synthetic-not-a-real-key"
    positive_usage = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    cases = [
        ("absent", {}, {}, "gpt-4o-mini"),
        ("null", {"usage": None}, {}, "gpt-4o-mini"),
        ("usage-cost", {"usage": {"cost": 0.125}}, {}, "gpt-4o-mini"),
        ("usage-zero", {"usage": {"cost": 0.0}}, {}, "gpt-4o-mini"),
        ("header-cost", {}, {"x-litellm-response-cost": "0.125"}, "gpt-4o-mini"),
        ("header-zero", {}, {"x-litellm-response-cost": "0"}, "gpt-4o-mini"),
        ("priced-usage", {"usage": positive_usage}, {}, "gpt-4o-mini"),
        ("unpriced-usage", {"usage": positive_usage}, {}, "synthetic-unpriced"),
    ]
    result = {"litellm_version": importlib.metadata.version("litellm"), "cases": {}}
    for name, extra, headers, model in cases:
        payload = {
            "id": "synthetic-completion",
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "synthetic answer"},
                    "finish_reason": "stop",
                }
            ],
            **extra,
        }
        requests = []

        def transport(request):
            requests.append(request.url.path)
            return httpx.Response(200, json=payload, headers=headers, request=request)

        # The public provider client and LiteLLM parser execute normally. Only
        # HTTP transport is replaced, so normalized usage/cost is not a fixture.
        with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
            client = OpenAI(
                api_key=dummy_key,
                base_url="https://synthetic.invalid/v1",
                http_client=http_client,
                max_retries=0,
            )
            response = litellm.completion(
                model=f"openai/{model}",
                messages=[{"role": "user", "content": "synthetic question"}],
                client=client,
                api_key=dummy_key,
                max_retries=0,
            )
        cost = namespace["provider_reported_cost"](response)
        namespace["record_call_spend"](cost)
        result["cases"][name] = {
            "wire_usage": payload.get("usage"),
            "wire_cost_header": headers.get("x-litellm-response-cost"),
            "normalized_usage": response.usage.model_dump(),
            "hidden_cost": response._hidden_params.get("response_cost"),
            "guide_cost": cost,
            "budget_debit": namespace["RUN_SPEND_USD"][-1],
            "recorded_cost": namespace["RUN_CALL_COSTS"][-1],
            "requests": requests,
        }
    result["network_attempts"] = ATTEMPTS
    return result


class LiteLLMCostProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if importlib.util.find_spec("litellm") is None:
            message = (
                "Install assets/requirements-first-run.txt for LiteLLM provenance tests"
            )
            if os.environ.get("CI"):
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        environment = _credential_stripped_environment(
            {"LITELLM_LOCAL_MODEL_COST_MAP": "true", "TRAIGENT_OFFLINE_MODE": "true"}
        )
        with tempfile.TemporaryDirectory() as directory:
            finished = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--probe"],
                cwd=directory,
                env=environment,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        if finished.returncode:
            raise AssertionError(f"{finished.stdout}\n{finished.stderr}")
        cls.result = json.loads(finished.stdout)

    def test_actual_parser_synthesized_zero_stays_unknown_and_debits_allowance(self):
        for name in ("absent", "null"):
            with self.subTest(case=name):
                case = self.result["cases"][name]
                self.assertEqual(case["normalized_usage"]["total_tokens"], 0)
                self.assertEqual(case["hidden_cost"], 0.0)
                self.assertIsNone(case["guide_cost"])
                self.assertIsNone(case["recorded_cost"])
                self.assertEqual(case["budget_debit"], 0.05)

    def test_explicit_positive_and_zero_cost_survive_absent_tokens(self):
        for name, expected in (
            ("usage-cost", 0.125),
            ("usage-zero", 0.0),
            ("header-cost", 0.125),
            ("header-zero", 0.0),
        ):
            with self.subTest(case=name):
                case = self.result["cases"][name]
                self.assertEqual(case["normalized_usage"]["total_tokens"], 0)
                self.assertEqual(case["guide_cost"], expected)
                self.assertEqual(case["recorded_cost"], expected)
                self.assertEqual(case["budget_debit"], expected)
        self.assertEqual(self.result["cases"]["usage-cost"]["hidden_cost"], 0.0)

    def test_priced_usage_survives_but_unknown_model_does_not_become_free(self):
        priced = self.result["cases"]["priced-usage"]
        self.assertGreater(priced["guide_cost"], 0)
        self.assertEqual(priced["guide_cost"], priced["hidden_cost"])
        unpriced = self.result["cases"]["unpriced-usage"]
        self.assertEqual(unpriced["normalized_usage"]["total_tokens"], 3)
        self.assertIsNone(unpriced["hidden_cost"])
        self.assertIsNone(unpriced["guide_cost"])
        self.assertEqual(unpriced["budget_debit"], 0.05)

    def test_probe_uses_the_pinned_parser_and_never_opens_a_network_connection(self):
        requirements = (
            ROOT / "skills/traigent-first-run/assets/requirements-first-run.txt"
        ).read_text()
        pinned = re.search(r"^litellm==([^\s;]+)", requirements, re.M)
        self.assertIsNotNone(pinned)
        self.assertEqual(self.result["litellm_version"], pinned.group(1))
        self.assertEqual(self.result["network_attempts"], [])
        for case in self.result["cases"].values():
            self.assertEqual(case["requests"], ["/v1/chat/completions"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            record = probe()
        record["captured_stdout"] = stdout.getvalue()
        print(json.dumps(record))
    else:
        unittest.main()
