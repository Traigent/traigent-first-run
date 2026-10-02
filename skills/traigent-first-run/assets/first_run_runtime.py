"""Shared runtime for generated first-run bridges.

`scripts/generate_adapter.py` writes a thin bridge that imports the customer's own agent and
evaluator unchanged and hands every run to this module. Everything that spends money or touches
the network is here, once, so a bridge cannot carry its own copy of a guarantee:

* the offline boundary and phase pin, read before `.env` exactly as the hand-adapted wrapper in
  `references/sdk-execution.md` reads them;
* the spend ledger, a verbatim copy of that wrapper's functions (a test compares the two syntax
  trees, so they cannot drift apart): reserve before a call, settle after, refuse past the approved
  total, per-request timeout;
* provider interception on `litellm.completion` and the OpenAI client's `chat.completions.create`.
  A call through any other transport is not seen, so the generator refuses such agents and the
  first row's ledger delta double-checks it;
* the dataset reader, which never opens the holdout file in the baseline phase.

Importing this module has no side effect and needs no approval figure: `Bridge.start()` does the
enforcing, and only the run commands call it. A bridge's `score` function therefore loads under
the credential-stripped calibration child.
"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import importlib.util
import inspect
import itertools
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True  # nothing imported later writes __pycache__

APPROVED_FIGURE_NAMES = (
    "TRAIGENT_FIRST_RUN_COST_CEILING_USD",
    "TRAIGENT_FIRST_RUN_COST_SPENT_USD",
    "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD",
)
#: Same names preflight reads; a test pins the two sets together.
TUNING_SPLIT_NAMES = frozenset({"tune", "tuning", "train", "search"})
HOLDOUT_SPLIT_NAMES = frozenset(
    {
        "holdout",
        "held-out",
        "heldout",
        "held_out",
        "test",
        "validation",
        "validate",
    }
)
PROVIDER_PROBE_KEYS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
)

# Process state. Assigned by `Bridge.start`; the copied functions below read these names.
APPROVED_FIGURES: dict[str, str | None] = {}
RUN_COST_CEILING_USD: float = 0.0
RUN_COST_SPENT_USD: float = 0.0
UNTRACKED_CALL_COST_USD: float = 0.0
RUN_COST_REMAINING_USD: float = 0.0
MODEL_REQUEST_TIMEOUT_SECONDS: float = 120.0
RUN_SPEND_USD: list[float] = []
RUN_CALL_COSTS: list[float | None] = []
REJECTED_CALLS: list[str] = []
REFUSED_TRIAL_COSTS: list[float] = []
TRACKED_RUN: object | None = None
LEDGER_LOCK: threading.Lock = threading.Lock()
INSIDE_THE_DOOR: contextvars.ContextVar = contextvars.ContextVar(
    "traigent_first_run_inside_the_door", default=False
)
litellm = None  # imported by `start`, after the environment is pinned


# --- copied verbatim from references/sdk-execution.md (compared by test) ---------------------


def approved_usd(name: str) -> float:
    raw = (APPROVED_FIGURES.get(name) or "").strip()
    if not raw:
        raise SystemExit(
            f"{name} is not set, and this phase spends real money. Supply the "
            "approved figures in this process's environment - never in .env, "
            "which outlives the approval that set them - and start it again."
        )
    try:
        value = float(raw)
    except ValueError:
        # Caught rather than left to surface: every other way this figure can
        # be wrong stops with a sentence naming the remedy, and a bare
        # ValueError on a comma decimal would be the one that does not.
        raise SystemExit(
            f"{name} is {raw!r}, which is not a number of USD. Write it plainly "
            "as 5.00 - a decimal comma, a currency symbol, or a thousands "
            "separator is not read as a figure here."
        ) from None
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f"{name} must be a finite, non-negative number of USD")
    return value


def provider_reported_cost(response) -> float | None:
    # Prefer explicit provider cost: LiteLLM can synthesize hidden cost=0.0
    # when token counts are absent, including a cost-only usage block.
    # Its hidden response_cost remains useful on routes reporting only tokens,
    # but a computed cost is not a provider billing statement.
    hidden = getattr(response, "_hidden_params", None)
    hidden = hidden if isinstance(hidden, dict) else {}
    usage = getattr(response, "usage", None)

    def usage_field(name):
        return (
            usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        )

    reported = usage_field("cost")
    if reported is None:
        headers = hidden.get("additional_headers")
        if isinstance(headers, dict):
            reported = headers.get("llm_provider-x-litellm-response-cost")
    explicit_cost = reported is not None
    if reported is None:
        reported = hidden.get("response_cost")
    if reported is None:
        return None
    if isinstance(reported, bool):
        raise RuntimeError("The provider returned malformed response-cost metadata")
    try:
        cost = float(reported)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "The provider returned malformed response-cost metadata"
        ) from error
    if not math.isfinite(cost) or cost < 0:
        raise RuntimeError("The provider returned an invalid per-response cost")
    if cost == 0 and not explicit_cost:
        counts = [
            usage_field(name)
            for name in ("total_tokens", "prompt_tokens", "completion_tokens")
            if usage_field(name) is not None
        ]
        valid_usage = (
            counts
            and all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
                and value >= 0
                for value in counts
            )
            and any(value > 0 for value in counts)
        )
        if not valid_usage:
            return None
    return cost


def require_untruncated_completion(response) -> None:
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason is None and isinstance(choice, dict):
        finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise RuntimeError(
            "The provider truncated this completion (finish_reason='length'). "
            "It is not a measurement and must not be scored: a cut-off answer "
            "scores 0 rather than low and can crown a weaker model. This "
            "wrapper sets no max_tokens, so if your own agent sets one, raise "
            "it and re-run this configuration; otherwise the answer ran into "
            "the model's own output limit, so drop this configuration and "
            "report it as excluded"
        )


def run_remaining_usd() -> float:
    return RUN_COST_REMAINING_USD - sum(RUN_SPEND_USD)


def report_run_spend() -> None:
    spent_here = sum(RUN_SPEND_USD)
    print(
        f"this process placed {len(RUN_SPEND_USD)} provider call(s); budget debit "
        f"${spent_here:.4f}; prior phases debited ${RUN_COST_SPENT_USD:.4f}; "
        f"cumulative debit ${RUN_COST_SPENT_USD + spent_here:.4f} of the approved "
        f"${RUN_COST_CEILING_USD:.2f}; remaining budget ${run_remaining_usd():.4f}; "
        f"known cost subtotal for refused measurements ${sum(REFUSED_TRIAL_COSTS):.4f}"
    )
    reported_costs = [cost for cost in RUN_CALL_COSTS if cost is not None]
    unreported = len(RUN_SPEND_USD) - len(reported_costs)
    known_cost = (
        f"${sum(reported_costs):.4f} across {len(reported_costs)} call(s) with known cost"
        if reported_costs
        else "not reported"
    )
    print(
        f"Known call cost this process: {known_cost}; cost not reported for {unreported} "
        "call(s). Budget debits include conservative reservations for unpriced "
        "calls and are not a billing statement."
    )
    if REJECTED_CALLS:
        # A run that lost most of its calls to a dead model id or a rejected
        # key otherwise reads as a cheap success. The count and class names
        # identify the failure without exposing provider text.
        print(
            f"{len(REJECTED_CALLS)} of those call(s) were refused by the "
            f"provider before billing and cost nothing - their reservations "
            f"were returned to the remaining total. Failure types: "
            f"{', '.join(sorted(set(REJECTED_CALLS)))}. Raw provider text omitted."
        )


def record_call_spend(cost: float | None) -> None:
    RUN_CALL_COSTS.append(cost)
    RUN_SPEND_USD.append(UNTRACKED_CALL_COST_USD if cost is None else cost)


# Every litellm knob that turns one invocation into several provider requests
# is named for what it does: it retries, or it falls back.
# `worst_case_requests` below sizes three of them and can read no others, so a
# request carrying any other is REFUSED rather than priced at one request.
#
# The test is the NAME rather than a list of the knobs known today, because
# such a list is what failed here: `retry_policy` sat outside one, litellm
# honoured it on plain `completion` all the same, and a rate-limited call
# reserved for 1 request placed 6. So the default is closed, and a knob a
# later release adds is refused before it spends rather than priced at one
# after it has.
PRICED_REQUEST_KNOBS: frozenset[str] = frozenset(
    {"num_retries", "max_retries", "fallbacks"}
)


UNPRICED_KNOB_MARKERS: tuple[str, ...] = ("retry", "retries", "fallback")


def worst_case_requests(kwargs: dict) -> int:
    unpriced = sorted(
        name
        for name in kwargs
        if name not in PRICED_REQUEST_KNOBS
        and any(marker in name for marker in UNPRICED_KNOB_MARKERS)
    )
    if unpriced:
        raise RuntimeError(
            f"a call setting {', '.join(unpriced)} was not placed: this "
            "reservation reads `num_retries`, `max_retries` and `fallbacks` "
            "and prices no other retry or fallback knob - `retry_policy` "
            "alone placed 6 provider requests against a reservation of 1. "
            "Express the resilience with those three alone."
        )

    def rounded_up(count) -> int:
        # An integer is already whole, and `float(10**400)` raises
        # `OverflowError`, so an integer skips the cast. The cast stays for
        # everything else: a count read out of a file arrives as text.
        return count if isinstance(count, int) else math.ceil(float(count))

    asked = kwargs.get("num_retries")
    counted = asked or getattr(litellm, "num_retries", 0) or 0
    library_retries = max(1, rounded_up(counted)) if counted else 0
    client_retries = max(
        0, rounded_up((asked if asked is not None else kwargs["max_retries"]) or 0)
    )
    legs = 1 + len(kwargs.get("fallbacks") or ())
    per_leg = 1 + library_retries + client_retries
    if legs > 1 and asked:
        per_leg += max(1, rounded_up(asked))
    return per_leg * legs


def tracking_stopped() -> str | None:
    config = getattr(TRACKED_RUN, "traigent_config", None)
    if getattr(config, "result_source", None) == "local_fallback":
        return getattr(config, "fallback_reason", None) or "backend tracking failed"
    if getattr(config, "persistence_reason", None) == "rejected":
        return "the backend rejected this run's trials"
    return None


def reserve_call_spend(args: tuple, kwargs: dict) -> int:
    stopped = tracking_stopped()
    if stopped:
        raise RuntimeError(
            f"backend tracking dropped to local-only during this run "
            f"({stopped}), so nothing further reaches the portal and this call "
            "was not placed. Report the trials that completed and what it cost."
        )
    requests = worst_case_requests(kwargs)
    try:
        needed = requests * UNTRACKED_CALL_COST_USD
    except OverflowError:
        # A count too large to price in floating point is still a count, and
        # the answer to one is the refusal below rather than a traceback out of
        # the arithmetic - clamped, it would name a figure nobody asked for.
        needed = math.inf
    with LEDGER_LOCK:
        remaining = run_remaining_usd()
        if remaining < needed:
            model = kwargs.get("model") or (args[0] if args else "an unnamed model")
            raise RuntimeError(
                f"${remaining:.4f} of the approved ${RUN_COST_CEILING_USD:.2f} "
                f"total is left, which does not cover the {requests} provider "
                f"request(s) this invocation may place, so a call to {model} "
                "was not placed. Report what completed and ask for a larger "
                "total before running anything else."
            )
        RUN_SPEND_USD.append(needed)
        RUN_CALL_COSTS.append(None)
        return len(RUN_SPEND_USD) - 1


def settle_call_spend(slot: int, cost: float | None) -> None:
    RUN_SPEND_USD[slot] = UNTRACKED_CALL_COST_USD if cost is None else cost
    RUN_CALL_COSTS[slot] = cost


# The narrow class of failures the provider decides BEFORE the request reaches
# a model, so no tokens are generated and nothing is billed. Everything else -
# a timeout, a dropped connection, a mid-stream failure, a 5xx - reached a
# model or may have, is billable, and keeps its reservation under
# `release_call_spend` below. Keep this list short and certain: the cost of
# holding a reservation that was never billed is a run that halts early, and
# the cost of releasing one that WAS billed is spending past the approved
# total. Only add a class here when the provider cannot have charged for it.
REJECTED_BEFORE_BILLING: tuple[str, ...] = (
    "NotFoundError",
    "AuthenticationError",
    "PermissionDeniedError",
    # A 429 is an admission decision taken before generation, so it bills
    # nothing. It earns its place rather than riding along: the door pins
    # `max_retries=0`, so a rate limit is surfaced to this wrapper instead of
    # being absorbed underneath, once per occurrence, and a throttled free-tier
    # key is the single most likely way a run meets this code at all. A
    # depleted balance is here only where the route reports it as a 429, as
    # OpenAI does; OpenRouter answers 402, which the pinned litellm maps to
    # `APIError` rather than to any class named here - measured - so that one
    # is held, and a run refused on every call should check the balance first.
    "RateLimitError",
)


def release_call_spend(slot: int, error: BaseException) -> bool:
    if type(error).__name__ not in REJECTED_BEFORE_BILLING:
        return False
    if RUN_SPEND_USD[slot] > UNTRACKED_CALL_COST_USD:
        return False
    RUN_SPEND_USD[slot] = 0.0
    RUN_CALL_COSTS[slot] = 0.0
    REJECTED_CALLS.append(type(error).__name__)
    return True


def ledgered(place):

    def placed(*args, **kwargs):
        # Pin what cannot be counted, then count the rest and reserve it.
        # litellm hands the OpenAI-shaped client a nonzero `max_retries`, so a
        # call retries below this line where nothing can see it; `setdefault`
        # stops that and leaves a caller who asked for retries holding them.
        # The pin alone was claimed to make one wrapped call one billable
        # request, and `worst_case_requests` above records the measurements
        # that refuted it. Nor can the rest be turned off from here:
        # `setdefault("num_retries", 0)` is read as
        # `kwargs.get("num_retries") or litellm.num_retries`, where a literal
        # `0` is falsy - and it DOES suppress the process-wide figure on
        # `acompletion`, which is worse than useless, a safeguard holding on
        # the entry point nothing generates and not on the one every generated
        # line uses.
        #
        # So the invariant is not asserted. What is reserved instead is the
        # worst case the request states, before the call. `run-safety.md`
        # records the pin as one of the two exceptions to preserving a
        # caller's retry behaviour, and what it trades: a transient 429 or 500
        # now reaches the caller instead of being absorbed, paid for and
        # visible rather than silently, and re-running is the user's decision.
        kwargs.setdefault("max_retries", 0)
        if INSIDE_THE_DOOR.get():
            # A re-entry, not a new call - litellm's fallback handling calls
            # back in once per attempt, and the invocation that reserved
            # covered all of them. The paragraph after this fence owns why, and
            # what it concedes: a genuinely separate call placed from INSIDE
            # another one is covered by that invocation's reservation and no
            # more.
            return place(*args, **kwargs)
        slot = reserve_call_spend(args, kwargs)
        outside = INSIDE_THE_DOOR.set(True)
        # Everything is caught below and everything re-raises; one narrow class
        # is released on the way past. A call that fails after REACHING the
        # provider is billable and brings back no price - litellm surfaces a
        # timeout, a dropped connection and a mid-stream failure as an
        # exception rather than as a degraded response, and an awaited call
        # cancelled in flight raises `CancelledError`, which is not even an
        # `Exception`. The reservation already stands for all of them and for
        # the attempts retried underneath. Cost metadata that raises out of
        # `provider_reported_cost` lands the same way, with the conservative
        # figure left in place rather than a call spending nothing.
        #
        # What that reasoning does NOT cover is a request the gateway refuses
        # before any model sees it: a model id absent from the account's
        # catalogue is a 404 that bills nothing and cannot succeed on retry, and
        # a rejected key is a 401 on every call the run will ever place. Held at
        # the conservative unpriced rate, those spend the approved total on
        # calls that cost zero - and, worse, REPORT that spend to the user as
        # money gone. `release_call_spend` returns those it can identify and
        # leaves every billable failure holding its reservation; read its
        # docstring for what it holds regardless of the name - any invocation
        # that reserved for more than one request.
        try:
            response = place(*args, **kwargs)
            settle_call_spend(slot, provider_reported_cost(response))
        except BaseException as error:
            release_call_spend(slot, error)
            raise
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


def ledgered_async(place):

    async def placed(*args, **kwargs):
        kwargs.setdefault("max_retries", 0)  # as above, and for the same reason
        if INSIDE_THE_DOOR.get():
            return await place(*args, **kwargs)
        slot = reserve_call_spend(args, kwargs)
        outside = INSIDE_THE_DOOR.set(True)
        try:
            response = await place(*args, **kwargs)
            settle_call_spend(slot, provider_reported_cost(response))
        except BaseException as error:  # as above, and for the same reason
            release_call_spend(slot, error)
            raise
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


def refuse_unless_it_fits(calls: int, what: str) -> None:
    needed = calls * UNTRACKED_CALL_COST_USD
    remaining = run_remaining_usd()
    if needed > remaining:
        raise RuntimeError(
            f"{what} needs {calls} provider calls, about ${needed:.4f} at the "
            f"approved conservative rate, and ${remaining:.4f} of the approved "
            f"${RUN_COST_CEILING_USD:.2f} is left. Report the phases that did "
            "complete and take a larger total back to the user; do not run "
            "part of this and present its number as the whole."
        )


# --- end of the copied block ------------------------------------------------------------------


def inherited(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def positive_number(name: str, *, default: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        if default is None:
            raise SystemExit(f"{name} is required (a positive number of seconds)")
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise SystemExit(f"{name} must be finite and positive")
    return value


class _ProbeStop(BaseException):
    """Ends one probed agent call after its request was recorded. Not an Exception on purpose,
    so an agent's own `except Exception` cannot swallow it."""


