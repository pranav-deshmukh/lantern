def friendly_total(amount, currency="USD"):
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{amount:.2f}"
