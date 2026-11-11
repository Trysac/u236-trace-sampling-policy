"""Tail-based trace sampling policies.

Evaluate ordered keep rules over complete traces with bounded memory and
consistent decisions for spans that arrive late.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

__all__ = [
    "Decision",
    "Policy",
    "Rule",
    "SamplerStats",
    "SamplingError",
    "Span",
    "TailSampler",
    "__version__",
    "keep_by_ratio",
    "load_policy",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Span(TypedDict):
    """A single span in a trace."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_ns: int
    end_ns: int
    status: Literal["UNSET", "OK", "ERROR"]
    attributes: dict[str, str | int | float | bool]


class SamplingError(Exception):
    """Base error for trace sampling policy problems."""

    def __init__(self, code: Literal["invalid_span", "invalid_policy"]) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Rule:
    """A single sampling rule evaluated in order."""

    kind: Literal["error", "latency", "attribute", "probabilistic", "rate_limit"]
    min_ms: float | None = None
    key: str | None = None
    values: tuple[str | int | bool, ...] = ()
    ratio: float | None = None
    per_second: float | None = None


@dataclass(frozen=True)
class Decision:
    """Outcome of a sampling decision."""

    keep: bool
    rule: str | None
    forced: bool = False


@dataclass(frozen=True)
class SamplerStats:
    """Statistics for a TailSampler."""

    buffered_traces: int
    decided: int
    dropped_spans: int
    forced: int


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_HEX_DIGITS = set("0123456789abcdef")
_MAX_NAME_LENGTH = 1024
_MAX_ATTR_KEY_LENGTH = 256
_MAX_ATTR_VALUE_LENGTH = 1024


def _validate_trace_id(trace_id: str) -> None:
    if (
        not isinstance(trace_id, str)
        or len(trace_id) != 32
        or any(c not in _HEX_DIGITS for c in trace_id)
        or trace_id == "0" * 32
    ):
        raise SamplingError("invalid_span")


def _validate_span_id(span_id: str) -> None:
    if (
        not isinstance(span_id, str)
        or len(span_id) != 16
        or any(c not in _HEX_DIGITS for c in span_id)
    ):
        raise SamplingError("invalid_span")


def _validate_span(span: Span) -> None:
    if not isinstance(span, dict):
        raise SamplingError("invalid_span")
    required = {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "start_ns",
        "end_ns",
        "status",
        "attributes",
    }
    if not required.issubset(span.keys()):
        raise SamplingError("invalid_span")

    _validate_trace_id(span["trace_id"])
    _validate_span_id(span["span_id"])
    if span["parent_span_id"] is not None:
        _validate_span_id(span["parent_span_id"])

    name = span["name"]
    if not isinstance(name, str) or not name or len(name) > _MAX_NAME_LENGTH:
        raise SamplingError("invalid_span")

    start_ns = span["start_ns"]
    end_ns = span["end_ns"]
    if not isinstance(start_ns, int) or not isinstance(end_ns, int):
        raise SamplingError("invalid_span")
    if end_ns < start_ns:
        raise SamplingError("invalid_span")

    status = span["status"]
    if status not in ("UNSET", "OK", "ERROR"):
        raise SamplingError("invalid_span")

    attributes = span["attributes"]
    if not isinstance(attributes, dict):
        raise SamplingError("invalid_span")
    for key, value in attributes.items():
        if not isinstance(key, str) or not key or len(key) > _MAX_ATTR_KEY_LENGTH:
            raise SamplingError("invalid_span")
        if not isinstance(value, (str, int, float, bool)):
            raise SamplingError("invalid_span")
        if isinstance(value, str) and len(value) > _MAX_ATTR_VALUE_LENGTH:
            raise SamplingError("invalid_span")


def _match_value(a: str | int | float | bool, b: str | int | bool) -> bool:
    """Return True if ``a`` and ``b`` have the same type and value."""
    return type(a) is type(b) and a == b


# ---------------------------------------------------------------------------
# Probabilistic sampling
# ---------------------------------------------------------------------------