PROBED_REQUESTS: list[str] = []


def _record_request(kwargs: dict) -> None:
    PROBED_REQUESTS.append(json.dumps(kwargs, sort_keys=True, default=repr))
    raise _ProbeStop


class SafetyRefusal(RuntimeError):
    """An accounting or safety refusal: the run stops here. An ordinary per-row agent failure is
    any other exception and only counts as a failed row."""


def halting(place):
    """A refusal raised before this call reserved anything (budget, retry knob, tracking) halts
    the run. Nested re-entries and failures after a reservation stay ordinary errors."""

    @functools.wraps(place)
    def placed(*args, **kwargs):
        outer, entered = INSIDE_THE_DOOR.get(), len(RUN_SPEND_USD)
        try:
            return place(*args, **kwargs)
        except SafetyRefusal:
            raise
        except RuntimeError as error:
            if not outer and len(RUN_SPEND_USD) == entered:
                raise SafetyRefusal(str(error)) from error
            raise

    return placed


def halting_async(place):
    @functools.wraps(place)
    async def placed(*args, **kwargs):
        outer, entered = INSIDE_THE_DOOR.get(), len(RUN_SPEND_USD)
        try:
            return await place(*args, **kwargs)
        except SafetyRefusal:
            raise
        except RuntimeError as error:
            if not outer and len(RUN_SPEND_USD) == entered:
                raise SafetyRefusal(str(error)) from error
            raise

    return placed


