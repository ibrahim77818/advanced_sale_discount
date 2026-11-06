# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import BaseCase

from ..utils.discount_engine import EngineError, allocate, build_plan, compose_discount


def _items(*bases, **extra):
    return [dict({'key': i, 'name': 'L%s' % i, 'subtotal': b, 'total': b * 1.15}, **{
        k: v[i] for k, v in extra.items()}) for i, b in enumerate(bases)]


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestDiscountEngine(BaseCase):

    def assertAmounts(self, actual, expected, places=6):
        self.assertEqual(len(actual), len(expected))
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got, want, places=places)

    def test_compose_discount(self):
        self.assertAlmostEqual(compose_discount(0, 10), 10.0)
        self.assertAlmostEqual(compose_discount(5, 10), 14.5)
        self.assertAlmostEqual(compose_discount(100, 10), 100.0)
        self.assertAlmostEqual(compose_discount(20, 0), 20.0)

    def test_allocate_sums_exactly(self):
        parts = allocate(100.0, [300.0, 233.31, 466.69], 0.01)
        self.assertAmounts(parts, [30.0, 23.33, 46.67])
        self.assertAlmostEqual(sum(parts), 100.0, places=6)
        # three equal weights: one cent must go somewhere, deterministically
        parts = allocate(0.10, [1, 1, 1], 0.01)
        self.assertAlmostEqual(sum(parts), 0.10, places=6)
        self.assertAmounts(parts, [0.04, 0.03, 0.03])

    def test_allocate_three_decimals_currency(self):
        parts = allocate(1.0, [10.0, 20.0, 30.0], 0.001)
        self.assertAlmostEqual(sum(parts), 1.0, places=9)
        self.assertAmounts(parts, [0.167, 0.333, 0.5], places=9)

    def test_allocate_zero_weight_gets_nothing(self):
        parts = allocate(10.0, [0.0, 1.0, 1.0], 0.01)
        self.assertEqual(parts[0], 0.0)
        self.assertAlmostEqual(sum(parts), 10.0)

    def test_allocate_invalid_weights(self):
        with self.assertRaises(EngineError):
            allocate(10.0, [0.0, 0.0], 0.01)
        with self.assertRaises(EngineError):
            allocate(10.0, [-1.0, 2.0], 0.01)

    def test_plan_percent(self):
        plan = build_plan(_items(300.0, 233.31, 466.69), 'proportional', 'percent', 10.0,
                          'subtotal', None, 0.01)
        self.assertEqual({p['extra'] for p in plan.values()}, {10.0})
        self.assertAlmostEqual(sum(p['target'] for p in plan.values()), 100.0)

    def test_plan_fixed(self):
        plan = build_plan(_items(300.0, 233.31, 466.69), 'proportional', 'fixed', 100.0,
                          'subtotal', None, 0.01)
        self.assertAlmostEqual(plan[0]['extra'], 10.0)
        self.assertAlmostEqual(sum(p['target'] for p in plan.values()), 100.0)

    def test_plan_fixed_whole_amount(self):
        plan = build_plan(_items(40.0, 60.0), 'proportional', 'fixed', 100.0,
                          'subtotal', None, 0.01)
        self.assertEqual({p['extra'] for p in plan.values()}, {100.0})

    def test_plan_errors(self):
        items = _items(100.0, 50.0)
        for value, dtype, code in ((0.0, 'percent', 'value_not_positive'),
                                   (-5.0, 'fixed', 'value_not_positive'),
                                   (100.01, 'percent', 'percent_over_100'),
                                   (150.01, 'fixed', 'amount_over_base')):
            with self.assertRaises(EngineError) as ctx:
                build_plan(items, 'proportional', dtype, value, 'subtotal', None, 0.01)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(EngineError) as ctx:
            build_plan([], 'proportional', 'percent', 10, 'subtotal', None, 0.01)
        self.assertEqual(ctx.exception.code, 'no_lines')

    def test_plan_weighted(self):
        items = _items(100.0, 100.0, weight=[3.0, 1.0])
        plan = build_plan(items, 'weighted', 'fixed', 40.0, 'subtotal', 'weight', 0.01)
        self.assertAlmostEqual(plan[0]['target'], 30.0)
        self.assertAlmostEqual(plan[1]['target'], 10.0)
        # a weight pushing one line above 100% is refused
        items = _items(10.0, 1000.0, weight=[1000.0, 1.0])
        with self.assertRaises(EngineError) as ctx:
            build_plan(items, 'weighted', 'fixed', 500.0, 'subtotal', 'weight', 0.01)
        self.assertEqual(ctx.exception.code, 'line_over_100')
        with self.assertRaises(EngineError) as ctx:
            build_plan(_items(100.0, 100.0, weight=[0.0, 0.0]), 'weighted', 'fixed', 10.0,
                       'subtotal', 'weight', 0.01)
        self.assertEqual(ctx.exception.code, 'invalid_weights')

    def test_plan_line_percent_and_amount(self):
        plan = build_plan(_items(100.0, 100.0, line_percent=[10.0, 0.0]), 'weighted', None, 0,
                          'subtotal', 'line_percent', 0.01)
        self.assertEqual(plan[0]['extra'], 10.0)
        self.assertEqual(plan[1]['extra'], 0.0)
        plan = build_plan(_items(100.0, 100.0, line_amount=[15.0, 5.0]), 'weighted', None, 0,
                          'subtotal', 'line_amount', 0.01)
        self.assertAlmostEqual(plan[0]['extra'], 15.0)
        self.assertAlmostEqual(plan[1]['target'], 5.0)
        with self.assertRaises(EngineError) as ctx:
            build_plan(_items(100.0, line_amount=[100.01]), 'weighted', None, 0,
                       'subtotal', 'line_amount', 0.01)
        self.assertEqual(ctx.exception.code, 'line_amount_range')
        with self.assertRaises(EngineError) as ctx:
            build_plan(_items(100.0, line_percent=[101.0]), 'weighted', None, 0,
                       'subtotal', 'line_percent', 0.01)
        self.assertEqual(ctx.exception.code, 'line_percent_range')
        with self.assertRaises(EngineError) as ctx:
            build_plan(_items(100.0, line_percent=[0.0]), 'weighted', None, 0,
                       'subtotal', 'line_percent', 0.01)
        self.assertEqual(ctx.exception.code, 'nothing_to_apply')

    def test_plan_tax_included_base(self):
        plan = build_plan(_items(200.0), 'proportional', 'fixed', 23.0, 'total', None, 0.01)
        self.assertAlmostEqual(plan[0]['extra'], 10.0)
