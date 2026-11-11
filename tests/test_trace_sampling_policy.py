"""Tests for trace_sampling_policy."""

from __future__ import annotations

import pytest

from trace_sampling_policy import (
    Decision,
    Policy,
    Rule,
    SamplerStats,
    SamplingError,
    Span,
    TailSampler,
    keep_by_ratio,
    load_policy,
)


class FakeClock:
    """Deterministic clock for tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt

    def set(self, t: float) -> None:
        self.now = t


def make_span(
    trace_id: str = "0af7651916cd43dd8448eb211c80319c",
    span_id: str = "0123456789abcdef",
    parent_span_id: str | None = None,
    name: str = "test",
    start_ns: int = 0,
    end_ns: int = 1_000_000,
    status: str = "OK",
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        start_ns=start_ns,
        end_ns=end_ns,
        status=status,  # type: ignore[arg-type]
        attributes=attributes or {},
    )


def test_error_rule_keeps() -> None:
    policy = Policy([Rule("error")])
    span = make_span(status="ERROR")
    decision = policy.decide([span])
    assert decision == Decision(keep=True, rule="error")


def test_latency_rule_keeps_when_duration_exceeds_min() -> None:
    policy = Policy([Rule("latency", min_ms=500)])
    span = make_span(start_ns=0, end_ns=600_000_000)  # 600 ms
    decision = policy.decide([span])
    assert decision == Decision(keep=True, rule="latency")


def test_latency_rule_drops_short_trace() -> None:
    policy = Policy([Rule("latency", min_ms=500)])
    span = make_span(start_ns=0, end_ns=100_000_000)  # 100 ms
    decision = policy.decide([span])
    assert decision == Decision(keep=False, rule=None)


def test_no_rules_drops() -> None:
    policy = Policy([])
    decision = policy.decide([make_span()])
    assert decision == Decision(keep=False, rule=None)


def test_keep_by_ratio_acceptance() -> None:
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    assert keep_by_ratio(trace_id, 0.5) is False
    assert keep_by_ratio(trace_id, 0.75) is True
    assert keep_by_ratio(trace_id, 1.0) is True
    assert keep_by_ratio(trace_id, 0.0) is False


def test_keep_by_ratio_invalid_trace_id() -> None:
    with pytest.raises(SamplingError) as exc:
        keep_by_ratio("XYZ", 0.5)
    assert exc.value.code == "invalid_span"


def test_keep_by_ratio_invalid_ratio() -> None:
    with pytest.raises(SamplingError) as exc:
        keep_by_ratio("0af7651916cd43dd8448eb211c80319c", 1.5)
    assert exc.value.code == "invalid_policy"


def test_attribute_rule_keeps_on_match() -> None:
    policy = Policy([Rule("attribute", key="http.route", values=("/checkout",))])
    span = make_span(attributes={"http.route": "/checkout"})
    decision = policy.decide([span])
    assert decision == Decision(keep=True, rule="attribute")


def test_attribute_rule_drops_on_non_match() -> None:
    policy = Policy([Rule("attribute", key="http.route", values=("/checkout",))])
    span = make_span(attributes={"http.route": "/cart"})
    decision = policy.decide([span])
    assert decision == Decision(keep=False, rule=None)


def test_attribute_rule_type_strictness() -> None:
    policy = Policy([Rule("attribute", key="flag", values=(True,))])
    span_true = make_span(attributes={"flag": True})
    assert policy.decide([span_true]) == Decision(keep=True, rule="attribute")
    span_int = make_span(attributes={"flag": 1})
    assert policy.decide([span_int]) == Decision(keep=False, rule=None)


def test_rate_limit_rule_with_clock() -> None:
    clock = FakeClock(100.0)
    policy = Policy([Rule("rate_limit", per_second=2)], clock=clock)
    span = make_span()
    # first two kept
    assert policy.decide([span]) == Decision(keep=True, rule="rate_limit")
    assert policy.decide([span]) == Decision(keep=True, rule="rate_limit")
    # third dropped
    assert policy.decide([span]) == Decision(keep=False, rule=None)
    # advance clock by 1 second: gain 2 tokens
    clock.advance(1.0)
    assert policy.decide([span]) == Decision(keep=True, rule="rate_limit")
    assert policy.decide([span]) == Decision(keep=True, rule="rate_limit")
    assert policy.decide([span]) == Decision(keep=False, rule=None)


def test_rate_limit_after_error_does_not_consume_tokens() -> None:
    clock = FakeClock(100.0)
    policy = Policy(
        [Rule("error"), Rule("rate_limit", per_second=1)],
        clock=clock,
    )
    error_span = make_span(status="ERROR")
    good_span = make_span(status="OK")

    # error rule keeps and should not consume rate_limit token
    assert policy.decide([error_span]) == Decision(keep=True, rule="error")
    # rate_limit still has full capacity: first good span keeps
    assert policy.decide([good_span]) == Decision(keep=True, rule="rate_limit")
    # now token consumed, next good span drops
    assert policy.decide([good_span]) == Decision(keep=False, rule=None)


def test_latency_rule_two_roots_uses_earliest_start() -> None:
    policy = Policy([Rule("latency", min_ms=100)])
    root1 = make_span(
        trace_id="0af7651916cd43dd8448eb211c80319c",
        span_id="1111111111111111",
        parent_span_id=None,
        start_ns=0,
        end_ns=200_000_000,  # 200 ms
    )
    root2 = make_span(
        trace_id="0af7651916cd43dd8448eb211c80319c",
        span_id="2222222222222222",
        parent_span_id=None,
        start_ns=50_000_000,
        end_ns=100_000_000,  # 50 ms
    )
    # earliest root is root1 with 200ms >=100ms, so keep
    decision = policy.decide([root1, root2])
    assert decision == Decision(keep=True, rule="latency")


def test_latency_rule_no_root_uses_global_extent() -> None:
    policy = Policy([Rule("latency", min_ms=100)])
    span1 = make_span(
        parent_span_id="3333333333333333",
        start_ns=100_000_000,
        end_ns=150_000_000,
    )
    span2 = make_span(
        parent_span_id="3333333333333333",
        start_ns=200_000_000,
        end_ns=300_000_000,
    )
    # global extent = 300ms - 100ms = 200ms >= 100ms
    decision = policy.decide([span1, span2])
    assert decision == Decision(keep=True, rule="latency")


def test_invalid_span_end_before_start() -> None:
    policy = Policy([Rule("error")])
    span = make_span(start_ns=10, end_ns=5)
    with pytest.raises(SamplingError) as exc:
        policy.decide([span])
    assert exc.value.code == "invalid_span"


def test_invalid_span_all_zero_trace_id() -> None:
    policy = Policy([Rule("error")])
    span = make_span(trace_id="00000000000000000000000000000000")
    with pytest.raises(SamplingError) as exc:
        policy.decide([span])
    assert exc.value.code == "invalid_span"


def test_invalid_span_bad_trace_id() -> None:
    policy = Policy([Rule("error")])
    span = make_span(trace_id="XYZ")
    with pytest.raises(SamplingError) as exc:
        policy.decide([span])
    assert exc.value.code == "invalid_span"


def test_load_policy_valid() -> None:
    config = {
        "rules": [
            {"kind": "error"},
            {"kind": "latency", "min_ms": 500},
            {"kind": "attribute", "key": "http.route", "values": ["/checkout", 42, True]},
            {"kind": "probabilistic", "ratio": 0.5},
            {"kind": "rate_limit", "per_second": 2},
        ]
    }
    policy = load_policy(config)
    assert isinstance(policy, Policy)
    assert len(policy._rules) == 5  # type: ignore[attr-defined]


def test_load_policy_invalid_ratio() -> None:
    config = {"rules": [{"kind": "probabilistic", "ratio": 1.5}]}
    with pytest.raises(SamplingError) as exc:
        load_policy(config)
    assert exc.value.code == "invalid_policy"


def test_load_policy_too_many_rules() -> None:
    rules = [{"kind": "error"}] * 11
    config = {"rules": rules}
    with pytest.raises(SamplingError) as exc:
        load_policy(config)
    assert exc.value.code == "invalid_policy"


def test_load_policy_values_too_long() -> None:
    values = list(range(101))
    config = {"rules": [{"kind": "attribute", "key": "k", "values": values}]}
    with pytest.raises(SamplingError) as exc:
        load_policy(config)
    assert exc.value.code == "invalid_policy"


def test_tail_sampler_wait_and_poll() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, decision_wait_s=10.0, clock=clock)
    span = make_span(status="ERROR")
    sampler.add_spans([span])
    assert sampler.poll() == []
    clock.advance(9.9)
    assert sampler.poll() == []
    clock.advance(0.1)  # now 10.0
    result = sampler.poll()
    assert len(result) == 1
    trace_id, decision = result[0]
    assert trace_id == span["trace_id"]
    assert decision == Decision(keep=True, rule="error")
    assert sampler.stats() == SamplerStats(buffered_traces=0, decided=1, dropped_spans=0, forced=0)


def test_tail_sampler_late_span_cached_decision() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, decision_wait_s=1.0, clock=clock)
    span = make_span(status="ERROR")
    sampler.add_spans([span])
    clock.advance(1.0)
    first_result = sampler.poll()
    assert first_result != []
    # late span arriving after decision
    late_span = make_span(status="OK", span_id="fedcba9876543210")
    late_results = sampler.add_spans([late_span])
    assert len(late_results) == 1
    trace_id, decision = late_results[0]
    assert trace_id == span["trace_id"]
    assert decision == first_result[0][1]  # same decision, forced=False
    # not buffered again
    assert sampler.stats().buffered_traces == 0


def test_tail_sampler_overflow_forces_oldest() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, max_traces=2, clock=clock)
    trace1 = "0af7651916cd43dd8448eb211c80319c"
    trace2 = "1af7651916cd43dd8448eb211c80319c"
    trace3 = "2af7651916cd43dd8448eb211c80319c"
    span1 = make_span(trace_id=trace1, status="ERROR")
    span2 = make_span(trace_id=trace2, status="OK")
    span3 = make_span(trace_id=trace3, status="OK")
    sampler.add_spans([span1, span2])
    assert sampler.stats().buffered_traces == 2
    results = sampler.add_spans([span3])
    # one forced decision for trace1
    assert len(results) == 1
    forced_tid, forced_decision = results[0]
    assert forced_tid == trace1
    assert forced_decision.forced is True
    assert forced_decision.keep is True  # error kept
    assert sampler.stats().buffered_traces == 2
    assert sampler.stats().forced == 1
    assert sampler.stats().decided == 1


def test_tail_sampler_overflow_many_traces_in_one_call() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, max_traces=2, clock=clock)
    spans = [make_span(trace_id=f"{i:032x}", status="ERROR") for i in range(1, 6)]
    results = sampler.add_spans(spans)
    # 5 new traces with max_traces=2: the first 3 are forced out immediately.
    assert len(results) == 3
    for _tid, decision in results:
        assert decision.forced is True
    assert sampler.stats().buffered_traces == 2
    assert sampler.stats().forced == 3
    assert sampler.stats().decided == 3


def test_tail_sampler_span_limit_drops() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, max_spans_per_trace=3, clock=clock)
    span_ids = [f"{i:016x}" for i in range(4)]
    spans = [make_span(span_id=sid) for sid in span_ids]
    sampler.add_spans(spans[:3])
    assert sampler.stats().dropped_spans == 0
    sampler.add_spans([spans[3]])
    assert sampler.stats().dropped_spans == 1
    assert sampler.stats().buffered_traces == 1


def test_tail_sampler_poll_empty() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, clock=clock)
    assert sampler.poll() == []


def test_tail_sampler_events() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    events: list[dict[str, object]] = []
    sampler = TailSampler(
        policy,
        decision_wait_s=1.0,
        max_traces=1,
        clock=clock,
        on_event=events.append,
    )
    span = make_span(status="ERROR")
    sampler.add_spans([span])
    clock.advance(1.0)
    sampler.poll()
    assert events == [{"event": "decided", "trace_id": span["trace_id"], "keep": True}]

    # overflow forced event
    clock.set(0.0)
    events.clear()
    sampler2 = TailSampler(
        policy,
        max_traces=1,
        clock=clock,
        on_event=events.append,
    )
    trace1 = "0af7651916cd43dd8448eb211c80319c"
    trace2 = "1af7651916cd43dd8448eb211c80319c"
    span1 = make_span(trace_id=trace1, status="ERROR")
    span2 = make_span(trace_id=trace2, status="OK")
    sampler2.add_spans([span1])
    sampler2.add_spans([span2])
    assert events == [{"event": "forced", "trace_id": trace1, "keep": True}]

    # span dropped event
    events.clear()
    sampler3 = TailSampler(
        policy,
        max_spans_per_trace=1,
        clock=clock,
        on_event=events.append,
    )
    span_a = make_span(span_id="aaaaaaaaaaaaaaaa")
    span_b = make_span(span_id="bbbbbbbbbbbbbbbb")
    sampler3.add_spans([span_a])
    sampler3.add_spans([span_b])
    assert events == [{"event": "span_dropped", "trace_id": span_a["trace_id"], "keep": False}]


def test_tail_sampler_lru_cache_eviction() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, max_decisions=2, clock=clock)
    # generate traces and decide them
    spans = []
    for i in range(1, 4):
        trace_id = f"{i:032x}"
        span = make_span(trace_id=trace_id, status="ERROR")
        spans.append(span)
    sampler.add_spans(spans)
    clock.advance(10.0)
    results = sampler.poll()
    assert len(results) == 3
    # cache size limited to 2
    assert len(sampler._decisions) == 2  # type: ignore[attr-defined]


def test_tail_sampler_cached_span_not_buffered() -> None:
    clock = FakeClock(0.0)
    policy = Policy([Rule("error")])
    sampler = TailSampler(policy, decision_wait_s=1.0, clock=clock)
    span = make_span(status="ERROR")
    sampler.add_spans([span])
    clock.advance(1.0)
    sampler.poll()
    # late span
    late_span = make_span(span_id="abcdefabcdefabcd", status="OK")
    sampler.add_spans([late_span])
    # should not be buffered
    assert sampler.stats().buffered_traces == 0


def test_policy_validation_too_many_rules() -> None:
    rules = [Rule("error")] * 11
    with pytest.raises(SamplingError) as exc:
        Policy(rules)
    assert exc.value.code == "invalid_policy"


def test_policy_validation_latency_negative_min() -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("latency", min_ms=-1)])
    assert exc.value.code == "invalid_policy"


def test_policy_validation_rate_limit_zero() -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("rate_limit", per_second=0)])
    assert exc.value.code == "invalid_policy"


def test_policy_validation_attribute_missing_key() -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("attribute", values=("x",))])
    assert exc.value.code == "invalid_policy"


def test_decide_empty_spans_drops() -> None:
    assert Policy([Rule("error")]).decide([]) == Decision(keep=False, rule=None)


def test_probabilistic_rule_decide() -> None:
    span = make_span()
    assert Policy([Rule("probabilistic", ratio=0.0)]).decide([span]) == Decision(
        keep=False, rule=None
    )
    assert Policy([Rule("probabilistic", ratio=1.0)]).decide([span]) == Decision(
        keep=True, rule="probabilistic"
    )


def test_invalid_span_id() -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("error")]).decide([make_span(span_id="XYZ")])
    assert exc.value.code == "invalid_span"


def test_invalid_parent_span_id() -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("error")]).decide([make_span(parent_span_id="XYZ")])
    assert exc.value.code == "invalid_span"


@pytest.mark.parametrize(
    "bad_span",
    [
        {},
        "not-a-span",
        {**make_span(), "name": ""},
        {**make_span(), "name": "x" * 2000},
        {**make_span(), "start_ns": "0"},
        {**make_span(), "status": "BAD"},
        {**make_span(), "attributes": []},
        {**make_span(), "attributes": {1: "x"}},
        {**make_span(), "attributes": {"k": [1]}},
        {**make_span(), "attributes": {"k": "x" * 2000}},
    ],
)
def test_invalid_span_shape(bad_span: object) -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([Rule("error")]).decide([bad_span])  # type: ignore[list-item]
    assert exc.value.code == "invalid_span"


@pytest.mark.parametrize(
    "rule",
    [
        Rule("latency"),
        Rule("probabilistic"),
        Rule("attribute", key="k", values=tuple(range(101))),
        Rule("attribute", key="k", values=(1.5,)),  # type: ignore[arg-type]
        Rule("bogus"),  # type: ignore[arg-type]
    ],
)
def test_policy_validation_variants(rule: Rule) -> None:
    with pytest.raises(SamplingError) as exc:
        Policy([rule])
    assert exc.value.code == "invalid_policy"


@pytest.mark.parametrize(
    "config",
    [
        [],
        {},
        {"rules": "error"},
        {"rules": ["error"]},
        {"rules": [{"kind": "bogus"}]},
        {"rules": [{"kind": "latency"}]},
        {"rules": [{"kind": "attribute", "values": ["x"]}]},
        {"rules": [{"kind": "attribute", "key": "k", "values": "x"}]},
        {"rules": [{"kind": "attribute", "key": "k", "values": [1.5]}]},
        {"rules": [{"kind": "rate_limit"}]},
        {"rules": [{"kind": "rate_limit", "per_second": -1}]},
    ],
)
def test_load_policy_invalid_configs(config: object) -> None:
    with pytest.raises(SamplingError) as exc:
        load_policy(config)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_policy"


def test_tail_sampler_invalid_limits() -> None:
    with pytest.raises(SamplingError) as exc:
        TailSampler(Policy([Rule("error")]), decision_wait_s=-1.0)
    assert exc.value.code == "invalid_policy"