def _clamp_timeout(kwargs: dict) -> None:
    """Absent, None, zero, negative or above the configured limit all mean the limit."""
    value = kwargs.get("timeout")
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not numeric and value is not None:
        return  # a client timeout object: the provider client enforces it
    if not numeric or not 0 < value <= MODEL_REQUEST_TIMEOUT_SECONDS:
        kwargs["timeout"] = MODEL_REQUEST_TIMEOUT_SECONDS


def _deadline(kwargs: dict) -> float | None:
    value = kwargs.get("timeout")
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    return float(value) if ok else None


def timed(place):
    """The guide's per-request timeout on every intercepted LiteLLM call (OpenAI's has its own)."""

    @functools.wraps(place)
    def placed(*args, **kwargs):
        _clamp_timeout(kwargs)
        return place(*args, **kwargs)

    return placed


def timed_async(place):
    """Same timeout, also enforced as a deadline, so a hung await is cancelled, not waited on."""

    @functools.wraps(place)
    async def placed(*args, **kwargs):
        _clamp_timeout(kwargs)
        return await asyncio.wait_for(place(*args, **kwargs), _deadline(kwargs))

    return placed


def untruncated(place):
    """Refuse a cut-off completion instead of scoring it as an ordinary wrong answer."""

    @functools.wraps(place)
    def placed(*args, **kwargs):
        response = place(*args, **kwargs)
        if hasattr(response, "choices"):
            cost = provider_reported_cost(response)
            try:
                require_untruncated_completion(response)
            except RuntimeError:
                if cost is not None:
                    REFUSED_TRIAL_COSTS.append(cost)
                raise
        return response

    return placed


