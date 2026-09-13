from lantern_sample import CartItem, friendly_total, percentage, subtotal


def test_subtotal_multiplies_unit_prices_by_quantity() -> None:
    items = [CartItem("Notebook", 3.5, 2), CartItem("Pen", 1.25, 3)]

    assert subtotal(items) == 10.75


def test_friendly_total_formats_default_currency() -> None:
    assert friendly_total(10.75) == "$10.75"


def test_percentage_handles_zero_denominator() -> None:
    assert percentage(3, 0) == 0.0
