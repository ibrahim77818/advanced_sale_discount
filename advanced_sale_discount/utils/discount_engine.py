# -*- coding: utf-8 -*-
"""Pure allocation engine for advanced_sale_discount.

This module holds no ORM code: it only works on plain Python values so that
the arithmetic (allocation, rounding, percentage composition) is shared by
the wizard preview and the real application on sales orders and invoices,
and can be unit tested in isolation.
"""
import math

from odoo.tools import float_compare, float_is_zero, float_round

PERCENT_EPSILON = 1e-9


class EngineError(Exception):
    """Validation error raised by the engine.

    ``code`` identifies the problem; ``params`` carry the values used to
    build a translated message in the ORM layer.
    """

    def __init__(self, code, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def compose_discount(base_percent, extra_percent):
    """Return the single discount equivalent to ``base`` then ``extra``.

    A line already discounted by 5% that receives an extra 10% ends up at
    100 - 95 * 90 / 100 = 14.5%.
    """
    base_percent = base_percent or 0.0
    extra_percent = extra_percent or 0.0
    return 100.0 - (100.0 - base_percent) * (100.0 - extra_percent) / 100.0


def allocate(total, weights, precision_rounding):
    """Split ``total`` over ``weights`` without any rounding leakage.

    Uses the largest remainder method on the currency's smallest unit, so the
    returned amounts are all rounded to ``precision_rounding`` and always sum
    exactly to the rounded ``total``.
    """
    if not weights:
        return []
    if any(w < 0 for w in weights):
        raise EngineError('invalid_weights')
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise EngineError('invalid_weights')
    total = float_round(total, precision_rounding=precision_rounding)
    units = int(round(total / precision_rounding))
    sign = -1 if units < 0 else 1
    units = abs(units)
    raw = [units * w / weight_sum for w in weights]
    floors = [int(math.floor(r + PERCENT_EPSILON)) for r in raw]
    remainder = units - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - floors[i]), i))
    for index in order[:max(remainder, 0)]:
        floors[index] += 1
    return [
        float_round(sign * f * precision_rounding, precision_rounding=precision_rounding)
        for f in floors
    ]


def build_plan(items, mode, discount_type, value, base_key, weighted_method, precision_rounding):
    """Compute the per-line discount plan.

    :param items: list of dicts with keys ``key``, ``name``, ``subtotal``,
        ``total`` and optionally ``weight``, ``line_percent``, ``line_amount``.
    :param mode: ``proportional``, ``weighted`` or ``line``.
    :param discount_type: ``percent`` or ``fixed``.
    :param base_key: ``subtotal`` (tax excluded) or ``total`` (tax included).
    :return: dict ``key -> {'extra': percent, 'target': amount}`` where
        ``extra`` is the additional discount (%) to compose with the line's
        current discount and ``target`` the discount amount expected on that
        line, expressed in ``base_key`` terms.
    """
    if not items:
        raise EngineError('no_lines')
    rounding = precision_rounding
    bases = [it[base_key] for it in items]
    plan = {}

    if mode == 'weighted' and weighted_method == 'line_percent':
        for it, base in zip(items, bases):
            percent = it.get('line_percent') or 0.0
            if percent < 0 or percent > 100:
                raise EngineError('line_percent_range', line=it['name'])
            plan[it['key']] = {
                'extra': percent,
                'target': float_round(base * percent / 100.0, precision_rounding=rounding),
            }
        if all(float_is_zero(p['extra'], precision_digits=6) for p in plan.values()):
            raise EngineError('nothing_to_apply')
        return plan

    if mode == 'weighted' and weighted_method == 'line_amount':
        for it, base in zip(items, bases):
            amount = float_round(it.get('line_amount') or 0.0, precision_rounding=rounding)
            if amount < 0 or float_compare(amount, base, precision_rounding=rounding) > 0:
                raise EngineError('line_amount_range', line=it['name'])
            plan[it['key']] = {
                'extra': min(amount / base * 100.0, 100.0) if base else 0.0,
                'target': amount,
            }
        if all(float_is_zero(p['target'], precision_rounding=rounding) for p in plan.values()):
            raise EngineError('nothing_to_apply')
        return plan

    # Modes driven by one global value.
    if not value or value <= 0:
        raise EngineError('value_not_positive')
    total_base = sum(bases)
    if discount_type == 'percent':
        if value > 100:
            raise EngineError('percent_over_100')
        total = float_round(total_base * value / 100.0, precision_rounding=rounding)
    else:
        total = float_round(value, precision_rounding=rounding)
        if float_compare(total, total_base, precision_rounding=rounding) > 0:
            raise EngineError('amount_over_base', amount=total, base=total_base)

    if mode == 'weighted':
        weights = [base * (it.get('weight') or 0.0) for it, base in zip(items, bases)]
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise EngineError('invalid_weights')
    else:
        weights = bases

    targets = allocate(total, weights, rounding)
    for it, base, target in zip(items, bases, targets):
        if discount_type == 'percent' and mode != 'weighted':
            extra = value
        else:
            extra = target / base * 100.0 if base else 0.0
        if extra > 100.0 + PERCENT_EPSILON:
            raise EngineError('line_over_100', line=it['name'])
        plan[it['key']] = {'extra': min(extra, 100.0), 'target': target}
    return plan
