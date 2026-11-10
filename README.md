# trace-sampling-policy

[![PyPI version](https://img.shields.io/pypi/v/trysac-trace-sampling-policy)](https://pypi.org/project/trysac-trace-sampling-policy/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-trace-sampling-policy)](LICENSE)
[![CI](https://github.com/Trysac/u236-trace-sampling-policy/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u236-trace-sampling-policy/actions/workflows/ci.yml)

Tail-based trace sampling policies: ordered keep rules for errors, latency, attributes, trace-id ratio and rate limits, a bounded decision buffer and cached late-span decisions

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-trace-sampling-policy
# or
uv add trysac-trace-sampling-policy
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import trace_sampling_policy

# normalize() trims surrounding whitespace and lower-cases the text.
print(trace_sampling_policy.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    trace_sampling_policy.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
