"""Small numeric helpers."""


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole, rounded for display."""
    if whole == 0:
        return 0.0
    return round((part / whole) * 100, 1)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Return value constrained to the inclusive range."""
    if value < minimum:
        return minimum
    return value
