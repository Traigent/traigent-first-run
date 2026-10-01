#!/usr/bin/env python3
"""Generate a thin bridge from a declarative adapter config; never edit the customer's code.

    generate_adapter.py generate --config adapter.json [--project-root DIR] [--run-dir DIR]
    generate_adapter.py suggest [--project-root DIR] [--dataset FILE]

`generate` validates the config against `assets/adapter.schema.json` and the project, then writes
into the run directory (default `<project-root>/traigent-runs`): `adapter_bridge.py` (imports the
customer's agent and evaluator unchanged, by file path), a byte copy of
`assets/first_run_runtime.py` (the one shared runtime that owns spend, timeout, interception and
the offline/holdout guarantees), and `config-space.json` (checked by readiness's own reader).
Output is deterministic: the same config and sources give byte-identical files.

It refuses, before writing anything: a mapping that does not fit a callable's signature, an
evaluator whose source (or a project module it imports) reaches a code or SQL engine, an agent whose
source reaches a transport the cost ledger cannot see (only `openai` and `litellm` are supported),
paths outside the project, and a search space readiness would reject.

`suggest` prints candidate field paths and callables for the assistant to show the user. It writes
nothing and decides nothing: the user approves the mapping, then it goes in the config.

Exit 0 on success, 1 on a refusal (the reasons are printed as JSON), 2 on a usage error.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
RUNTIME_SOURCE = SKILL / "assets" / "first_run_runtime.py"
SCHEMA = SKILL / "assets" / "adapter.schema.json"
BRIDGE_NAME = "adapter_bridge.py"
RUNTIME_NAME = "first_run_runtime.py"
AGENT_TOKENS = {"$input", "$expected", "$output", "$metadata", "$id", "$row"}
EVALUATOR_TOKENS = {"$output", "$expected", "$input", "$metadata"}
SUPPORTED_TRANSPORTS = {"openai", "litellm"}
UNSUPPORTED_TRANSPORTS = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "urllib.request",
    "http.client",
    "socket",
    "websockets",
    "anthropic",
    "boto3",
    "botocore",
    "google.generativeai",
    "google.genai",
    "vertexai",
    "cohere",
    "mistralai",
    "groq",
    "ollama",
    "replicate",
    "together",
    "huggingface_hub",
    "transformers",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "llama_index",
}
MAX_SCANNED_FILES = 25


class Refusal(Exception):
    """Collected reasons; nothing is written when there is one."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def load_sibling(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_first_run_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


# --- config validation ------------------------------------------------------------------------


