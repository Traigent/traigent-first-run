#!/usr/bin/env python3
"""Subprocess probe for ``tests/test_offline_socket_contract.py`` (traigent-first-run#132).

Not part of the shipped skill package - a test fixture that is exec'd as a child
process by the hermetic offline-socket-contract test. Its job, in order:

1. Install a socket-layer guard *before* importing anything else, so an
   outbound event is caught even when it would otherwise succeed (the
   acceptance criteria explicitly reject "did the call fail" as the bar - a
   merely *attempted* connection must be visible and fatal to the guarantee).
   "Outbound" covers name resolution as well as connection: a lookup emits a
   DNS query carrying the hostname, which is the first packet a network
   monitor sees, and used to pass this probe unrecorded (#152).
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
   asserts on the recorded ``attempts`` list instead. ``permitted`` carries the
   guard hits that were *not* traffic (a numeric host, loopback, ``AF_UNIX``)
   so the permissive branch is reviewable rather than invisible; it is
   deliberately a separate key, because ``attempts == []`` is the assertion
   everything else rests on.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import sys

ATTEMPTS: list[dict[str, str]] = []
PERMITTED: list[dict[str, str]] = []

# Names that resolve without leaving the machine on any sane resolver. A
# hostname is what a lookup actually leaks - to the configured resolver, and to
# anything on the path to it - so these are the only ones allowed through by
# name rather than by being an address already.
LOOPBACK_NAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)


class BlockedNetworkAccess(OSError):
    """Raised in place of any outbound connection attempt made by this probe."""


def _record(operation: str, address: object) -> None:
    ATTEMPTS.append({"operation": operation, "address": repr(address)})


def _permit(operation: str, address: object, reason: str) -> None:
    """Record a guard hit that is not outbound traffic, and let it proceed.

    Kept out of ``ATTEMPTS`` deliberately. ``attempts == []`` is the assertion
    the whole module is built on, and a numeric-host ``getaddrinfo`` performs no
    network I/O at all - folding it in would turn every legitimate local lookup
    into a red run and the assertion into something people edit rather than
    trust. They are still reported, because a guard whose permissive branch is
    invisible cannot be reviewed.
    """
    PERMITTED.append(
        {"operation": operation, "address": repr(address), "reason": reason}
    )


def _parsed_address(host: object) -> object | None:
    """The host as an IP address object, or ``None`` when it is not a literal."""
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(host, str):
        return None
    try:
        return ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        return None


def _forward_local_target(host: object) -> str | None:
    """Why this host needs no network to resolve, or ``None`` if it does.

    Three cases resolve locally, and each is a real call shape:

    * ``None`` - ``getaddrinfo(None, port)`` is the wildcard/loopback bind form,
      used by servers and by ``socketpair`` fallbacks; it asks nothing of a
      resolver.
    * an IP literal - the C library parses it and returns; no query is sent.
      This is also how a client that already has an address reaches ``connect``,
      which the connection half of this guard still catches.
    * a loopback name - conventionally answered from ``/etc/hosts``. Allowed by
      name because a test that binds to ``localhost`` must keep working; the
      hostname does not identify a customer or a vendor either way.
    """
    if host is None:
        return "no-host"
    if _parsed_address(host) is not None:
        return "ip-literal"
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return None
    if isinstance(host, str) and host.lower().rstrip(".") in LOOPBACK_NAMES:
        return "loopback-name"
    return None


def _reverse_local_target(address: object) -> str | None:
    """The forward rule inverted, because the address is the *input* here.

    ``getaddrinfo("93.184.216.34", ...)`` sends nothing - the literal is
    already the answer. ``gethostbyaddr`` of the same literal sends a PTR query
    to the resolver, which leaks exactly the address being looked up. So a
    routable literal is permitted forward and blocked in reverse.
    """
    if isinstance(address, tuple) and address:
        address = address[0]
    if address is None:
        return "no-host"
    parsed = _parsed_address(address)
    if parsed is not None:
        return "loopback-address" if parsed.is_loopback else None
    if isinstance(address, str) and address.lower().rstrip(".") in LOOPBACK_NAMES:
        return "loopback-name"
    return None


def _datagram_local_target(address: object) -> str | None:
    """Same rule as ``connect``: only loopback and non-``AF_INET`` are local.

    A datagram target is normally an address already, so the forward rule would
    permit every one of them - which is the whole point of blocking here.
    ``None`` means a connected socket, whose ``connect`` this guard already
    caught, and a non-tuple address is an ``AF_UNIX`` path, which never leaves
    the machine.
    """
    if address is None:
        return "connected-socket"
    if not isinstance(address, tuple):
        return "non-inet"
    if not address:
        return "non-inet"
    parsed = _parsed_address(address[0])
    if parsed is not None:
        return "loopback-address" if parsed.is_loopback else None
    if isinstance(address[0], str) and address[0].lower().rstrip(".") in LOOPBACK_NAMES:
        return "loopback-name"
    return None


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


# Captured before `install_guard` replaces them: a permitted local call is
# delegated to the real implementation, and looking it up through `socket`
# after patching would call the wrapper again.
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_GETNAMEINFO = socket.getnameinfo
_REAL_GETHOSTBYNAME = socket.gethostbyname
_REAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_REAL_GETHOSTBYADDR = socket.gethostbyaddr
_REAL_SENDTO = socket.socket.sendto
_REAL_SENDMSG = socket.socket.sendmsg


def _guarded_resolution(operation: str, host: object, call, *args, **kwargs):
    """Block a name lookup, or let a local one through and say so.

    A lookup is itself an outbound event: the hostname reaches the configured
    resolver, and on a corporate network the DNS query is the first packet a
    monitor sees - before any connection exists to be blocked.
    """
    reason = _forward_local_target(host)
    if reason is None:
        _record(operation, host)
        raise BlockedNetworkAccess(
            f"outbound name resolution blocked in offline probe: {operation}"
            f"({host!r})"
        )
    _permit(operation, host, reason)
    return call(*args, **kwargs)


def _blocked_getaddrinfo(host: object, port: object, *args: object, **kwargs: object):
    return _guarded_resolution(
        "socket.getaddrinfo", host, _REAL_GETADDRINFO, host, port, *args, **kwargs
    )


def _blocked_gethostbyname(hostname: object):
    return _guarded_resolution(
        "socket.gethostbyname", hostname, _REAL_GETHOSTBYNAME, hostname
    )


def _blocked_gethostbyname_ex(hostname: object):
    return _guarded_resolution(
        "socket.gethostbyname_ex", hostname, _REAL_GETHOSTBYNAME_EX, hostname
    )


def _blocked_gethostbyaddr(address: object):
    return _guarded_reverse(
        "socket.gethostbyaddr", address, _REAL_GETHOSTBYADDR, address
    )


def _blocked_getnameinfo(address: object, flags: object = 0):
    return _guarded_reverse(
        "socket.getnameinfo", address, _REAL_GETNAMEINFO, address, flags
    )


def _guarded_reverse(operation: str, address: object, call, *args):
    """Reverse lookups take the address as input, so the forward rule inverts.

    ``getaddrinfo("93.184.216.34", ...)`` sends nothing; ``gethostbyaddr`` of
    that same literal sends a PTR query. Only a loopback address is local here.
    """
    reason = _reverse_local_target(address)
    if reason is None:
        _record(operation, address)
        raise BlockedNetworkAccess(
            f"outbound name resolution blocked in offline probe: {operation}"
            f"({address!r})"
        )
    _permit(operation, address, reason)
    return call(*args)


def _blocked_sendto(self: socket.socket, *args: object):
    address = args[-1] if len(args) >= 2 else None
    return _guarded_datagram("socket.sendto", address, _REAL_SENDTO, self, *args)


def _blocked_sendmsg(self: socket.socket, *args: object):
    address = args[3] if len(args) >= 4 else None
    return _guarded_datagram("socket.sendmsg", address, _REAL_SENDMSG, self, *args)


def _guarded_datagram(operation: str, address: object, call, *args):
    """A connectionless send reaches the network without ever calling connect.

    Not the reported regression's path, and not reachable from this import as
    it stands - included because the sweep that closed the resolution gap found
    the same shape here, and "no current caller" is what the connect-only guard
    was also true of until a dependency changed.
    """
    reason = _datagram_local_target(address)
    if reason is None:
        _record(operation, address)
        raise BlockedNetworkAccess(
            f"outbound datagram blocked in offline probe: {operation}({address!r})"
        )
    if address is not None:
        _permit(operation, address, reason)
    return call(*args)


def install_guard() -> None:
    """Block every outbound path in this module that reaches the network.

    Connections. ``socket.create_connection`` covers the common high-level
    entry point (used directly by httpx/httpcore's sync transport and by
    urllib3); the two ``socket.socket`` methods cover manual ``socket.socket()
    ; sock.connect()`` use and asyncio's selector-based ``sock_connect``, which
    calls ``sock.connect`` directly on a non-blocking socket.

    Name resolution. Previously out of scope, and the gap said so in writing:
    a leak that only looked a hostname up - happy-eyeballs pre-resolution, a
    resolver probe, a telemetry hostname - left no attempt recorded and passed
    a test whose entire purpose is to prove the run is hermetic (#152). A
    lookup is an outbound network event on its own: the hostname reaches the
    resolver, and the DNS query is the first packet a corporate monitor sees.
    Forward lookups (``getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``)
    and reverse ones (``gethostbyaddr``, ``getnameinfo``) are both blocked,
    with distinct ``operation`` values so a resolution-only leak is
    distinguishable from a connection in the assertion output.

    Not every call is traffic, so the guard is not a blanket refusal: a
    numeric host, ``None``, and the loopback names perform no query and are
    permitted and recorded in ``permitted`` rather than ``attempts``. Blanket
    blocking would fail local and ``AF_UNIX`` paths that are not leaks.

    Connectionless sends. ``sendto``/``sendmsg`` reach the network without
    ever calling ``connect``, so the connection interceptions above do not see
    them; anything but a loopback or non-``AF_INET`` target is blocked.

    Still out of scope, stated so this docstring keeps describing what is
    actually shipped: a leak that reaches the network without the ``socket``
    module - a raw syscall through ``ctypes``, or a subprocess this probe does
    not spawn - is invisible here, as is any traffic from a library that ships
    its own resolver in C.
    """
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex
    socket.create_connection = _blocked_create_connection
    socket.getaddrinfo = _blocked_getaddrinfo
    socket.gethostbyname = _blocked_gethostbyname
    socket.gethostbyname_ex = _blocked_gethostbyname_ex
    socket.gethostbyaddr = _blocked_gethostbyaddr
    socket.getnameinfo = _blocked_getnameinfo
    socket.socket.sendto = _blocked_sendto
    socket.socket.sendmsg = _blocked_sendmsg


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
        "permitted": PERMITTED,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
