"""The calls the resolution guard must NOT block (traigent-first-run#152).

The counterweight to ``dns_only_leak``. Blocking every ``getaddrinfo`` would
have been simpler and wrong: a numeric host performs no query at all, ``None``
is the wildcard/loopback bind form, and a loopback name is answered from
``/etc/hosts``. None of the three emits a packet, so a guard that failed on
them would produce red runs with no leak behind them - and a test that fails
for a reason nobody believes is a test people learn to edit.

Every call here must land in the probe's ``permitted`` list and none in
``attempts``. Unwrapped on purpose: these are expected to succeed, so a raise
here is a real regression in the guard and must surface as an import error
rather than be absorbed.
"""

from __future__ import annotations

import socket

resolved: dict[str, object] = {
    "ipv4_literal": socket.getaddrinfo("127.0.0.1", 80),
    "ipv6_literal": socket.getaddrinfo("::1", 80),
    "routable_literal": socket.getaddrinfo("93.184.216.34", 443),
    "wildcard": socket.getaddrinfo(None, 0),
    "loopback_name": socket.gethostbyname("localhost"),
}
