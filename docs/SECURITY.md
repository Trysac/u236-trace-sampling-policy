# Security

`trysac-trace-sampling-policy` is a pure in-memory library with no network or filesystem
operations. It does not handle secrets, credentials, or personal data beyond what a caller
places in span attributes or trace IDs.

## Input Validation

All function inputs that accept untrusted data (spans, configuration mappings) undergo
strict validation:

- Trace IDs must be 32 lowercase hex characters and not all zeros.
- Span IDs must be 16 lowercase hex characters.
- `end_ns` must be greater than or equal to `start_ns`.
- Attribute keys and string values have length limits.
- Policy rules are limited in count and field constraints.

Validation failures raise `SamplingError` with a stable `code`.

## Memory Bounds

`TailSampler` enforces configurable maximums for buffered traces, spans per trace, and
cached decisions. This prevents unbounded memory growth even under high span volume.

## Logging

The library uses `logging.getLogger(__name__)` and installs a `NullHandler`; it never logs
span contents or attributes.
