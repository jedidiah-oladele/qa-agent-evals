"""Import products from CSV exports produced by spreadsheets and other shops.

The importer is forgiving about layout (header case, spacing, blank lines,
column order, a UTF-8 byte order mark) and strict about values. Invalid rows
are reported with the line on which the record starts and never imported.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .catalog import Product
from .errors import CsvFormatError
from .money import Money, exponent_for

REQUIRED_COLUMNS = ("sku", "name", "price")
OPTIONAL_COLUMNS = ("category", "tax_category", "weight_grams")

_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


@dataclass(frozen=True)
class RowError:
    line: int
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}"
        return f"{where}: {self.field}: {self.message}" if self.field else f"{where}: {self.message}"


@dataclass
class ImportResult:
    products: list[Product] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_header(name: str) -> str:
    """``' Unit Price '`` -> ``'unit_price'``; also drops a leading BOM."""
    return name.lstrip("\ufeff").strip().lower().replace(" ", "_").replace("-", "_")


def parse_price(text: str, currency: str) -> Decimal:
    """Parse a non-negative price such as ``12.50`` or ``1,234.50``.

    Thousands separators must group digits in threes. More decimal places than
    the currency allows is an error rather than a silent rounding.
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("price is empty")
    if "," in cleaned:
        if not _THOUSANDS.match(cleaned):
            raise ValueError(f"malformed thousands separators in {text!r}")
        cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a number: {text!r}")
    if value < 0:
        raise ValueError("price cannot be negative")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > exponent_for(currency):
        raise ValueError(f"too many decimal places for {currency}: {text!r}")
    return value


def _parse_weight(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    if not cleaned.isdigit():
        raise ValueError(f"weight must be a whole number of grams, got {text!r}")
    return int(cleaned)


def import_products(source: Iterable[str], *, currency: str = "USD") -> ImportResult:
    """Import products from an iterable of CSV lines (an open file works)."""
    reader = csv.reader(source)
    result = ImportResult()

    header: list[str] | None = None
    previous_end = 0
    for row in reader:
        start_line = previous_end + 1
        previous_end = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [normalize_header(cell) for cell in row]
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                raise CsvFormatError(f"missing required column(s): {', '.join(missing)}")
            seen_skus: dict[str, int] = {}
            continue

        if len(row) != len(header):
            result.errors.append(RowError(start_line, None, f"expected {len(header)} fields, got {len(row)}"))
            continue
        record = {name: value.strip() for name, value in zip(header, row)}
        errors_before = len(result.errors)

        sku = record["sku"]
        if not sku:
            result.errors.append(RowError(start_line, "sku", "sku is empty"))
        elif sku in seen_skus:
            result.errors.append(
                RowError(start_line, "sku", f"duplicate sku {sku} (first seen on line {seen_skus[sku]})")
            )
        if not record["name"]:
            result.errors.append(RowError(start_line, "name", "name is empty"))
        try:
            price = parse_price(record["price"], currency)
        except ValueError as exc:
            result.errors.append(RowError(start_line, "price", str(exc)))
        try:
            weight = _parse_weight(record.get("weight_grams", ""))
        except ValueError as exc:
            result.errors.append(RowError(start_line, "weight_grams", str(exc)))

        if len(result.errors) > errors_before:
            continue
        seen_skus[sku] = start_line
        result.products.append(
            Product(
                sku=sku,
                name=record["name"],
                unit_price=Money(price, currency),
                category=record.get("category") or "general",
                tax_category=record.get("tax_category") or "standard",
                weight_grams=weight,
            )
        )

    if header is None:
        raise CsvFormatError("file is empty")
    return result


def load_products(path: str | Path, *, currency: str = "USD") -> ImportResult:
    """Import products from a CSV file on disk (UTF-8, with or without BOM)."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return import_products(handle, currency=currency)