def check_shape(config: object, problems: list[str]) -> None:
    """The schema file is the contract; this applies its required/unknown/type rules."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def walk(value, node, where: str) -> None:
        if "const" in node:
            if value != node["const"]:
                problems.append(f"{where} must be {node['const']!r}")
            return
        kind = node.get("type")
        types = {
            "object": dict,
            "string": str,
            "array": list,
            "integer": int,
        }
        if kind and (
            not isinstance(value, types[kind])
            or (kind == "integer" and isinstance(value, bool))
        ):
            problems.append(f"{where} must be a JSON {kind}")
            return
        if kind == "integer" and "minimum" in node and value < node["minimum"]:
            problems.append(f"{where} must be at least {node['minimum']}")
        if kind == "array" and "items" in node:
            for index, item in enumerate(value):
                walk(item, node["items"], f"{where}[{index}]")
        if kind != "object" or "properties" not in node:
            return
        for key in node.get("required", ()):
            if key not in value:
                problems.append(f"{where}.{key} is required")
        for key, item in value.items():
            if key not in node["properties"]:
                known = ", ".join(sorted(node["properties"]))
                problems.append(f"{where}.{key} is not a field (fields: {known})")
            else:
                walk(item, node["properties"][key], f"{where}.{key}")

    walk(config, schema, "config")


def split_callable(spec: str, root: Path, role: str, problems: list[str]):
    """(relative file, function name, absolute path) or None, recording why not."""
    file_part, separator, function = spec.partition(":")
    if not separator or not function.isidentifier():
        problems.append(f"{role}.callable must be module:function or path.py:function")
        return None
    relative = (
        file_part if file_part.endswith(".py") else file_part.replace(".", "/") + ".py"
    )
    path = (root / relative).resolve()
    if not path.is_file() and not file_part.endswith(".py"):
        path = (root / file_part.replace(".", "/") / "__init__.py").resolve()
    if not inside(path, root):
        problems.append(
            f"{role}.callable names a file outside the project: {file_part}"
        )
        return None
    if not path.is_file():
        problems.append(f"{role}.callable: no file for {file_part} under the project")
        return None
    return str(path.relative_to(root.resolve())), function, path


def find_function(path: Path, name: str, role: str, problems: list[str]):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError) as error:
        problems.append(f"{role} source {path.name} cannot be parsed: {error}")
        return None, None
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node, tree
    problems.append(f"{role}: {path.name} has no top-level function {name}")
    return None, tree


def check_mapping(
    node, args: dict, allowed: set[str], role: str, problems: list[str]
) -> None:
    signature = node.args
    if signature.posonlyargs:
        problems.append(
            f"{role} takes positional-only parameters; wrap it in a function that does not"
        )
    names = {a.arg for a in signature.args + signature.kwonlyargs}
    for name, token in args.items():
        if isinstance(token, dict):
            if set(token) != {"value"}:
                problems.append(
                    f'{role}.args.{name}: a literal is {{"value": ...}} and nothing else'
                )
            continue
        if not isinstance(token, str) or not token.startswith("$"):
            problems.append(
                f'{role}.args.{name}: {token!r} is not a token (use "$input" or {{"value": ...}})'
            )
        elif token not in allowed and not (
            role == "agent" and token.startswith("$config.")
        ):
            problems.append(
                f"{role}.args.{name}: {token} is not available to the {role}"
            )
        if signature.kwarg is None and name not in names:
            problems.append(f"{role}.args.{name}: {role} has no parameter {name}")
    required = [
        a.arg
        for a in signature.args[: len(signature.args) - len(signature.defaults)]
        + [a for a, d in zip(signature.kwonlyargs, signature.kw_defaults) if d is None]
    ]
    missing = [name for name in required if name not in args]
    if missing:
        problems.append(
            f"{role} requires {', '.join(missing)}, which args does not map"
        )


# --- source scans -----------------------------------------------------------------------------


def local_imports(tree: ast.Module, here: Path, root: Path) -> list[Path]:
    found = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [base] + [f"{base}.{alias.name}".strip(".") for alias in node.names]
            if node.level:
                names = [
                    ("../" * (node.level - 1)) + name.replace(".", "/")
                    for name in names
                ]
        for name in names:
            parts = name.replace(".", "/") if not name.startswith("..") else name
            for base in {here.parent, root}:
                for candidate in (base / f"{parts}.py", base / parts / "__init__.py"):
                    if candidate.is_file() and inside(candidate, root):
                        found.append(candidate.resolve())
    return found


def reachable_sources(start: Path, root: Path) -> list[tuple[Path, ast.Module]]:
    """The file and the project modules it imports, transitively, bounded."""
    seen: dict[Path, ast.Module] = {}
    queue = [start.resolve()]
    while queue and len(seen) < MAX_SCANNED_FILES:
        path = queue.pop(0)
        if path in seen:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
            continue
        seen[path] = tree
        queue.extend(local_imports(tree, path, root))
    return list(seen.items())


def scan_transports(agent_path: Path, root: Path, problems: list[str]) -> None:
    for path, tree in reachable_sources(agent_path, root):
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                modules = [node.module]
            for module in modules:
                parts = module.split(".")
                prefixes = {".".join(parts[: i + 1]) for i in range(len(parts))}
                if prefixes & UNSUPPORTED_TRANSPORTS:
                    problems.append(
                        f"{path.name}:{node.lineno} imports {module}, a transport the cost "
                        "ledger does not see (supported: openai, litellm). Route the call "
                        "through one of them, or use the hand-adapted wrapper"
                    )


def scan_hazards(evaluator_path: Path, root: Path, problems: list[str]) -> None:
    preflight = load_sibling("preflight")
    for path, tree in reachable_sources(evaluator_path, root):
        witnesses = list(preflight.candidate_execution_witnesses(tree)) + list(
            preflight.process_execution_witnesses(tree)
        )
        if witnesses:
            problems.append(
                f"evaluator source {path.name} reaches a code or SQL engine or a process "
                f"({'; '.join(witnesses[:3])}); references/run-safety.md routes that to a "
                "separate containment review, so no bridge is generated"
            )


# --- search space -----------------------------------------------------------------------------


def check_space(config: dict, agent_args: dict, problems: list[str]) -> dict:
    baseline = config["baseline"]
    space, current = baseline["space"], baseline["config"]
    for knob, values in space.items():
        if not isinstance(values, list) or not values:
            problems.append(f"baseline.space.{knob} must be a non-empty list")
        elif any(values[i] == values[j] for i in range(len(values)) for j in range(i)):
            problems.append(f"baseline.space.{knob} repeats a value; each is paid for")
    if set(current) != set(space):
        problems.append("baseline.config and baseline.space must name the same knobs")
    for knob, value in current.items():
        if knob in space and isinstance(space[knob], list) and value not in space[knob]:
            problems.append(f"baseline.config.{knob}={value!r} is not in its space")
    mapped = {
        token[len("$config.") :]
        for token in agent_args.values()
        if isinstance(token, str) and token.startswith("$config.")
    }
    unmapped = sorted(set(space) - mapped)
    if unmapped:
        problems.append(
            f"knob(s) {', '.join(unmapped)} are in the space but no agent argument is "
            "mapped from them, so the agent cannot consume them"
        )
    wired = baseline.get("wired", sorted(mapped & set(space)))
    enhanced = baseline.get("enhanced_space", space)
    for knob, values in space.items():
        if knob in enhanced and isinstance(values, list):
            if any(value not in enhanced[knob] for value in values):
                problems.append(f"enhanced_space.{knob} drops a baseline value")
    document = {"knobs": enhanced, "wired": list(wired)}
    if "max_trials" in baseline:
        document["max_trials"] = baseline["max_trials"]
    return document


def validate_with_readiness(document: dict, problems: list[str]) -> None:
    readiness = load_sibling("readiness")
    try:
        readiness.agent_facts_from_config_space(document)
    except readiness.ConfigSpaceInputError as error:
        problems.append(f"readiness would refuse this space: {error}")


# --- generation -------------------------------------------------------------------------------

BRIDGE = '''#!/usr/bin/env python3
"""Generated by scripts/generate_adapter.py. Do not edit: change the adapter config and regenerate.

