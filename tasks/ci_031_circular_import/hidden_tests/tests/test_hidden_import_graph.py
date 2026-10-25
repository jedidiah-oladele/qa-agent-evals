"""Import-order independence: every module and public name must import first, in a fresh interpreter."""

import ast
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "shopcore"
MODULES = [
    "catalog",
    "clock",
    "csv_import",
    "discounts",
    "errors",
    "inventory",
    "money",
    "order",
    "payments",
    "pricing",
    "shipping",
    "tax",
    "testing",
]


def fresh(code: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_in_fresh_interpreter(module):
    result = fresh(f"import shopcore.{module}")
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.parametrize(
    "name",
    ["ShippingPolicy", "WeightTier", "TaxTable", "TaxRounding", "default_tax_table", "PricingEngine", "Money"],
)
def test_public_name_imports_first_in_fresh_interpreter(name):
    result = fresh(f"from shopcore import {name}")
    assert result.returncode == 0, result.stderr[-2000:]


def test_quote_works_when_tax_and_shipping_load_before_pricing():
    code = """
from decimal import Decimal
from shopcore.tax import default_tax_table
from shopcore.shipping import ShippingPolicy, WeightTier
from shopcore.pricing import PricingEngine
from shopcore import FixedClock, Money, Order, Product
from datetime import UTC, datetime

usd = lambda a: Money.of(a, "USD")
order = Order("USD", "US-CA")
order.add(Product("LAMP-7", "Desk lamp", usd("2.00"), weight_grams=1200), 2)
policy = ShippingPolicy(tiers=(WeightTier(1000, usd("5.00")), WeightTier(3000, usd("9.00"))))
engine = PricingEngine(default_tax_table(), shipping=policy, clock=FixedClock(datetime(2026, 5, 1, tzinfo=UTC)))
quote = engine.quote(order)
print(quote.shipping.amount, quote.tax_total.amount, quote.total.amount)
"""
    result = fresh(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == ["9.00", "0.29", "13.29"]


def _module_level_imports(tree: ast.Module, module: str) -> set[str]:
    """shopcore modules imported at module level (not in functions or TYPE_CHECKING blocks)."""
    found: set[str] = set()

    def visit(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.If):
                test = ast.unparse(node.test)
                if "TYPE_CHECKING" not in test:
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1 or (node.level == 0 and (node.module or "").split(".")[0] == "shopcore"):
                    parts = (node.module or "").split(".")
                    if node.level == 0:
                        parts = parts[1:]
                    if parts and parts[0]:
                        found.add(parts[0])
                    else:
                        for alias in node.names:
                            found.add(alias.name if (PACKAGE / f"{alias.name}.py").exists() else "__init__")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "shopcore":
                        found.add(parts[1] if len(parts) > 1 else "__init__")

    visit(tree.body)
    found.discard(module)
    return found


def test_module_level_import_graph_has_no_cycles():
    graph = {}
    for path in sorted(PACKAGE.glob("*.py")):
        graph[path.stem] = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")), path.stem)
    state: dict[str, int] = {}
    stack: list[str] = []

    def walk(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                pytest.fail("import cycle: " + " -> ".join(cycle))
            if nxt not in state:
                walk(nxt)
        stack.pop()
        state[node] = 2

    for name in sorted(graph):
        if name not in state:
            walk(name)


def test_importing_the_package_stays_lazy():
    result = fresh(
        "import sys, shopcore\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('shopcore.'))\n"
        "print(','.join(loaded))"
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == ""


def test_shipping_weight_still_counts_quantity():
    from shopcore import LineItem, Money, Product, ShippingPolicy, WeightTier

    policy = ShippingPolicy(tiers=(WeightTier(500, Money.of("4.00", "USD")),), per_extra_kg=Money.of("1.50", "USD"))
    lines = [LineItem(Product("JAR-3", "Jar", Money.of("3.00", "USD"), weight_grams=400), 3)]
    assert policy.quote(lines, Money.of("9.00", "USD")) == Money.of("5.50", "USD")


def test_per_line_tax_still_rounds_half_up():
    from shopcore.money import Money
    from shopcore.tax import compute_taxes

    taxes = compute_taxes([Money.of("2.00", "USD"), Money.of("-2.00", "USD")], [Decimal("0.0725")] * 2)
    assert [t.amount for t in taxes] == [Decimal("0.15"), Decimal("-0.15")]
