#!/usr/bin/env python3
"""Traigent first-run preflight — every environment check from GUIDE.md, in one
free command.

Run this instead of improvising the checks by hand. It verifies, at zero LLM
cost, everything the guide otherwise asks the assistant to derive ad hoc:

  C1  python-version    Python 3.11-3.13 (GUIDE Step 1)
  C2  sdk-version       traigent installed, >= 0.21, not the 0.0.1 pip stub (Step 2);
                        warns if `tenacity` is absent (LiteLLM num_retries dies
                        without it and the failed call scores 0 - SDK#1824)
  C3  key-presence      vendor keys in .env with the blank-or-comment-means-absent
                        rule; TRAIGENT_API_KEY format sanity (Step 3)
  C4  model-liveness    each --models id exists: openrouter/* via the keyless
                        public list; openai/anthropic/gemini/mistral via
                        `traigent models --check`; cohere/HF are not CLI-checkable
                        and bedrock needs a region+creds, so all report SKIP (Step 9)
  C5  model-pricing     each --models id has a LiteLLM price entry - unpriced
                        models abort the cost gate or report $0 cost (Step 9)
  C6  cost-cap          TRAIGENT_RUN_COST_LIMIT / TRAIGENT_COST_APPROVED /
                        TRAIGENT_BACKEND_URL sanity (Steps 3d, 9)
  C7  dataset-shape     JSONL rows with input+output; size; extra-field notes
                        (Step 5)
  C8  dataset-binding   dict-input keys match the decorated function's
                        parameters - catches the "field left at top level
                        silently stays at its default" trap (Steps 5/6)
  C9  scorer-sanity     the metric rewards a known-good output (>= 0.9) and
                        penalizes a known-bad one (<= 0.1); signature checks
                        (Step 8's evaluator sanity gate)
  C10 openrouter-credit when OPENROUTER_API_KEY is set (and not --offline), an
                        authenticated GET of the account key-info endpoint to
                        catch the funded-credit / HTTP 402 trap - a valid key
                        with $0 credit passes C3-C9 then 402s mid-run (Step 9)

Zero paid LLM calls by construction: the only network I/O is (1) a keyless GET
of the public OpenRouter model list, (2) `traigent models --json` (model
listing, never a completion), and (3) - only when OPENROUTER_API_KEY is present
- an authenticated GET of OpenRouter's key-info endpoint (account balance, not a
completion). With --offline all of these are skipped.

Dependencies: stdlib + litellm + python-dotenv - both already in traigent's
own dependency closure; the script adds nothing new.

Examples:
  python templates/preflight.py                          # env-only checks
  python templates/preflight.py --env .env --models openrouter/openai/gpt-4o
  python templates/preflight.py --dataset traigent-runs/eval.jsonl \
      --agent my_wrapper.py:my_agent \
      --scorer my_wrapper.py:accuracy_metric \
      --good "SELECT 1" --bad "garbage" --expected "SELECT 1"

Exit codes: 0 = no FAIL (with --strict: also no WARN); 1 = at least one FAIL;
2 = usage error.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"  # account balance, not a completion

# Providers actually registered in `traigent models` (SDK 0.20.0); everything
# else is not pre-validated by the CLI and gets a SKIP with manual guidance.
CLI_CHECKABLE = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "mistral": "mistral",
}

VENDOR_KEYS = [
    ("OpenRouter", ["OPENROUTER_API_KEY"]),
    ("OpenAI", ["OPENAI_API_KEY"]),
    ("Anthropic", ["ANTHROPIC_API_KEY"]),
    ("Google (Gemini)", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),  # one slot, two names
    ("Mistral", ["MISTRAL_API_KEY"]),
    ("Cohere", ["COHERE_API_KEY"]),
    ("HuggingFace", ["HF_TOKEN"]),
]
BEDROCK_KEYS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]


@dataclass
class Result:
    check: str
    status: str
    detail: str


RESULTS: list[Result] = []


def emit(check: str, status: str, detail: str) -> None:
    RESULTS.append(Result(check, status, detail))


def key_present(value: str | None) -> bool:
    """GUIDE Step 3c: blank values and leftover '# hint' text count as absent
    (python-dotenv reads a value-side comment verbatim as the key)."""
    if value is None:
        return False
    v = value.strip()
    return bool(v) and not v.startswith("#")


def read_env(env_path: Path) -> tuple[dict[str, str | None], str]:
    """Merge .env (if present) with os.environ, without mutating os.environ."""
    values: dict[str, str | None] = {}
    source = "os.environ only"
    if env_path.exists():
        try:
            from dotenv import dotenv_values  # dep of litellm, no new install

            values.update(dotenv_values(env_path))
            source = f"{env_path} + os.environ"
        except ImportError:
            emit(
                "env-file",
                WARN,
                "python-dotenv is not importable - reading os.environ only "
                "(it ships with litellm; is the right venv active?)",
            )
    else:
        emit(
            "env-file",
            WARN,
            f"{env_path} not found - reading os.environ only (GUIDE Step 3 "
            "creates it from .env.example)",
        )
    for k, v in os.environ.items():
        values.setdefault(k, v)
    return values, source


# --------------------------------------------------------------------------- C1
def check_python() -> None:
    v = sys.version_info
    if (3, 11) <= (v.major, v.minor) < (3, 14):
        emit("python-version", PASS, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        emit(
            "python-version",
            FAIL,
            f"Python {v.major}.{v.minor} is outside the supported 3.11-3.13 "
            "range - recreate the venv: python3.13 -m venv --clear .venv "
            "(GUIDE Steps 1-2).",
        )


# --------------------------------------------------------------------------- C2
def check_sdk() -> None:
    try:
        from importlib.metadata import version

        ver = version("traigent")
    except Exception:
        emit(
            "sdk-version",
            FAIL,
            f"traigent is not installed in {sys.executable} - "
            'pip install "traigent[recommended]>=0.21".',
        )
        return
    parts = tuple(int(p) for p in re.findall(r"\d+", ver)[:3]) or (0,)
    if ver == "0.0.1" or parts < (0, 21):
        emit(
            "sdk-version",
            FAIL,
            f"traigent {ver} is below 0.21"
            + (
                " (the ancient 0.0.1 placeholder pip resolves on unsupported "
                "Pythons)"
                if ver == "0.0.1"
                else ""
            )
            + ' - recreate the venv on Python 3.11-3.13, then pip install '
            '"traigent[recommended]>=0.21" (GUIDE Step 2).',
        )
        return
    emit("sdk-version", PASS, f"traigent {ver}")
    if shutil.which("traigent") is None:
        emit(
            "sdk-cli",
            WARN,
            "the `traigent` console script is not on PATH although the module "
            "imports - activate the venv so CLI checks (C4) can run.",
        )
    if importlib.util.find_spec("tenacity") is None:
        emit(
            "sdk-retry-dep",
            WARN,
            "`tenacity` is not installed - it is not in traigent's dependency "
            "closure, and agent code that passes num_retries to LiteLLM dies with "
            "ModuleNotFoundError instead of retrying, so the failed call silently "
            "scores 0 (Traigent/Traigent#1824). If the user's agent retries via "
            "LiteLLM: pip install tenacity.",
        )


# --------------------------------------------------------------------------- C3
def check_keys(env: dict[str, str | None]) -> None:
    present: list[str] = []
    for name, vars_ in VENDOR_KEYS:
        if any(key_present(env.get(k)) for k in vars_):
            present.append(name)
    bedrock_found = [k for k in BEDROCK_KEYS if key_present(env.get(k))]
    if len(bedrock_found) == len(BEDROCK_KEYS):
        present.append("Bedrock")
    elif bedrock_found:
        emit(
            "key-presence",
            WARN,
            f"partial Bedrock credentials: {', '.join(bedrock_found)} set but "
            f"{', '.join(k for k in BEDROCK_KEYS if k not in bedrock_found)} "
            "missing - Bedrock needs all three (GUIDE Step 3c table).",
        )

    if not present:
        emit(
            "key-presence",
            FAIL,
            "no LLM vendor key found (blank values and '# hint' values count "
            "as absent) - add one; OpenRouter is the recommended default "
            "(GUIDE Step 3c).",
        )
    elif len(present) == 1:
        emit("key-presence", PASS, f"1 vendor configured: {present[0]}")
    else:
        emit(
            "key-presence",
            WARN,
            f"multiple vendors configured ({', '.join(present)}) - GUIDE Step "
            "3c: ask the user which one drives this run.",
        )

    tk = env.get("TRAIGENT_API_KEY")
    if not key_present(tk):
        emit("traigent-key", PASS, "TRAIGENT_API_KEY not set - fine until Step 9")
    elif tk.strip().startswith("tg_"):
        emit(
            "traigent-key",
            WARN,
            "TRAIGENT_API_KEY is a tg_ token - that is a local SDK dev/mock "
            "token, never issued by the portal; portal keys start with uk_ "
            "(.env.example).",
        )
    elif not (tk.strip().startswith("uk_") and len(tk.strip()) == 46):
        emit(
            "traigent-key",
            WARN,
            "TRAIGENT_API_KEY does not look like a portal full-access key "
            "(uk_..., 46 chars) - double-check the paste (.env.example).",
        )
    else:
        emit("traigent-key", PASS, "TRAIGENT_API_KEY looks like a portal key")

    ork = env.get("OPENROUTER_API_KEY")
    if key_present(ork) and not ork.strip().startswith("sk-or-"):
        emit(
            "openrouter-key",
            WARN,
            "OPENROUTER_API_KEY does not start with sk-or- - double-check the "
            "paste (.env.example documents the sk-or-v1-... format).",
        )


# --------------------------------------------------------------------------- C4
def check_liveness(models: list[str], offline: bool) -> None:
    openrouter_ids: set[str] | None = None
    for mid in models:
        if mid.startswith("openrouter/"):
            if offline:
                emit(f"liveness:{mid}", SKIP, "--offline: network check skipped")
                continue
            if openrouter_ids is None:
                try:
                    with urllib.request.urlopen(
                        OPENROUTER_MODELS_URL, timeout=10
                    ) as r:
                        openrouter_ids = {
                            m["id"] for m in json.load(r)["data"]
                        }
                except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
                    emit(
                        f"liveness:{mid}",
                        WARN,
                        f"could not fetch the OpenRouter model list ({e}) - "
                        "inconclusive, not a failure.",
                    )
                    continue
            slug = mid.removeprefix("openrouter/")
            if slug in openrouter_ids:
                emit(f"liveness:{mid}", PASS, "live on openrouter.ai")
            else:
                emit(
                    f"liveness:{mid}",
                    FAIL,
                    f"'{slug}' is not in the live list at {OPENROUTER_MODELS_URL}"
                    " - delisted or renamed; a dead id wastes the run on a 404 "
                    "(GUIDE Step 9).",
                )
            continue

        provider = None
        if mid.startswith(("gpt-", "o1", "o3", "o4")):
            provider = "openai"
        elif mid.startswith("claude-"):
            provider = "anthropic"
        elif mid.startswith("gemini-"):
            provider = "gemini"
        elif mid.startswith("mistral-"):
            provider = "mistral"

        if provider is None:
            emit(
                f"liveness:{mid}",
                SKIP,
                "not pre-validated here (cohere/HF/azure and unrecognized "
                "prefixes; bedrock is CLI-checkable but needs a region+AWS "
                "creds) - verify the id manually against the vendor's docs; "
                "the pricing check (C5) still applies.",
            )
            continue
        if offline:
            emit(f"liveness:{mid}", SKIP, "--offline: CLI check skipped")
            continue
        if shutil.which("traigent") is None:
            emit(
                f"liveness:{mid}",
                WARN,
                "`traigent` CLI not on PATH - cannot run "
                f"`traigent models --provider {provider} --check {mid}`.",
            )
            continue
        try:
            proc = subprocess.run(
                [
                    "traigent",
                    "models",
                    "--provider",
                    provider,
                    "--check",
                    mid,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(proc.stdout or "{}")
            valid = payload.get("valid")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            emit(
                f"liveness:{mid}",
                WARN,
                f"`traigent models` check inconclusive ({e}).",
            )
            continue
        if valid:
            emit(f"liveness:{mid}", PASS, f"known {provider} model")
        else:
            # WARN, not FAIL: the SDK's built-in model list can lag the vendor
            # (e.g. it may end before the newest model family), so "not known"
            # is a prompt to double-check, not proof the id is dead.
            emit(
                f"liveness:{mid}",
                WARN,
                f"'{mid}' is not in `traigent models`' known {provider} list - "
                "the SDK's list may lag the vendor; verify the id against the "
                "vendor's docs before running (GUIDE Step 9).",
            )


# --------------------------------------------------------------------------- C5
def check_pricing(models: list[str], offline: bool) -> None:
    if not models:
        return
    if offline:
        # keep litellm from fetching its remote price map at import time
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    try:
        import litellm
    except ImportError:
        emit(
            "pricing",
            WARN,
            "litellm is not importable - cannot check price entries (it ships "
            "with traigent; is the right venv active?)",
        )
        return
    for mid in models:
        try:
            litellm.cost_per_token(
                model=mid, prompt_tokens=1000, completion_tokens=1000
            )
        except Exception:
            emit(
                f"pricing:{mid}",
                FAIL,
                f"'{mid}' has no LiteLLM price entry - the pre-run gate can "
                "abort on an unpriced model, and if it proceeds cost reports "
                "$0 (GUIDE Step 9). Swap for a priced equivalent, set "
                "TRAIGENT_CUSTOM_MODEL_PRICING_*, or flag it to "
                "support@traigent.ai.",
            )
        else:
            emit(f"pricing:{mid}", PASS, "LiteLLM has a price entry")


# --------------------------------------------------------------------------- C6
def check_cost_cap(env: dict[str, str | None]) -> None:
    raw = env.get("TRAIGENT_RUN_COST_LIMIT")
    if raw is None or not raw.strip():
        emit(
            "cost-cap",
            WARN,
            "TRAIGENT_RUN_COST_LIMIT not set - SDK default is 2.00; the "
            "first-run template ships 5.00 (GUIDE Step 3d).",
        )
    else:
        try:
            cap = float(raw)
        except ValueError:
            emit(
                "cost-cap",
                FAIL,
                f"TRAIGENT_RUN_COST_LIMIT='{raw}' is not a positive number - "
                "set e.g. 5.00.",
            )
            cap = None
        if cap is not None and cap <= 0:
            emit(
                "cost-cap",
                FAIL,
                f"TRAIGENT_RUN_COST_LIMIT={cap} is not positive - set e.g. 5.00.",
            )
        elif cap is not None and cap < 1.0:
            emit(
                "cost-cap",
                WARN,
                f"TRAIGENT_RUN_COST_LIMIT={cap} is very low - a cap below the "
                "per-trial estimate yields 0 trials with "
                "stop_reason=='cost_limit' (no exception), and a stray low "
                "exported value even cancels keyless quickstart runs "
                "(GUIDE Steps 3d, 9).",
            )
        elif cap is not None:
            emit("cost-cap", PASS, f"TRAIGENT_RUN_COST_LIMIT={cap}")
    shell_v, file_v = os.environ.get("TRAIGENT_RUN_COST_LIMIT"), raw
    if shell_v is not None and file_v is not None and shell_v != file_v:
        emit(
            "cost-cap",
            WARN,
            f"shell exports TRAIGENT_RUN_COST_LIMIT={shell_v} but .env says "
            f"{file_v} - litellm auto-loads a CWD .env, so the effective value "
            "may surprise you (GUIDE Step 3, 'Why explicit').",
        )
    approved = env.get("TRAIGENT_COST_APPROVED")
    if key_present(approved) and approved.strip().lower() in ("1", "true", "yes"):
        emit(
            "cost-approved",
            WARN,
            "TRAIGENT_COST_APPROVED is pre-set - the paid-run approval gate is "
            "silently skipped; unset it until the user says yes (GUIDE Steps "
            "3d, 9).",
        )
    backend = env.get("TRAIGENT_BACKEND_URL")
    if key_present(backend):
        emit(
            "backend-url",
            WARN,
            f"TRAIGENT_BACKEND_URL is pinned to {backend.strip()} - a "
            "first-run user normally leaves it unset (production cloud); "
            "intended? (GUIDE Step 3b).",
        )


# --------------------------------------------------------------------------- C7
def check_dataset(path: Path) -> list[dict] | None:
    if not path.exists():
        emit("dataset-shape", FAIL, f"{path} does not exist.")
        return None
    rows: list[dict] = []
    input_types: set[str] = set()
    extra_keys: set[str] = set()
    with path.open() as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                emit(
                    "dataset-shape",
                    FAIL,
                    f"line {n} is not valid JSON - dataset must be JSONL "
                    "(GUIDE Step 5).",
                )
                return None
            for field in ("input", "output"):
                if field not in row:
                    emit(
                        "dataset-shape",
                        FAIL,
                        f"line {n} lacks '{field}' - dataset must be JSONL "
                        "with input and output per row (GUIDE Step 5).",
                    )
                    return None
            rows.append(row)
            input_types.add(type(row["input"]).__name__)
            extra_keys.update(k for k in row if k not in ("input", "output"))
    if len(rows) < 10:
        emit(
            "dataset-shape",
            WARN,
            f"{len(rows)} examples is too few to be meaningful "
            "(GUIDE Step 5 recommends 10-20+).",
        )
    if len(input_types) > 1:
        emit(
            "dataset-shape",
            WARN,
            f"mixed input types across rows ({', '.join(sorted(input_types))})"
            " - keep one shape.",
        )
    detail = f"{len(rows)} rows"
    if extra_keys:
        detail += (
            f"; extra top-level keys {sorted(extra_keys)} are routed to the "
            "scorer's metadata (NOT to the function - see C8)"
        )
    emit("dataset-shape", PASS, detail)
    return rows


# --------------------------------------------------------------------------- C8
def load_symbol(spec_str: str, what: str):
    """Import FILE.py:NAME. Sets TRAIGENT_OFFLINE_MODE first so importing a
    decorated module cannot reach the backend (module top level must not make
    LLM calls)."""
    os.environ.setdefault("TRAIGENT_OFFLINE_MODE", "true")
    file_part, _, name = spec_str.partition(":")
    if not name:
        emit(what, FAIL, f"--{what} must be FILE.py:FUNCTION, got '{spec_str}'.")
        return None
    p = Path(file_part)
    if not p.exists():
        emit(what, FAIL, f"{p} does not exist.")
        return None
    sys.path.insert(0, str(p.resolve().parent))
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        emit(what, FAIL, f"importing {p} raised {type(e).__name__}: {e}")
        return None
    obj = getattr(mod, name, None)
    if obj is None:
        emit(what, FAIL, f"{p} has no attribute '{name}'.")
    return obj


def real_signature(func) -> inspect.Signature | None:
    """Unwrap @traigent.optimize objects down to the original function."""
    for attr in ("__wrapped__", "func", "original_function", "_func"):
        inner = getattr(func, attr, None)
        if inner is not None and callable(inner):
            func = inner
            break
    try:
        return inspect.signature(func)
    except (TypeError, ValueError):
        return None


def check_binding(rows: list[dict], agent_spec: str) -> None:
    func = load_symbol(agent_spec, "dataset-binding")
    if func is None:
        return
    sig = real_signature(func)
    if sig is None:
        emit(
            "dataset-binding",
            WARN,
            "could not introspect the function signature - verify manually "
            "that every input key matches a parameter.",
        )
        return
    params = sig.parameters
    has_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    named = {
        n: p
        for n, p in params.items()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    dict_rows = [r for r in rows if isinstance(r["input"], dict)]
    if not dict_rows:
        emit(
            "dataset-binding",
            PASS,
            "input is a plain value (bound to the first parameter) - no "
            "dict-binding to check.",
        )
        return
    input_keys = set().union(*(r["input"].keys() for r in dict_rows))
    top_keys = set().union(
        *({k for k in r if k not in ("input", "output")} for r in dict_rows)
    )
    problems = False
    # The SDK expands dict inputs as func(**input) (traigent/evaluators/
    # base.py:1574-1577, decision at :1253-1290) - only keys INSIDE input
    # reach parameters.
    for k in sorted(input_keys):
        if k not in named and not has_kwargs:
            problems = True
            emit(
                "dataset-binding",
                FAIL,
                f"input key '{k}' matches no parameter of the agent function - "
                "every trial raises TypeError (unexpected keyword argument).",
            )
    for n, p in named.items():
        if p.default is inspect.Parameter.empty and n not in input_keys:
            problems = True
            emit(
                "dataset-binding",
                FAIL,
                f"parameter '{n}' has no default and is absent from input - "
                "every trial raises TypeError (missing argument).",
            )
        elif p.default is not inspect.Parameter.empty and n not in input_keys:
            if n in top_keys:
                problems = True
                emit(
                    "dataset-binding",
                    FAIL,
                    f"dataset field '{n}' is top-level only; Traigent binds "
                    "arguments from INSIDE input, so "
                    f"'{n}' silently stays at its default ({p.default!r}) "
                    "every trial - copy it into input (keep the top-level "
                    "copy for metric metadata).",
                )
            else:
                emit(
                    "dataset-binding",
                    WARN,
                    f"parameter '{n}' stays at its default ({p.default!r}) "
                    "for every row - intended?",
                )
    if not problems:
        emit(
            "dataset-binding",
            PASS,
            f"all {len(input_keys)} input keys bind to parameters "
            f"({', '.join(sorted(input_keys))}).",
        )


# --------------------------------------------------------------------------- C9
def literal_or_file(v: str | None):
    if v is None:
        return None
    if v.startswith("@"):
        return json.loads(Path(v[1:]).read_text())
    return v


def check_scorer(scorer_spec: str, good, bad, expected, metadata) -> None:
    fn = load_symbol(scorer_spec, "scorer-sanity")
    if fn is None:
        return
    if inspect.iscoroutinefunction(fn):
        emit(
            "scorer-sanity",
            FAIL,
            "the scorer is async - scorers are not awaited, so it returns a "
            "coroutine and reads as a failed metric (GUIDE Step 5).",
        )
        return
    sig = real_signature(fn)
    # Model the PRODUCTION metric binder — LocalEvaluator._build_metric_keyword_arguments
    # / _invoke_metric_function (traigent/evaluators/local.py:630-755) — NOT the legacy
    # SimpleScoringEvaluator._build_metric_kwargs, which is instantiated nowhere in
    # production and recognizes a narrower set. Modelling that legacy set here would
    # false-FAIL a perfectly valid DeepEval-style scorer. The real binder (a) accepts a
    # BROAD alias set including actual_output/expected_output/ground_truth, and (b) falls
    # back to POSITIONAL calls (output, expected, llm_payload) / (output, expected) /
    # (output,), so a scorer fails to bind only when NONE of those call forms fit.
    _OUTPUT_NAMES = {"actual", "actual_output", "output", "prediction", "predicted", "result"}
    _EXPECTED_NAMES = {"expected", "expected_output", "ground_truth", "reference", "target"}
    _LLM_NAMES = {"llm_metrics", "metrics"}

    def _bind_like_production(signature, out, exp):
        """Return the first (args, kwargs) LocalEvaluator would use to call the scorer,
        or None if no call form binds (i.e. every trial would raise TypeError)."""
        params = list(signature.parameters.values())
        recognized = {
            "example": None,
            "input_data": None,
            "metadata": metadata if metadata is not None else {},
            "config": {},
            "example_index": 0,
        }
        for n in _OUTPUT_NAMES:
            recognized[n] = out
        for n in _EXPECTED_NAMES:
            recognized[n] = exp
        for n in _LLM_NAMES:
            recognized[n] = {}
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params
        )
        kwargs = {}
        for p in params:
            if p.kind in (
                inspect.Parameter.VAR_KEYWORD,
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.VAR_POSITIONAL,
            ):
                continue
            if p.name in recognized:
                kwargs[p.name] = recognized[p.name]
        if accepts_kwargs:
            kwargs.setdefault("output", out)
            kwargs.setdefault("expected", exp)
            kwargs.setdefault("llm_metrics", {})
        positional = (out, exp, {})  # (output, expected, llm_payload)
        candidates: list[tuple[tuple, dict]] = []
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
            candidates.append((positional, {}))
        if kwargs:
            candidates.append(((), kwargs))
        candidates += [
            (positional, {}),
            (positional[:2], {}),
            (positional[:1], {}),
            ((), {}),
        ]
        for args, kw in candidates:
            try:
                signature.bind(*args, **kw)
            except TypeError:
                continue
            return args, kw
        return None

    if sig is not None and _bind_like_production(sig, "", "") is None:
        emit(
            "scorer-sanity",
            FAIL,
            "no call form of Traigent's production metric binder "
            "(traigent/evaluators/local.py) fits this scorer's signature, so every "
            "trial raises TypeError. It binds recognized keyword names "
            "(output/actual/actual_output/prediction/predicted/result, "
            "expected/expected_output/ground_truth/reference/target, "
            "llm_metrics/metrics, plus example/input_data/metadata/config/"
            "example_index) and, failing that, tries positional "
            "(output, expected, llm_metrics). A scorer with >3 required positional "
            "params, or a required keyword-only param outside those names with no "
            "**kwargs, can't be called - rename to a recognized name or add **kwargs.",
        )
        return
    if good is None or bad is None or expected is None:
        emit(
            "scorer-sanity",
            SKIP,
            "signature checked; pass --good/--bad/--expected to run the "
            "known-good/known-bad probes (GUIDE Step 8's sanity gate).",
        )
        return

    def call(output):
        # Invoke exactly as LocalEvaluator would: the first binding call form.
        bound = _bind_like_production(sig, output, expected) if sig else None
        if bound is None:
            return fn(output, expected)
        args, kw = bound
        return fn(*args, **kw)

    for label, value, ok in (
        ("known-good", good, lambda s: s >= 0.9),
        ("known-bad", bad, lambda s: s <= 0.1),
    ):
        try:
            score = float(call(value))
        except Exception as e:
            emit(
                "scorer-sanity",
                FAIL,
                f"the {label} probe raised {type(e).__name__}: {e} - at run "
                "time an informational metric that raises is warning-logged "
                "and coerced to 0.0 (indistinguishable from a wrong answer), "
                "and an objective metric that raises fails the trial closed; "
                "fix before spending (GUIDE Steps 5, 8).",
            )
            return
        if ok(score):
            emit(f"scorer-sanity:{label}", PASS, f"scored {score}")
        else:
            bound = ">= 0.9" if label == "known-good" else "<= 0.1"
            emit(
                f"scorer-sanity:{label}",
                FAIL,
                f"{label} output scored {score} (need {bound}) - the metric "
                f"cannot {'reward a right' if label == 'known-good' else 'penalize a wrong'}"
                " answer; fix before running anything paid (GUIDE Step 8's "
                "sanity gate).",
            )


# ---------------------------------------------------------------------------
# --------------------------------------------------------------------------- C10
def check_openrouter_credit(env: dict[str, str | None], offline: bool) -> None:
    """The funded-credit / HTTP 402 trap: C3 checks the key's *shape*, C4 uses the
    keyless public list, C5 prices locally - nothing verifies the account can
    actually pay. A syntactically valid key with $0 credit passes every other check
    and then 402s on the first paid call, *after* TRAIGENT_COST_APPROVED is set and
    the run has started. This is the only authenticated request the preflight makes,
    and it is a balance read - never a completion, so still zero LLM cost."""
    key = env.get("OPENROUTER_API_KEY")
    if not key_present(key):
        # No OpenRouter key -> nothing to verify here (the vendor may be OpenAI/etc.,
        # or the key is deferred). C3 already reports presence.
        emit("openrouter-credit", SKIP, "no OPENROUTER_API_KEY in .env - skipped.")
        return
    if offline:
        emit("openrouter-credit", SKIP, "--offline: credit check skipped.")
        return
    req = urllib.request.Request(
        OPENROUTER_KEY_URL, headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r).get("data", {})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            emit(
                "openrouter-credit",
                FAIL,
                "OpenRouter rejected the key (HTTP 401) - invalid or revoked; "
                "the run would fail on the first paid call (GUIDE Step 9).",
            )
        elif e.code == 402:
            emit(
                "openrouter-credit",
                FAIL,
                "OpenRouter reports no funded credit (HTTP 402) - the key is "
                "valid but the account can't pay; every paid call will 402 "
                "*after* the run starts. Add credit at openrouter.ai/credits.",
            )
        else:
            emit(
                "openrouter-credit",
                WARN,
                f"key-info endpoint returned HTTP {e.code} - inconclusive, not a "
                "failure; verify funded credit manually before a paid run.",
            )
        return
    except (urllib.error.URLError, OSError, ValueError) as e:
        emit(
            "openrouter-credit",
            WARN,
            f"could not reach the OpenRouter key-info endpoint ({e}) - "
            "inconclusive, not a failure.",
        )
        return

    remaining = data.get("limit_remaining")
    limit = data.get("limit")
    if remaining is not None and remaining <= 0:
        emit(
            "openrouter-credit",
            FAIL,
            f"OpenRouter credit exhausted (limit_remaining={remaining}) - a paid "
            "run will 402 mid-flight. Add credit at openrouter.ai/credits.",
        )
        return
    if remaining is not None:
        emit(
            "openrouter-credit",
            PASS,
            f"funded: {remaining} credit remaining"
            + (f" of a {limit} limit" if limit is not None else ""),
        )
    else:
        # limit_remaining null == no preset limit (pay-as-you-go); can't prove a
        # positive balance from this field alone, so PASS-with-caveat, not FAIL.
        emit(
            "openrouter-credit",
            PASS,
            "key authenticated; no preset credit limit (pay-as-you-go) - ensure "
            "the account is funded (openrouter.ai/credits) before a paid run.",
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Traigent first-run preflight (free - no LLM calls)."
    )
    ap.add_argument("--env", default=".env", help="path to .env (default ./.env)")
    ap.add_argument(
        "--models", default="", help="comma-separated LiteLLM model ids to check"
    )
    ap.add_argument("--dataset", help="JSONL dataset to shape-check")
    ap.add_argument(
        "--agent",
        help="FILE.py:FUNC - enables the dataset<->signature binding check",
    )
    ap.add_argument("--scorer", help="FILE.py:FUNC - metric to sanity-probe")
    ap.add_argument("--good", help="known-good output (literal or @file.json)")
    ap.add_argument("--bad", help="known-bad output (literal or @file.json)")
    ap.add_argument("--expected", help="expected/gold value (literal or @file.json)")
    ap.add_argument(
        "--metadata", help="metadata JSON for the scorer probes (literal or @file)"
    )
    ap.add_argument(
        "--offline", action="store_true", help="skip all network checks (SKIP)"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--strict", action="store_true", help="exit 1 on WARN as well as FAIL"
    )
    args = ap.parse_args()

    env, source = read_env(Path(args.env))
    emit("env-source", PASS, source)

    check_python()
    check_sdk()
    check_keys(env)
    check_cost_cap(env)
    check_openrouter_credit(env, args.offline)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if models:
        check_liveness(models, args.offline)
        check_pricing(models, args.offline)

    rows = check_dataset(Path(args.dataset)) if args.dataset else None
    if rows and args.agent:
        check_binding(rows, args.agent)
    elif args.agent and not args.dataset:
        emit("dataset-binding", SKIP, "--agent given without --dataset.")

    if args.scorer:
        try:
            md = json.loads(args.metadata) if args.metadata and not args.metadata.startswith("@") else literal_or_file(args.metadata)
        except json.JSONDecodeError:
            md = None
        check_scorer(
            args.scorer,
            literal_or_file(args.good),
            literal_or_file(args.bad),
            literal_or_file(args.expected),
            md,
        )

    if args.json:
        print(json.dumps([r.__dict__ for r in RESULTS], indent=2))
    else:
        w = max(len(r.check) for r in RESULTS)
        for r in RESULTS:
            print(f"{r.check:<{w}}  {r.status:<4}  {r.detail}")
        counts = {s: sum(1 for r in RESULTS if r.status == s) for s in (PASS, WARN, FAIL, SKIP)}
        print(
            f"\n{counts[PASS]} pass, {counts[WARN]} warn, {counts[FAIL]} fail, "
            f"{counts[SKIP]} skipped"
        )

    if any(r.status == FAIL for r in RESULTS):
        return 1
    if args.strict and any(r.status == WARN for r in RESULTS):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
