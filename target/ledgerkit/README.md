# ledgerkit

A small, typed TypeScript library (Node 22, ESM) for billing back-ends:

| Module | What it does |
| --- | --- |
| `money` | Integer minor-unit `Money`, exact decimal parsing/formatting, rounding modes, remainder-safe allocation |
| `rounding` | Integer rounding that is robust to binary floating point noise |
| `currency` | `RateTable` with base-currency quotes, cross rates, single-rounding conversion, staleness checks |
| `dates` | Zone-free calendar dates (`YYYY-MM-DD`), month arithmetic with end-of-month clamping |
| `billing` | Anchored billing periods without drift, daily proration, mid-period plan changes |
| `invoice` | Invoice lines, discounts, per-line tax, issue / pay / void lifecycle, overdue checks |
| `numbering` | Yearly sequential invoice numbers |
| `client` | Fetch-based REST client: URL building, timeouts, retries with backoff and `Retry-After`, cursor pagination |

```bash
npm ci
npm test          # vitest
npm run typecheck # tsc --noEmit
```

This library is synthetic: it was written as a target codebase for the
`qa-agent-evals` benchmark and is not used in production.
