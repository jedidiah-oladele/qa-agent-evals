# shopcore

A small, typed Python 3.12 library for the money side of an online shop:

| Module | What it does |
| --- | --- |
| `money` | `Money` value type on `Decimal`, per-currency minor units, half-up rounding, cent-exact allocation |
| `catalog`, `order` | Products, catalog lookup, orders and line items |
| `discounts` | Percentage, fixed-amount and buy-X-get-Y rules, priority ordering, stacking vs exclusive discounts, expiry |
| `tax` | Tax regions with standard/reduced/exempt categories, tax-inclusive regions, per-line or per-order rounding |
| `shipping` | Weight tiers, extra-kilogram pricing, free shipping over a discounted-subtotal threshold |
| `pricing` | `PricingEngine.quote(order)`: discounts, then shipping, then tax, then totals |
| `inventory` | Stock levels, reservations with time-to-live, commit/release, all-or-nothing multi-SKU reservations |
| `payments` | Async capture with exponential backoff, jitter and idempotency keys; bounded-concurrency batch charging |
| `csv_import` | Forgiving-layout, strict-value product CSV import with per-line error reports |
| `testing` | `ScriptedGateway` and `RecordingSleep` test doubles |

No runtime dependencies. Tests use pytest:

```bash
pytest            # from this directory; pyproject.toml sets pythonpath=src
```

This library is synthetic: it was written as a target codebase for the
`qa-agent-evals` benchmark and is not used in production.
