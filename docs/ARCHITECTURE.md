# Architecture

## Design Overview

`trysac-trace-sampling-policy` is a single-module Python library that provides tail-based
trace sampling decisions. It deliberately has no runtime dependencies and relies only on
Python's standard library.

### Core Components

1. **Span** (TypedDict): the minimal span representation required for sampling decisions.
2. **Rule**: a frozen dataclass describing one keep condition.
3. **Policy**: an ordered, immutable list of rules with a mutable token-bucket state for
   `rate_limit` rules. `decide()` evaluates rules sequentially and returns the first
   match or a drop decision.
4. **TailSampler**: buffers spans until a decision wait elapses, enforces resource limits,
   and caches decisions for late spans.
5. **load_policy**: validates and builds a `Policy` from a configuration mapping.

### Key Decisions

- **Ordered evaluation:** rules are applied in the order given; the first keep wins. This
  matches the OpenTelemetry Collector's tail sampling processor philosophy and makes
  behavior predictable.
- **Deterministic time:** all time-dependent behavior uses an injectable clock
  (default `time.monotonic`), enabling reproducible tests.
- **Bounded memory:** every collection (`buffered traces`, `spans per trace`, `decisions`)
  has a configurable maximum. Overflow forces a decision for the oldest trace and LRU
  evicts old decisions.
- **Error typing:** all validation errors raise `SamplingError` with a machine-readable
  `code` attribute (`invalid_span` or `invalid_policy`).

### Probabilistic Sampling

`keep_by_ratio` follows the OpenTelemetry consistent probability sampling convention:
keep a trace when the integer value of the rightmost 56 bits of its trace ID is greater
than or equal to `2**56 - int(ratio * 2**56)`.

### Out of Scope

- OTLP decoding or encoding.
- Exporting sampled spans.
- Adjusting sampling probability in `tracestate`.
- Distributed buffers across collector instances.