def keep_by_ratio(trace_id: str, ratio: float) -> bool:
    """Decide probabilistically using the rightmost 56 bits of ``trace_id``.

    Implements the OpenTelemetry consistent probability sampling convention:
    keep when ``R >= T`` where ``R`` is the integer value of the last 14 hex
    digits and ``T = 2**56 - int(ratio * 2**56)``.

    Raises:
        SamplingError: if ``trace_id`` is invalid or ``ratio`` is outside [0, 1].
    """
    _validate_trace_id(trace_id)
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not (0.0 <= ratio <= 1.0):
        raise SamplingError("invalid_policy")
    if ratio == 0.0:
        return False
    if ratio == 1.0:
        return True
    threshold = 2**56 - int(ratio * 2**56)
    r_value = int(trace_id[-14:], 16)
    return r_value >= threshold


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class Policy:
    """Ordered list of keep rules.

    Rules are evaluated in order; the first rule that decides to keep wins.
    If no rule keeps, the trace is dropped (rule ``None``).
    """

    def __init__(
        self,
        rules: Sequence[Rule],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if len(rules) > 10:
            raise SamplingError("invalid_policy")
        self._rules = tuple(rules)
        self._clock = clock
        self._bucket_tokens: list[float] = []
        self._bucket_last: list[float] = []
        for rule in self._rules:
            if rule.kind == "rate_limit":
                per_second = rule.per_second
                if (
                    per_second is None
                    or isinstance(per_second, bool)
                    or not isinstance(per_second, (int, float))
                    or per_second <= 0
                ):
                    raise SamplingError("invalid_policy")
                self._bucket_tokens.append(float(per_second))
                self._bucket_last.append(self._clock())
            else:
                self._bucket_tokens.append(0.0)
                self._bucket_last.append(0.0)
        # Validate all rules
        for rule in self._rules:
            self._validate_rule(rule)

    @staticmethod
    def _validate_rule(rule: Rule) -> None:
        if rule.kind == "error":
            # no required fields
            pass
        elif rule.kind == "latency":
            if (
                rule.min_ms is None
                or isinstance(rule.min_ms, bool)
                or not isinstance(rule.min_ms, (int, float))
                or rule.min_ms < 0
            ):
                raise SamplingError("invalid_policy")
        elif rule.kind == "attribute":
            if not isinstance(rule.key, str) or not rule.key:
                raise SamplingError("invalid_policy")
            if not isinstance(rule.values, tuple):
                raise SamplingError("invalid_policy")
            if len(rule.values) > 100:
                raise SamplingError("invalid_policy")
            for value in rule.values:
                if not isinstance(value, (str, int, bool)):
                    raise SamplingError("invalid_policy")
        elif rule.kind == "probabilistic":
            if (
                rule.ratio is None
                or isinstance(rule.ratio, bool)
                or not isinstance(rule.ratio, (int, float))
                or not (0.0 <= rule.ratio <= 1.0)
            ):
                raise SamplingError("invalid_policy")
        elif rule.kind == "rate_limit":
            # validated in __init__
            pass
        else:
            raise SamplingError("invalid_policy")

    def decide(self, spans: Sequence[Span]) -> Decision:
        """Evaluate the rules against a complete trace."""
        for span in spans:
            _validate_span(span)

        if not spans:
            return Decision(keep=False, rule=None)

        trace_id = spans[0]["trace_id"]

        for idx, rule in enumerate(self._rules):
            if rule.kind == "error":
                if any(span["status"] == "ERROR" for span in spans):
                    return Decision(keep=True, rule="error")
            elif rule.kind == "latency":
                min_ms = cast(float, rule.min_ms)
                roots = [s for s in spans if s["parent_span_id"] is None]
                if roots:
                    earliest_root = min(roots, key=lambda s: s["start_ns"])
                    duration_ns = earliest_root["end_ns"] - earliest_root["start_ns"]
                else:
                    duration_ns = max(s["end_ns"] for s in spans) - min(
                        s["start_ns"] for s in spans
                    )
                duration_ms = duration_ns / 1_000_000
                if duration_ms >= min_ms:
                    return Decision(keep=True, rule="latency")
            elif rule.kind == "attribute":
                key = cast(str, rule.key)
                for span in spans:
                    attr_value = span["attributes"].get(key)
                    if attr_value is not None and any(
                        _match_value(attr_value, v) for v in rule.values
                    ):
                        return Decision(keep=True, rule="attribute")
            elif rule.kind == "probabilistic":
                if keep_by_ratio(trace_id, cast(float, rule.ratio)):
                    return Decision(keep=True, rule="probabilistic")
            elif rule.kind == "rate_limit":
                now = self._clock()
                tokens = self._bucket_tokens[idx]
                last = self._bucket_last[idx]
                elapsed = now - last
                capacity = cast(float, rule.per_second)
                tokens = min(capacity, tokens + elapsed * capacity)
                self._bucket_last[idx] = now
                if tokens >= 1.0 - 1e-12:
                    tokens -= 1.0
                    self._bucket_tokens[idx] = tokens
                    return Decision(keep=True, rule="rate_limit")
                self._bucket_tokens[idx] = tokens

        return Decision(keep=False, rule=None)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_policy(config: Mapping[str, object]) -> Policy:
    """Build a Policy from a configuration mapping.

    ``config`` must contain a ``rules`` key with a list of at most 10 rule
    dictionaries. Raises :class:`SamplingError` with code ``invalid_policy``
    on any validation failure.
    """
    if not isinstance(config, Mapping):
        raise SamplingError("invalid_policy")
    rules_raw = config.get("rules")
    if not isinstance(rules_raw, list):
        raise SamplingError("invalid_policy")
    if len(rules_raw) > 10:
        raise SamplingError("invalid_policy")

    rules: list[Rule] = []
    for item in rules_raw:
        if not isinstance(item, Mapping):
            raise SamplingError("invalid_policy")
        kind = item.get("kind")
        if kind not in ("error", "latency", "attribute", "probabilistic", "rate_limit"):
            raise SamplingError("invalid_policy")

        min_ms = item.get("min_ms")
        key = item.get("key")
        values_raw = item.get("values", ())
        ratio = item.get("ratio")
        per_second = item.get("per_second")

        if kind == "error":
            rule = Rule(kind="error")
        elif kind == "latency":
            if (
                min_ms is None
                or isinstance(min_ms, bool)
                or not isinstance(min_ms, (int, float))
                or min_ms < 0
            ):
                raise SamplingError("invalid_policy")
            rule = Rule(kind="latency", min_ms=float(min_ms))
        elif kind == "attribute":
            if not isinstance(key, str) or not key:
                raise SamplingError("invalid_policy")
            if not isinstance(values_raw, (list, tuple)):
                raise SamplingError("invalid_policy")
            if len(values_raw) > 100:
                raise SamplingError("invalid_policy")
            values: list[str | int | bool] = []
            for v in values_raw:
                if not isinstance(v, (str, int, bool)):
                    raise SamplingError("invalid_policy")
                values.append(v)
            rule = Rule(kind="attribute", key=key, values=tuple(values))
        elif kind == "probabilistic":
            if (
                ratio is None
                or isinstance(ratio, bool)
                or not isinstance(ratio, (int, float))
                or not (0.0 <= ratio <= 1.0)
            ):
                raise SamplingError("invalid_policy")
            rule = Rule(kind="probabilistic", ratio=float(ratio))
        elif kind == "rate_limit":
            if (
                per_second is None
                or isinstance(per_second, bool)
                or not isinstance(per_second, (int, float))
                or per_second <= 0
            ):
                raise SamplingError("invalid_policy")
            rule = Rule(kind="rate_limit", per_second=float(per_second))
        else:
            raise SamplingError("invalid_policy")
        rules.append(rule)

    return Policy(rules)


# ---------------------------------------------------------------------------
# TailSampler
# ---------------------------------------------------------------------------


class TailSampler:
    """Buffer complete traces before deciding, with bounded memory."""

    def __init__(
        self,
        policy: Policy,
        *,
        decision_wait_s: float = 10.0,
        max_traces: int = 50_000,
        max_spans_per_trace: int = 1_000,
        max_decisions: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if decision_wait_s < 0 or max_traces <= 0 or max_spans_per_trace <= 0 or max_decisions <= 0:
            raise SamplingError("invalid_policy")
        self._policy = policy
        self._decision_wait_s = decision_wait_s
        self._max_traces = max_traces
        self._max_spans_per_trace = max_spans_per_trace
        self._max_decisions = max_decisions
        self._clock = clock
        self._on_event = on_event

        self._buffered: dict[str, list[Span]] = {}
        self._first_seen: dict[str, float] = {}
        self._order: list[str] = []
        self._decisions: OrderedDict[str, Decision] = OrderedDict()
        self._decided_count = 0
        self._dropped_spans = 0
        self._forced_count = 0

    def add_spans(self, spans: Iterable[Span]) -> list[tuple[str, Decision]]:
        """Add spans, returning forced decisions and cached late-span decisions."""
        results: list[tuple[str, Decision]] = []
        for span in spans:
            _validate_span(span)
            trace_id = span["trace_id"]

            # Late span for an already decided trace: return cached decision.
            if trace_id in self._decisions:
                self._decisions.move_to_end(trace_id)
                results.append((trace_id, self._decisions[trace_id]))
                continue

            # New trace
            if trace_id not in self._buffered:
                self._buffered[trace_id] = []
                self._first_seen[trace_id] = self._clock()
                self._order.append(trace_id)

            # Add span if under limit
            if len(self._buffered[trace_id]) < self._max_spans_per_trace:
                self._buffered[trace_id].append(span)
            else:
                self._dropped_spans += 1
                self._emit("span_dropped", trace_id, False)

            # Force decisions when over max_traces
            while len(self._buffered) > self._max_traces:
                oldest_tid = self._order.pop(0)
                spans_list = self._buffered.pop(oldest_tid)
                del self._first_seen[oldest_tid]
                decision = self._policy.decide(spans_list)
                forced_decision = Decision(
                    keep=decision.keep,
                    rule=decision.rule,
                    forced=True,
                )
                self._cache_decision(oldest_tid, forced_decision)
                self._decided_count += 1
                self._forced_count += 1
                self._emit("forced", oldest_tid, forced_decision.keep)
                results.append((oldest_tid, forced_decision))

        return results

    def poll(self) -> list[tuple[str, Decision]]:
        """Return decisions for traces whose wait has elapsed."""
        results: list[tuple[str, Decision]] = []
        now = self._clock()
        while self._order:
            trace_id = self._order[0]
            if now - self._first_seen[trace_id] < self._decision_wait_s:
                break
            self._order.pop(0)
            spans_list = self._buffered.pop(trace_id)
            del self._first_seen[trace_id]
            decision = self._policy.decide(spans_list)
            final_decision = Decision(
                keep=decision.keep,
                rule=decision.rule,
                forced=False,
            )
            self._cache_decision(trace_id, final_decision)
            self._decided_count += 1
            self._emit("decided", trace_id, final_decision.keep)
            results.append((trace_id, final_decision))
        return results

    def stats(self) -> SamplerStats:
        """Return current statistics."""
        return SamplerStats(
            buffered_traces=len(self._buffered),
            decided=self._decided_count,
            dropped_spans=self._dropped_spans,
            forced=self._forced_count,
        )

    def _cache_decision(self, trace_id: str, decision: Decision) -> None:
        self._decisions[trace_id] = decision
        self._decisions.move_to_end(trace_id)
        if len(self._decisions) > self._max_decisions:
            self._decisions.popitem(last=False)

    def _emit(self, event: str, trace_id: str, keep: bool) -> None:
        if self._on_event is not None:
            self._on_event({"event": event, "trace_id": trace_id, "keep": keep})
