# trysac-trace-sampling-policy

Tail-based trace sampling policies as a pure-Python library.

[![PyPI](https://img.shields.io/pypi/v/trysac-trace-sampling-policy)](https://pypi.org/project/trysac-trace-sampling-policy/)
[![Python](https://img.shields.io/pypi/pyversions/trysac-trace-sampling-policy)](https://pypi.org/project/trysac-trace-sampling-policy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

`trysac-trace-sampling-policy` evaluates ordered keep rules over complete traces, with a
bounded decision buffer and consistent decisions for spans arriving late. It is a testable,
in-process implementation of the ideas behind the OpenTelemetry Collector's tail sampling
processor, using only the Python standard library.

## Installation

```bash
pip install trysac-trace-sampling-policy
```

Python 3.10 or later is required.

## Usage

```python
from trace_sampling_policy import Policy, Rule, Span

policy = Policy(
    [
        Rule("error"),
        Rule("latency", min_ms=500),
    ]
)
span: Span = {
    "trace_id": "0af7651916cd43dd8448eb211c80319c",
    "span_id": "0123456789abcdef",
    "parent_span_id": None,
    "name": "checkout",
    "start_ns": 0,
    "end_ns": 600_000_000,  # 600 ms
    "status": "ERROR",
    "attributes": {},
}
print(policy.decide([span]))  # Decision(keep=True, rule='error')
```

## Features

- **Ordered keep rules:** error, latency, attribute, probabilistic, and rate_limit.
- **Bounded buffer:** `TailSampler` enforces `max_traces`, `max_spans_per_trace`, and
  `max_decisions`.
- **Consistent late-span decisions:** decided trace IDs are cached (LRU) so late spans
  receive the same decision and are never buffered again.
- **Injectable clock:** deterministic tests for time-based rules and decision waiting.
- **Typed errors:** all validation failures raise `SamplingError` with code `invalid_span`
  or `invalid_policy`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Security](docs/SECURITY.md)

## License

MIT
