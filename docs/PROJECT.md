# Project record

## Objective

Tail-based trace sampling policies: ordered keep rules for errors, latency, attributes, trace-id ratio and rate limits, a bounded decision buffer and cached late-span decisions

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 3900291 / 212038 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.3657 |

## Factory run u236 (measured from API usage)

| Date (UTC) | Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | generation | deepseek-v4-pro | yes | 1883 | 21124 | 0 | 3200 | 0.0431 |
| 2026-11-10 | fix-1 | deepseek-flash | no | 25182 | 36283 | 0 | 624896 | 0.0274 |
| 2026-11-10 | fix-2 | deepseek-flash | no | 36967 | 19624 | 0 | 521984 | 0.0189 |
| 2026-11-10 | fix-3 | deepseek-flash | no | 32114 | 17507 | 0 | 913664 | 0.0181 |
| 2026-11-10 | fix-4 | deepseek-flash | no | 15423 | 15429 | 0 | 207232 | 0.0122 |
| 2026-11-11 | fix-1 | deepseek-v4-pro | no | 25604 | 19835 | 0 | 144256 | 0.0593 |
| 2026-11-11 | fix-2 | deepseek-v4-pro | no | 26879 | 22892 | 0 | 199040 | 0.0674 |
| 2026-11-11 | fix-3 | deepseek-v4-pro | no | 14363 | 10680 | 0 | 136320 | 0.0336 |
| 2026-11-11 | fix-4 | deepseek-v4-pro | no | 13994 | 3980 | 0 | 90880 | 0.0191 |
| 2026-11-11 | audit | deepseek-flash | no | 42787 | 25645 | 0 | 563968 | 0.0235 |
| 2026-11-11 | fix-1 | deepseek-v4-pro | no | 13885 | 3039 | 0 | 145792 | 0.0184 |
| 2026-11-11 | docs | deepseek-flash | no | 99722 | 16000 | 0 | 256 | 0.0246 |

Total: $0.3657. Prices: deepseek line, as measured by its adapter. Providers serve the current version of each model id, so the date tells which version answered; versions, launch stages and price sources per line are in the factory's model register (docs/MODELS.md).
