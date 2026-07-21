"""Telemetry-only socket guard; Docker's network namespace is the enforcement."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


def _deny(operation: str, target: object = None) -> None:
    path = os.environ.get("TRAIGENT_AUDIT_LOG")
    if path:
        with Path(path).open("a") as stream:
            stream.write(
                json.dumps({"operation": operation, "target": repr(target)}) + "\n"
            )
    raise OSError("network access is forbidden in the offline contract harness")


def _connect(self: socket.socket, address: object) -> None:
    del self
    _deny("socket.connect", address)


def _connect_ex(self: socket.socket, address: object) -> int:
    del self
    _deny("socket.connect_ex", address)
    return 1


def _create_connection(
    address: object, *args: object, **kwargs: object
) -> socket.socket:
    del args, kwargs
    _deny("socket.create_connection", address)
    raise AssertionError("unreachable")


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
