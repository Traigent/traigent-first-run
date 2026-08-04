#!/usr/bin/env python3
"""Subprocess probe for ``tests/test_offline_socket_contract.py`` (traigent-first-run#132).

Not part of the shipped skill package - a test fixture that is exec'd as a child
process by the hermetic offline-socket-contract test. Its job, in order:

1. Install a socket-layer guard *before* importing anything else, so an
   outbound connection is caught even when it would otherwise succeed (the
   acceptance criteria explicitly reject "did the call fail" as the bar - a
   merely *attempted* connection must be visible and fatal to the guarantee).
2. Record ``TRAIGENT_OFFLINE_MODE`` / ``LITELLM_LOCAL_MODEL_COST_MAP`` exactly
   as they read in the environment at this point - i.e. before the first
   ``import litellm`` / ``import traigent`` - so the parent test can assert the
   documented flags were set ahead of import, not merely present somewhere.
3. Import the modules named in ``PROBE_IMPORT_MODULES`` (comma-separated,
   default ``litellm``) and, if requested via ``PROBE_INVOKE=1`` and
   ``litellm`` imported cleanly, run one local ``mock_response`` completion -
   the "invocation" half of the documented local mock path. LiteLLM's own
   ``mock_response`` short-circuit never opens a socket by design, so this
   step exists to prove that under the guard too, not to add coverage over
   step 1's import-time fetch, which is the reported regression's actual
   trigger.
4. Print one JSON object to stdout and exit 0 unconditionally. The guard
   observed LiteLLM catch its own blocked-fetch ``OSError`` internally and
   fall back to its bundled local cost map without raising past ``import
   litellm`` - so exit code is not a reliable signal here. The parent test
   asserts on the recorded ``attempts`` list instead.
"""

from __future__ import annotations

import json
import os
import socket
import sys

ATTEMPTS: list[dict[str, str]] = []


class BlockedNetworkAccess(OSError):
    """Raised in place of any outbound connection attempt made by this probe."""


def _record(operation: str, address: object) -> None:
    ATTEMPTS.append({"operation": operation, "address": repr(address)})


def _blocked_connect(self: socket.socket, address: object) -> None:
    del self
    _record("socket.connect", address)
    raise BlockedNetworkAccess(
        f"outbound connection blocked in offline probe: {address!r}"
    )


def _blocked_connect_ex(self: socket.socket, address: object) -> int:
    del self
    _record("socket.connect_ex", address)
    raise BlockedNetworkAccess(
        f"outbound connection blocked in offline probe: {address!r}"
    )


def _blocked_create_connection(
    address: object, *args: object, **kwargs: object
) -> socket.socket:
    del args, kwargs
    _record("socket.create_connection", address)
    raise BlockedNetworkAccess(
        f"outbound connection blocked in offline probe: {address!r}"
    )


def install_guard() -> None:
    """Block every outbound connection path stdlib-based HTTP clients use.

    ``socket.create_connection`` covers the common high-level entry point
    (used directly by httpx/httpcore's sync transport and by urllib3); the two
    ``socket.socket`` methods cover manual ``socket.socket() ; sock.connect()``
    use and asyncio's selector-based ``sock_connect``, which calls
    ``sock.connect`` directly on a non-blocking socket.

    Out of scope: DNS resolution alone (``socket.getaddrinfo``) is not
    intercepted, so a bug that only performed a lookup without ever calling
    connect would not be caught here. The reported regression, and every
    known outbound path from this import, connects; a lookup-only leak is a
    narrower and less severe class this guard does not claim to cover.
    """
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex
    socket.create_connection = _blocked_create_connection


def main() -> int:
    # Nothing above this line imports anything beyond the stdlib modules
    # already at module scope, and nothing above this line has attempted a
    # connection - the guard is installed before any Traigent/LiteLLM import.
    install_guard()

    flags_before_import = {
        "TRAIGENT_OFFLINE_MODE": os.environ.get("TRAIGENT_OFFLINE_MODE"),
        "LITELLM_LOCAL_MODEL_COST_MAP": os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP"),
    }

    modules_requested = [
        module.strip()
        for module in os.environ.get("PROBE_IMPORT_MODULES", "litellm").split(",")
        if module.strip()
    ]
    imported: list[str] = []
    import_errors: dict[str, str] = {}
    for module_name in modules_requested:
        try:
            __import__(module_name)
        except Exception as error:  # reported in the JSON result, not swallowed
            import_errors[module_name] = f"{type(error).__name__}: {error}"
        else:
            imported.append(module_name)

    invocation: dict[str, str] | None = None
    if os.environ.get("PROBE_INVOKE") == "1" and "litellm" in imported:
        litellm = sys.modules["litellm"]
        try:
            response = litellm.completion(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "offline socket probe"}],
                mock_response="offline mock response",
            )
            invocation = {"content": response.choices[0].message.content}
        except Exception as error:  # reported in the JSON result, not swallowed
            invocation = {"error": f"{type(error).__name__}: {error}"}

    result = {
        "flags_before_import": flags_before_import,
        "imported": imported,
        "import_errors": import_errors,
        "invocation": invocation,
        "attempts": ATTEMPTS,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