def untruncated_async(place):
    @functools.wraps(place)
    async def placed(*args, **kwargs):
        response = await place(*args, **kwargs)
        if hasattr(response, "choices"):
            cost = provider_reported_cost(response)
            try:
                require_untruncated_completion(response)
            except RuntimeError:
                if cost is not None:
                    REFUSED_TRIAL_COSTS.append(cost)
                raise
        return response

    return placed


def reported_or_computed_cost(response) -> float | None:
    """The route's own cost when it states one, else litellm's table price, else None."""
    cost = provider_reported_cost(response)
    if cost is not None or litellm is None:
        return cost
    try:
        computed = float(litellm.completion_cost(completion_response=response))
    except Exception:  # an unpriced model: the caller keeps the conservative debit
        return None
    return computed if math.isfinite(computed) and computed >= 0 else None


def _openai_sizing(owner, kwargs: dict) -> dict:
    retries = getattr(getattr(owner, "_client", None), "max_retries", 0)
    return {"max_retries": int(retries or 0), "model": kwargs.get("model")}


def ledgered_openai(place):
    """The ledger on `chat.completions.create`: reserve before, settle after, refuse a stream."""

    @functools.wraps(place)
    def placed(self, *args, **kwargs):
        if INSIDE_THE_DOOR.get():  # litellm reached the client through its own door
            return place(self, *args, **kwargs)
        if kwargs.get("stream"):
            raise RuntimeError(
                "a streamed completion was not placed: the cost ledger settles on a whole "
                "response, so stream=True is not a supported transport for a first run"
            )
        _clamp_timeout(kwargs)
        slot = reserve_call_spend(args, _openai_sizing(self, kwargs))
        outside = INSIDE_THE_DOOR.set(True)
        try:
            response = place(self, *args, **kwargs)
            settle_call_spend(slot, reported_or_computed_cost(response))
        except BaseException as error:
            release_call_spend(slot, error)
            raise
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


