"""A leak that resolves a hostname and never connects (traigent-first-run#152).

Imported by name through ``PROBE_IMPORT_MODULES`` so it runs inside
``offline_socket_probe.py``'s guard, exactly like ``litellm`` does - the point
is to exercise the guard's real interception points, not a hand-rolled copy of
them.

This is the shape the connect-only guard could not see: a happy-eyeballs
pre-resolution, a resolver probe, or a telemetry hostname lookup emits a DNS
query carrying the hostname and then does nothing else. Against that guard the
probe recorded no attempt, and
``test_documented_local_mock_path_makes_zero_outbound_socket_attempts``
asserted ``attempts == []`` and passed.

Every lookup here is wrapped, because the guard raises and an unhandled
exception at import time would be reported as an ``import_errors`` entry
instead of as the recorded attempt the assertion reads. The host is under
``.invalid`` (RFC 2606), so on an unguarded interpreter the query is a
guaranteed NXDOMAIN against the configured resolver rather than a connection to
anything real - and it still leaves the machine, which is the whole finding.
"""

from __future__ import annotations

import socket

LEAKED_HOST = "telemetry.dns-only-leak.invalid"

outcomes: dict[str, str] = {}

try:
    socket.getaddrinfo(LEAKED_HOST, 443)
except Exception as error:  # recorded, not swallowed: the probe reports it
    outcomes["getaddrinfo"] = f"{type(error).__name__}: {error}"
else:
    outcomes["getaddrinfo"] = "returned"

try:
    socket.gethostbyname(LEAKED_HOST)
except Exception as error:
    outcomes["gethostbyname"] = f"{type(error).__name__}: {error}"
else:
    outcomes["gethostbyname"] = "returned"

# The reverse direction, which inverts the rule rather than repeating it: this
# literal is permitted as a *forward* lookup argument, because parsing an
# address asks nothing of a resolver - but a PTR query for it is a real
# outbound question about a routable address.
ROUTABLE_ADDRESS = "93.184.216.34"

try:
    socket.gethostbyaddr(ROUTABLE_ADDRESS)
except Exception as error:
    outcomes["gethostbyaddr"] = f"{type(error).__name__}: {error}"
else:
    outcomes["gethostbyaddr"] = "returned"
