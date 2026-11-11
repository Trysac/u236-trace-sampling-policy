# Implement tail-based trace sampling as a pure-Python library

Status: accepted (generated, pending human review)

## Context

Tail sampling requires keeping complete traces before deciding, but home-made buffers often grow without bound or lose late spans. A testable, in-process library with ordered rules, bounded memory, and deterministic clocks addresses this.

## Decision

Implement Ordered keep rules (error, latency, attribute, probabilistic, rate_limit), a bounded TailSampler with cached decisions, and a config loader. Use only the Python standard library and an injectable clock for deterministic testing.

## Consequences

No runtime dependencies. Memory usage is bounded by configurable limits. Decisions for late spans are consistent. Rate limiting uses a token bucket with continuous refill. Errors are typed with a stable machine-readable code.