def ledgered_openai_async(place):
    @functools.wraps(place)
    async def placed(self, *args, **kwargs):
        if INSIDE_THE_DOOR.get():
            return await place(self, *args, **kwargs)
        if kwargs.get("stream"):
            raise RuntimeError(
                "a streamed completion was not placed: stream=True is not a supported "
                "transport for a first run"
            )
        _clamp_timeout(kwargs)
        slot = reserve_call_spend(args, _openai_sizing(self, kwargs))
        outside = INSIDE_THE_DOOR.set(True)
        try:
            response = await asyncio.wait_for(
                place(self, *args, **kwargs), _deadline(kwargs)
            )
            settle_call_spend(slot, reported_or_computed_cost(response))
        except BaseException as error:
            release_call_spend(slot, error)
            raise
        finally:
            INSIDE_THE_DOOR.reset(outside)
        return response

    return placed


def _openai_classes():
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions
    except ImportError:
        return None
    return Completions, AsyncCompletions


def install_interceptors() -> None:
    """Wrap every transport this runtime supports, once per process."""
    if litellm is not None and not getattr(litellm, "_first_run_ledgered", False):
        litellm.completion = untruncated(halting(timed(ledgered(litellm.completion))))
        litellm.acompletion = untruncated_async(
            halting_async(timed_async(ledgered_async(litellm.acompletion)))
        )
        litellm._first_run_ledgered = True
    classes = _openai_classes()
    if classes and not getattr(classes[0], "_first_run_ledgered", False):
        sync, asynchronous = classes
        sync.create = untruncated(halting(ledgered_openai(sync.create)))
        asynchronous.create = untruncated_async(
            halting_async(ledgered_openai_async(asynchronous.create))
        )
        sync._first_run_ledgered = True


def install_recorders() -> None:
    """Probe mode: every supported call is recorded and stopped before any network use."""

    async def record_async(*_args, **kwargs):
        _record_request(kwargs)

    if litellm is not None:
        litellm.completion = lambda *a, **k: _record_request(k)
        litellm.acompletion = record_async
    classes = _openai_classes()
    if classes:
        classes[0].create = lambda self, *a, **k: _record_request(k)

        async def record_openai_async(self, *_args, **kwargs):
            _record_request(kwargs)

        classes[1].create = record_openai_async


