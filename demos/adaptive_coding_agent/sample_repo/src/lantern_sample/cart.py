"""Shopping-cart helpers with typed public data structures."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CartItem:
    """A purchasable item and the quantity selected by a customer."""

    name: str
    unit_price: float
    quantity: int = 1


def subtotal(items: list[CartItem]) -> float:
    return round(sum(item.unit_price * item.quantity for item in items), 2)
