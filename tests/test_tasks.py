"""Expected task answers are recomputed from the server tables, so bench/tasks.yaml cannot drift."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import yaml

from servers.inventory import CATALOG

ROOT = Path(__file__).resolve().parents[1]
TASKS = {task["id"]: task for task in yaml.safe_load((ROOT / "bench" / "tasks.yaml").read_text())["tasks"]}
PRICE = {sku: Decimal(str(row[2])) for sku, row in CATALOG.items()}
STOCK = {sku: row[3] for sku, row in CATALOG.items()}


def _category(name):
    return [sku for sku, row in CATALOG.items() if row[1] == name]


def _cheapest_in_stock(category):
    return min((sku for sku in _category(category) if STOCK[sku] > 0), key=PRICE.__getitem__)


def _quantities(text):
    return [(sku, int(quantity)) for sku, quantity in re.findall(r"(SKU-\d+)\s*x\s*(\d+)", text)]


def test_catalog_shape():
    assert len(CATALOG) == 14
    assert {row[1] for row in CATALOG.values()} == {"tea", "coffee", "cocoa", "matcha"}
    assert any(row[3] == 0 for row in CATALOG.values())
    assert all(Decimal(str(row[2])).as_tuple().exponent == -2 for row in CATALOG.values())


def test_price_total():
    task = TASKS["price_total"]
    pairs = re.findall(r"(\d+) x (SKU-\d+)", task["prompt"])
    assert len(pairs) == 4
    assert Decimal(str(task["grade"]["value"])) == sum(PRICE[sku] * int(quantity) for quantity, sku in pairs)


def test_cheapest_in_stock_order():
    task = TASKS["cheapest_in_stock_order"]
    tea = _category("tea")
    assert min(tea, key=PRICE.__getitem__) != _cheapest_in_stock("tea")  # the cheapest tea is out of stock
    assert task["grade"]["orders"] == [{"sku": _cheapest_in_stock("tea"), "quantity": 3}]


def test_note_summary():
    task = TASKS["note_summary"]
    notes = task["setup"]["notes"]
    counts = {key: int(notes[key].split(":")[1]) for key in ("region-north", "region-south", "region-west")}
    expected = f"total={sum(counts.values())} max={max(counts, key=counts.__getitem__)}"
    assert task["grade"] == {"type": "note", "key": "units-summary", "value": expected}


def test_cross_server_total():
    task = TASKS["cross_server_total"]
    items = _quantities(task["setup"]["notes"]["order-list"])
    assert len(items) == 4
    assert task["grade"]["value"] == f"{sum(PRICE[sku] * quantity for sku, quantity in items):.2f}"


def test_restock_cost():
    task = TASKS["restock_cost"]
    products = _category("cocoa") + _category("matcha")
    total = sum((10 - STOCK[sku]) * PRICE[sku] for sku in products if STOCK[sku] < 5)
    assert task["grade"] == {"type": "note", "key": "restock-cost", "value": f"{total:.2f}"}


def test_budget_order():
    task = TASKS["budget_order"]
    budget = Decimal(task["setup"]["notes"]["coffee-budget"])
    sku = _cheapest_in_stock("coffee")
    quantity = min(int(budget // PRICE[sku]), STOCK[sku])
    assert quantity >= 1
    orders, note = task["grade"]["checks"]
    assert orders == {"type": "orders_exact", "orders": [{"sku": sku, "quantity": quantity}]}
    assert note == {"type": "note", "key": "budget-order", "value": f"{sku} x{quantity}"}


def test_tasks_are_well_formed():
    assert len(TASKS) == 6
    tools = {"search_products", "get_product", "get_price", "get_price_v2", "get_stock", "place_order",
             "list_orders", "put_note", "get_note", "list_notes", "search_notes"}
    for task in TASKS.values():
        assert "FINAL:" in task["prompt"]
        assert not re.search(r"fault|chaos|fail|error|retry", task["prompt"], re.IGNORECASE)
        assert task["fault_targets"] and set(task["fault_targets"]) <= tools