def dotted(value, path: str):
    """(found, value) for a dotted path through dicts - the same reader preflight uses."""
    for part in path.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def attribute_or_key(value, path: str):
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                raise KeyError(part)
            value = value[part]
        else:
            value = getattr(value, part)
    return value


def read_rows(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SystemExit(f"{path.name} must hold one JSON object per row")
    return rows


def normalized_score(raw) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"the evaluator returned {type(raw).__name__}, not a number")
    score = float(raw)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(
            f"the evaluator returned {score!r}; a score is finite and in [0,1]"
        )
    return score


def resolve(token, context: dict):
    """One argument of a mapped call: `$name`, `$config.knob`, or `{"value": literal}`."""
    if isinstance(token, dict):
        return token["value"]
    name = token[1:]
    if name.startswith("config."):
        return context["config"][name[len("config.") :]]
    return context[name]


class Bridge:
    """One generated bridge's run: loads the customer's callables by file path, never copies them."""

    def __init__(self, spec: dict, run_dir: Path):
        self.spec = spec
        self.run_dir = Path(run_dir).resolve()
        self.project_root = (self.run_dir / spec.get("project_root", "..")).resolve()
        self.started = False
        self.ledgered = False
        self.transport_checked = False
        self._functions: dict[str, object] = {}

    # -- loading ---------------------------------------------------------------------------

    def function(self, role: str):
        if role not in self._functions:
            entry = self.spec[role]
            path = (self.project_root / entry["file"]).resolve()
            if not path.is_relative_to(self.project_root) or not path.is_file():
                raise SystemExit(
                    f"{role} file {entry['file']} is not inside the project"
                )
            package_base = self.package_base(path)
            if package_base is not None:
                # Inside a package: import it by its package path so `from . import x` works.
                if str(package_base) not in sys.path:
                    sys.path.insert(0, str(package_base))
                relative = path.relative_to(package_base).with_suffix("")
                parts = (
                    relative.parts[:-1]
                    if relative.name == "__init__"
                    else relative.parts
                )
                module = importlib.import_module(".".join(parts))
            else:
                for directory in (self.project_root, path.parent):
                    if str(directory) not in sys.path:
                        sys.path.insert(0, str(directory))
                spec = importlib.util.spec_from_file_location(
                    f"_first_run_{role}", path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            function = getattr(module, entry["function"], None)
            if not callable(function):
                raise SystemExit(f"{entry['file']} has no callable {entry['function']}")
            self._functions[role] = function
        return self._functions[role]

    def package_base(self, path: Path) -> Path | None:
        """The directory to put on sys.path so `path` imports as a package member, else None."""
        top = None
        directory = path.parent
        while (directory / "__init__.py").is_file() and directory != self.project_root:
            top, directory = directory, directory.parent
        return top.parent if top is not None else None

    @staticmethod
    def call(function, kwargs: dict):
        result = function(**kwargs)
        if inspect.isawaitable(result):
            result = asyncio.run(_await(result))
        return result

    # -- the two adapted calls -------------------------------------------------------------

    def agent_output(self, row: dict, config: dict):
        entry = self.spec["agent"]
        # The gold answer (and the raw row that holds it) never enters the agent's context.
        context = {
            "input": row["input"],
            "id": row["id"],
            "metadata": row["metadata"],
            "config": config,
        }
        arguments = {
            name: resolve(token, context) for name, token in entry["args"].items()
        }
        before = len(RUN_SPEND_USD)
        result = self.call(self.function("agent"), arguments)
        if self.ledgered and not self.transport_checked:
            self.transport_checked = True
            if entry["calls_per_row"] and len(RUN_SPEND_USD) == before:
                raise SystemExit(
                    "the agent placed no provider call the ledger saw. Its transport is not "
                    "supported, so nothing it spends is counted: stopped before any further spend"
                )
        if entry.get("output_path"):
            result = attribute_or_key(result, entry["output_path"])
        return result

    def score(self, *, output, expected, input_data, metadata=None) -> float:
        """The calibration contract: four keywords in, one normalized score out."""
        entry = self.spec["evaluator"]
        if entry["calls_per_row"] and not self.started:
            raise SystemExit(
                "this evaluator declares provider calls, so it runs only inside "
                "`baseline`, where the spend ledger is active"
            )
        context = {
            "output": output,
            "expected": expected,
            "input": input_data,
            "metadata": metadata or {},
        }
        arguments = {
            name: resolve(token, context) for name, token in entry["args"].items()
        }
        before = len(RUN_SPEND_USD)

        def accounted(failed: bool = False) -> None:
            placed = len(RUN_SPEND_USD) - before
            declared = entry["calls_per_row"]
            # A failure may stop short of its declared calls; it may never exceed them.
            if self.started and (
                placed > declared or (placed != declared and not failed)
            ):
                raise SafetyRefusal(
                    f"scoring one row placed {placed} provider call(s) the ledger saw, and "
                    f"evaluator.calls_per_row declares {entry['calls_per_row']}; correct the "
                    "declaration before any more spend"
                )

        try:
            score = normalized_score(self.call(self.function("evaluator"), arguments))
        except SafetyRefusal:
            raise
        except BaseException:
            accounted(True)  # an undeclared call before a failure still stops the run
            raise
        accounted()
        return score

    # -- data ------------------------------------------------------------------------------

    def rows(self, path: str) -> list[dict]:
        fields = self.spec["dataset"]
        located = (self.project_root / path).resolve()
        if not located.is_relative_to(self.project_root):
            raise SystemExit("the dataset must be inside the project")
        out = []
        for index, raw in enumerate(read_rows(located)):
            row = {"id": index, "metadata": {}, "split": None, "raw": raw}
            for target, key in (("input", "input"), ("expected", "expected")):
                found, value = dotted(raw, fields[key])
                if not found:
                    raise SystemExit(
                        f"row {index} has no field {fields[key]!r} for {target}"
                    )
                row[target] = value
            for target in ("id", "metadata", "split"):
                if fields.get(target):
                    found, value = dotted(raw, fields[target])
                    if found:
                        row[target] = value
            out.append(row)
        return out

    def tuning_rows(self) -> list[dict]:
        rows = self.rows(self.spec["dataset"]["path"])
        if not self.spec["dataset"].get("split"):
            return rows
        known = TUNING_SPLIT_NAMES | HOLDOUT_SPLIT_NAMES
        keep = []
        for row in rows:
            name = str(row["split"]).strip().casefold()
            if name not in known:
                raise SystemExit(
                    f"row {row['id']} has split {row['split']!r}; known splits are "
                    f"{', '.join(sorted(known))}"
                )
            if name in TUNING_SPLIT_NAMES:
                keep.append(row)
        return keep

    def holdout_rows(self) -> list[dict]:
        """Deliberately unreachable from the baseline: a bridge that never opens it cannot leak it."""
        raise SystemExit(
            "the held-out rows are read only by the connected phase, never by the baseline"
        )

    # -- commands --------------------------------------------------------------------------

    def configurations(self, space: dict) -> list[dict]:
        names = list(space)
        return [
            dict(zip(names, values)) for values in itertools.product(*space.values())
        ]

    def start(self, *, probe: bool = False) -> None:
        global litellm, APPROVED_FIGURES, RUN_COST_CEILING_USD, RUN_COST_SPENT_USD
        global UNTRACKED_CALL_COST_USD, RUN_COST_REMAINING_USD, MODEL_REQUEST_TIMEOUT_SECONDS
        if self.started:
            return
        phase = (
            os.environ.get("TRAIGENT_FIRST_RUN_PHASE", "baseline").strip().casefold()
        )
        # Captured before dotenv, popped after: a stale .env cannot supply an approval or opt a
        # baseline into connected work.
        APPROVED_FIGURES = {
            name: os.environ.get(name) for name in APPROVED_FIGURE_NAMES
        }
        try:
            from dotenv import load_dotenv

            load_dotenv(self.project_root / ".env", override=False)
        except ImportError:
            pass
        os.environ.pop("TRAIGENT_FIRST_RUN_PHASE", None)
        for name in APPROVED_FIGURE_NAMES:
            os.environ.pop(name, None)
        if phase != "baseline":
            raise SystemExit(
                "a generated bridge runs the local baseline; the connected phase is not "
                "generated, use the hand-adapted wrapper in references/sdk-execution.md"
            )
        if inherited("TRAIGENT_MOCK_LLM"):
            raise SystemExit(
                "TRAIGENT_MOCK_LLM is set, so every score would describe the mock and not "
                "the agent. Unset it; this run will not unset it for you."
            )
        if inherited("TRAIGENT_REQUIRE_CLOUD"):
            raise SystemExit(
                "TRAIGENT_REQUIRE_CLOUD requires a backend session, but the baseline is "
                "deliberately local. Launch a new baseline process with it set to 0."
            )
        # Backend-offline for this process: blank rather than absent, so a dotenv file cannot
        # bring a Traigent credential or URL back, and local pricing so importing litellm
        # fetches nothing.
        os.environ["TRAIGENT_OFFLINE_MODE"] = "true"
        for name in ("TRAIGENT_API_KEY", "TRAIGENT_BACKEND_URL", "TRAIGENT_API_URL"):
            os.environ[name] = ""
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        MODEL_REQUEST_TIMEOUT_SECONDS = positive_number(
            "TRAIGENT_FIRST_RUN_MODEL_REQUEST_TIMEOUT_SECONDS", default=120.0
        )
        import litellm as _litellm

        litellm = _litellm
        if probe:
            for name in PROVIDER_PROBE_KEYS:
                os.environ.setdefault(name, "sk-probe-never-sent")
            install_recorders()
        else:
            RUN_COST_CEILING_USD = approved_usd("TRAIGENT_FIRST_RUN_COST_CEILING_USD")
            RUN_COST_SPENT_USD = approved_usd("TRAIGENT_FIRST_RUN_COST_SPENT_USD")
            UNTRACKED_CALL_COST_USD = approved_usd(
                "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD"
            )
            RUN_COST_REMAINING_USD = RUN_COST_CEILING_USD - RUN_COST_SPENT_USD
            if UNTRACKED_CALL_COST_USD <= 0:
                raise SystemExit(
                    "TRAIGENT_FIRST_RUN_UNTRACKED_CALL_COST_USD must be positive: a zero "
                    "deduction lets an unpriced route run until something else stops it"
                )
            if RUN_COST_REMAINING_USD < UNTRACKED_CALL_COST_USD:
                raise SystemExit(
                    f"${RUN_COST_REMAINING_USD:.4f} of the approved "
                    f"${RUN_COST_CEILING_USD:.2f} is left, which does not cover one provider "
                    f"call at ${UNTRACKED_CALL_COST_USD:.4f}. Take a larger total back to the user."
                )
            install_interceptors()
            atexit.register(report_run_spend)
            self.ledgered = True
        self.started = True

    def run_baseline(self) -> int:
        timeout = positive_number("TRAIGENT_FIRST_RUN_BASELINE_TIMEOUT_SECONDS")
        self.start()
        space = self.spec["baseline"]["space"]
        configs = self.configurations(space)
        rows = self.tuning_rows()
        if not rows:
            raise SystemExit("the tuning split has no rows")
        per_row = (
            max(1, self.spec["agent"]["calls_per_row"])
            + self.spec["evaluator"]["calls_per_row"]
        )
        refuse_unless_it_fits(per_row * len(rows) * len(configs), "the baseline sweep")
        self.function("agent"), self.function(
            "evaluator"
        )  # load after the interceptors
        began, results, complete = time.monotonic(), [], True
        for config in configs:
            scores, failures = [], {}
            for row in rows:
                if time.monotonic() - began > timeout:
                    complete = False
                    break
                try:
                    output = self.agent_output(row, config)
                    scores.append(
                        {
                            "id": row["id"],
                            "score": self.score(
                                output=output,
                                expected=row["expected"],
                                input_data=row["input"],
                                metadata=row["metadata"],
                            ),
                        }
                    )
                except SafetyRefusal as refusal:
                    raise SystemExit(f"stopped before any further spend: {refusal}")
                except Exception as error:  # class name only: provider text is not kept
                    failures[type(error).__name__] = (
                        failures.get(type(error).__name__, 0) + 1
                    )
            values = [item["score"] for item in scores]
            results.append(
                {
                    "config": config,
                    "n_scored": len(values),
                    "n_failed": sum(failures.values()),
                    "failure_types": failures,
                    "mean_score": sum(values) / len(values) if values else None,
                    "rows": scores,
                }
            )
            if not complete:
                break
        document = {
            "kind": "first-run-bridge-baseline",
            "phase": "baseline",
            "complete": complete and len(results) == len(configs),
            "tuning_rows": len(rows),
            "baseline_config": self.spec["baseline"]["config"],
            "results": results,
            "provider_calls": len(RUN_SPEND_USD),
            "budget_debit_usd": round(sum(RUN_SPEND_USD), 6),
            "known_cost_usd": round(sum(c for c in RUN_CALL_COSTS if c is not None), 6),
            "elapsed_seconds": round(time.monotonic() - began, 3),
        }
        out = self.run_dir / "baseline-results.json"
        out.write_text(
            json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(f"wrote {out}")
        unscored = [r for r in results if not r["n_scored"]]
        if unscored:
            print(f"{len(unscored)} configuration(s) scored no row; see failure_types")
        return 0 if document["complete"] and not unscored else 3

    def run_probe(self) -> int:
        """Does each searched knob change the request the agent places? No network, no key."""
        self.start(probe=True)
        space = self.spec["baseline"]["space"]
        base = self.spec["baseline"]["config"]
        row = self.tuning_rows()[0]

        def request_for(config: dict):
            PROBED_REQUESTS.clear()
            try:
                self.agent_output(row, config)
            except _ProbeStop:
                pass
            except Exception as error:
                return f"error:{type(error).__name__}"
            return PROBED_REQUESTS[0] if PROBED_REQUESTS else None

        reference = request_for(base)
        verdicts = {}
        for knob, values in space.items():
            if len(set(map(repr, values))) < 2:
                verdicts[knob] = "not-searched"
                continue
            changed = [
                request_for({**base, knob: value}) != reference
                for value in values
                if value != base[knob]
            ]
            verdicts[knob] = "visible" if reference and any(changed) else "ignored"
        if reference is None or str(reference).startswith("error:"):
            verdicts = {knob: "unobserved" for knob in space}
        print(json.dumps({"wiring": verdicts}, indent=2))
        return (
            0 if all(v in {"visible", "not-searched"} for v in verdicts.values()) else 3
        )

    def main(self, argv: list[str]) -> int:
        commands = {"baseline": self.run_baseline, "probe": self.run_probe}
        if len(argv) != 1 or argv[0] not in commands:
            print("usage: adapter_bridge.py baseline | probe", file=sys.stderr)
            return 2
        return commands[argv[0]]()


async def _await(value):
    return await value