config sha256:  {config_hash}
runtime sha256: {runtime_hash}

    python adapter_bridge.py baseline   # the local baseline, under the approved spend ceiling
    python adapter_bridge.py probe      # does each knob change the request? no network, no key
    calibrate_evaluator.py --scorer adapter_bridge.py:score ...

The customer's agent and evaluator are imported unchanged from their own files.
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUN_DIR))

import first_run_runtime as runtime  # a byte copy of assets/first_run_runtime.py

SPEC = json.loads({spec_literal})
BRIDGE = runtime.Bridge(SPEC, RUN_DIR)


def score(*, output, expected, input_data, metadata=None):
    """The calibration contract, delegating to the customer's own evaluator."""
    return BRIDGE.score(
        output=output, expected=expected, input_data=input_data, metadata=metadata
    )


if __name__ == "__main__":
    raise SystemExit(BRIDGE.main(sys.argv[1:]))
'''


def normalized_spec(config: dict, agent, evaluator) -> dict:
    dataset = dict(config["dataset"])
    return {
        "dataset": dataset,
        "agent": {
            "file": agent[0],
            "function": agent[1],
            "args": config["agent"]["args"],
            "output_path": config["agent"].get("output_path"),
            "calls_per_row": config["agent"].get("calls_per_row", 1),
        },
        "evaluator": {
            "file": evaluator[0],
            "function": evaluator[1],
            "args": config["evaluator"]["args"],
            "calls_per_row": config["evaluator"].get("calls_per_row", 0),
        },
        "baseline": {
            "config": config["baseline"]["config"],
            "space": config["baseline"]["space"],
        },
    }


def validate(config: object, root: Path) -> tuple[dict, dict, Path]:
    """Everything that can refuse, before a file is written. Returns spec, space document."""
    problems: list[str] = []
    check_shape(config, problems)
    if problems:
        raise Refusal(problems)
    dataset = config["dataset"]
    for key in ("path", "holdout_path"):
        if key in dataset and not inside(root / dataset[key], root):
            problems.append(f"dataset.{key} is outside the project")
    if not (root / dataset["path"]).is_file():
        problems.append(f"dataset.path {dataset['path']} does not exist")
    resolved = {}
    for role in ("agent", "evaluator"):
        resolved[role] = split_callable(config[role]["callable"], root, role, problems)
    for role, allowed in (("agent", AGENT_TOKENS), ("evaluator", EVALUATOR_TOKENS)):
        if resolved[role]:
            node, _ = find_function(
                resolved[role][2], resolved[role][1], role, problems
            )
            if node is not None:
                check_mapping(node, config[role]["args"], allowed, role, problems)
    if resolved["agent"]:
        scan_transports(resolved["agent"][2], root, problems)
    if resolved["evaluator"]:
        scan_hazards(resolved["evaluator"][2], root, problems)
    document = check_space(config, config["agent"]["args"], problems)
    if not problems:
        validate_with_readiness(document, problems)
    if problems:
        raise Refusal(problems)
    spec = normalized_spec(config, resolved["agent"], resolved["evaluator"])
    return spec, document, root


def render_bridge(spec: dict, config_hash: str, runtime_hash: str) -> str:
    literal = repr(json.dumps(spec, sort_keys=True, ensure_ascii=True))
    return BRIDGE.format(
        config_hash=config_hash, runtime_hash=runtime_hash, spec_literal=literal
    )


def generate(config_path: Path, root: Path, run_dir: Path) -> dict:
    raw = config_path.read_text(encoding="utf-8")
    try:
        config = json.loads(raw)
    except ValueError as error:
        raise Refusal([f"{config_path.name} is not JSON: {error}"]) from error
    spec, document, root = validate(config, root)
    if not inside(run_dir, root):
        raise Refusal(["the run directory must be inside the project"])
    runtime_bytes = RUNTIME_SOURCE.read_bytes()
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    runtime_hash = hashlib.sha256(runtime_bytes).hexdigest()
    bridge = render_bridge(spec, config_hash, runtime_hash)
    preflight = load_sibling("preflight")
    witnesses = list(preflight.candidate_execution_witnesses(ast.parse(bridge))) + list(
        preflight.process_execution_witnesses(ast.parse(bridge))
    )
    if witnesses:
        raise Refusal([f"the generated bridge itself reaches an engine: {witnesses}"])
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / BRIDGE_NAME).write_text(bridge, encoding="utf-8")
    shutil.copyfile(RUNTIME_SOURCE, run_dir / RUNTIME_NAME)
    (run_dir / "config-space.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "bridge": str(run_dir / BRIDGE_NAME),
        "runtime": str(run_dir / RUNTIME_NAME),
        "config_space": str(run_dir / "config-space.json"),
        "config_sha256": config_hash,
        "runtime_sha256": runtime_hash,
        "agent": f"{spec['agent']['file']}:{spec['agent']['function']}",
        "evaluator": f"{spec['evaluator']['file']}:{spec['evaluator']['function']}",
        "next": [
            "python traigent-runs/adapter_bridge.py probe",
            "calibrate_evaluator.py --scorer traigent-runs/adapter_bridge.py:score",
        ],
    }


# --- suggestions (never decisions) ------------------------------------------------------------

INPUT_NAMES = re.compile(r"input|question|prompt|query|text|message|ticket", re.I)
EXPECTED_NAMES = re.compile(
    r"expected|answer|label|target|gold|reference|truth|output", re.I
)
ID_NAMES = re.compile(r"(^|\.)(id|uid|key)$", re.I)
EVALUATOR_NAMES = re.compile(r"score|eval|grade|match|metric|judge|accuracy", re.I)


def leaf_paths(value, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out += leaf_paths(item, f"{prefix}{key}.")
        return out
    return [prefix[:-1]] if prefix else []


def suggest(root: Path, dataset: Path | None) -> dict:
    result: dict = {
        "note": "suggestions only: show them to the user, then write the approved mapping "
        "into the adapter config",
        "dataset": None,
        "functions": [],
    }
    candidates = [dataset] if dataset else sorted(root.glob("*.jsonl"))[:3]
    for path in candidates:
        try:
            first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, ValueError, IndexError):
            continue
        leaves = leaf_paths(first)
        result["dataset"] = {
            "path": str(path.relative_to(root)) if inside(path, root) else str(path),
            "fields": leaves,
            "input_candidates": [p for p in leaves if INPUT_NAMES.search(p)],
            "expected_candidates": [p for p in leaves if EXPECTED_NAMES.search(p)],
            "id_candidates": [p for p in leaves if ID_NAMES.search(p)],
        }
        break
    for path in sorted(root.glob("*.py"))[:20]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result["functions"].append(
                    {
                        "callable": f"{path.stem}:{node.name}",
                        "parameters": [
                            a.arg for a in node.args.args + node.args.kwonlyargs
                        ],
                        "looks_like": (
                            "evaluator"
                            if EVALUATOR_NAMES.search(node.name)
                            else "agent"
                        ),
                    }
                )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate")
    gen.add_argument("--config", type=Path, required=True)
    gen.add_argument("--project-root", type=Path, default=Path.cwd())
    gen.add_argument("--run-dir", type=Path)
    sug = commands.add_parser("suggest")
    sug.add_argument("--project-root", type=Path, default=Path.cwd())
    sug.add_argument("--dataset", type=Path)
    options = parser.parse_args(argv)
    root = options.project_root.resolve()
    if options.command == "suggest":
        print(json.dumps(suggest(root, options.dataset), indent=2))
        return 0
    run_dir = (options.run_dir or root / "traigent-runs").resolve()
    try:
        result = generate(options.config, root, run_dir)
    except Refusal as refusal:
        print(json.dumps({"refused": refusal.reasons}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
