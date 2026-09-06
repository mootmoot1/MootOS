"""Synthetic GP-A eval fixture (case refactor_001). NOT production code.

Disposable, deterministic fixture: frozen "before" state of eval case
refactor_001 (behavior_preserving_refactor). ``quote_standard`` and
``quote_bulk`` duplicate the same discount-then-tax arithmetic; the task
is to remove the duplication without changing either function's output
for any input.
"""


def quote_standard(unit_price, quantity, discount_rate, tax_rate):
    subtotal = unit_price * quantity
    discounted = subtotal - (subtotal * discount_rate)
    total = discounted + (discounted * tax_rate)
    return round(total, 2)


def quote_bulk(unit_price, quantity, discount_rate, tax_rate):
    subtotal = unit_price * quantity
    discounted = subtotal - (subtotal * discount_rate)
    total = discounted + (discounted * tax_rate)
    return round(total, 2)
