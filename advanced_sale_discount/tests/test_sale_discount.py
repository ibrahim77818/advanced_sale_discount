# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestSaleDiscount(AsdCommon):

    # ------------------------------------------------------------------
    # Mode A - proportional
    # ------------------------------------------------------------------
    def test_proportional_percent(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        lines = self._regular_lines(order)
        self.assertEqual(lines.mapped('discount'), [10.0, 10.0, 10.0])
        self.assertTrue(all(lines.mapped('asd_discount_applied')))
        self.assertFalse(self._discount_lines(order))
        self.assertAlmostEqual(order.amount_untaxed, 900.0, places=2)
        self.assertAlmostEqual(order.asd_discount_total, 100.0, places=2)
        self.assertAlmostEqual(order.asd_discount_target, 100.0, places=2)
        self.assertEqual(order.asd_discount_mode, 'proportional')
        self.assertFalse(order.asd_discount_stale)

    def test_proportional_percent_composes_existing_discount(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15, discount=5.0),
            self._line(self.prod_b, 1, 100.0, self.tax_15),
        ])
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        line_a, line_b = order.order_line
        self.assertAlmostEqual(line_a.discount, 14.5)
        self.assertAlmostEqual(line_a.asd_base_discount, 5.0)
        self.assertAlmostEqual(line_b.discount, 10.0)
        self.assertAlmostEqual(order.amount_untaxed, 85.5 + 90.0, places=2)

    def test_proportional_fixed_exact(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=100.0)
        self.assertAlmostEqual(order.amount_untaxed, 900.0, places=2)
        self.assertFalse(self._discount_lines(order), 'No rounding line needed here')

    def test_proportional_fixed_rounding_adjustment_line(self):
        order = self._create_order([self._line(self.prod_a, 1, 999.99, self.tax_15)])
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=33.33)
        self.assertAlmostEqual(order.order_line[0].discount, 3.33)
        adjustment = self._discount_lines(order)
        self.assertEqual(len(adjustment), 1)
        self.assertEqual(adjustment.tax_id, self.tax_15)
        self.assertEqual(adjustment.product_id, self.discount_product)
        self.assertAlmostEqual(order.amount_untaxed, 999.99 - 33.33, places=2)

    def test_proportional_fixed_ignore_rounding(self):
        order = self._create_order([self._line(self.prod_a, 1, 999.99, self.tax_15)])
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=33.33,
                    residual_policy='ignore')
        self.assertFalse(self._discount_lines(order))
        self.assertAlmostEqual(order.amount_untaxed, 966.69, places=2)

    def test_proportional_fixed_on_tax_included_total(self):
        order = self._create_order([self._line(self.prod_a, 2, 115.0, self.tax_15_incl)])
        self.assertAlmostEqual(order.amount_total, 230.0)
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=23.0,
                    amount_base='total')
        self.assertAlmostEqual(order.order_line.discount, 10.0)
        self.assertAlmostEqual(order.amount_total, 207.0, places=2)
        self.assertAlmostEqual(order.amount_untaxed, 180.0, places=2)

    def test_proportional_fixed_whole_order(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=1000.0)
        self.assertAlmostEqual(order.amount_untaxed, 0.0, places=2)
        self.assertEqual(set(order.order_line.mapped('discount')), {100.0})

    # ------------------------------------------------------------------
    # Mode B - manual weighted
    # ------------------------------------------------------------------
    def test_weighted_by_weight(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 100.0, self.tax_15),
        ])
        line_a, line_b = order.order_line
        self._apply(order, {line_a: {'weight': 3.0}, line_b: {'weight': 1.0}},
                    mode='weighted', weighted_method='weight',
                    discount_type='fixed', discount_value=40.0)
        self.assertAlmostEqual(line_a.price_subtotal, 70.0)
        self.assertAlmostEqual(line_b.price_subtotal, 90.0)

    def test_weighted_zero_weight_excludes_line(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 100.0, self.tax_15),
        ])
        line_a, line_b = order.order_line
        self._apply(order, {line_a: {'weight': 0.0}}, mode='weighted', weighted_method='weight',
                    discount_type='percent', discount_value=10.0)
        self.assertEqual(line_a.discount, 0.0)
        self.assertAlmostEqual(line_b.price_subtotal, 80.0)

    def test_weighted_line_percent(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 100.0, self.tax_15),
        ])
        line_a, line_b = order.order_line
        self._apply(order, {line_a: {'line_percent': 10.0}, line_b: {'line_percent': 20.0}},
                    mode='weighted', weighted_method='line_percent')
        self.assertEqual((line_a.discount, line_b.discount), (10.0, 20.0))

    def test_weighted_line_amount(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 100.0, self.tax_15),
        ])
        line_a, line_b = order.order_line
        self._apply(order, {line_a: {'line_amount': 15.0}, line_b: {'line_amount': 5.0}},
                    mode='weighted', weighted_method='line_amount')
        self.assertAlmostEqual(line_a.price_subtotal, 85.0)
        self.assertAlmostEqual(line_b.price_subtotal, 95.0)
        with self.assertRaises(UserError):
            self._apply(order, {line_a: {'line_amount': 100.01}},
                        mode='weighted', weighted_method='line_amount')

    # ------------------------------------------------------------------
    # Mode C - dedicated discount lines
    # ------------------------------------------------------------------
    def test_dedicated_line_per_tax_group(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        discount_lines = self._discount_lines(order)
        self.assertEqual(len(discount_lines), 2)
        line_15 = discount_lines.filtered(lambda l: l.tax_id == self.tax_15)
        line_0 = discount_lines.filtered(lambda l: l.tax_id == self.tax_0)
        self.assertAlmostEqual(line_15.price_subtotal, -53.33)
        self.assertAlmostEqual(line_0.price_subtotal, -46.67)
        self.assertEqual(set(self._regular_lines(order).mapped('discount')), {0.0})
        self.assertAlmostEqual(order.amount_untaxed, 900.0, places=2)
        self.assertAlmostEqual(order.amount_tax, (533.31 - 53.33) * 0.15, delta=0.011)
        self.assertAlmostEqual(order.asd_discount_total, 100.0, places=2)

    def test_dedicated_line_fixed_tax_included(self):
        order = self._create_order([self._line(self.prod_a, 2, 115.0, self.tax_15_incl)])
        self._apply(order, mode='line', discount_type='fixed', discount_value=23.0,
                    amount_base='total')
        discount_line = self._discount_lines(order)
        self.assertAlmostEqual(discount_line.price_unit, -23.0)
        self.assertAlmostEqual(discount_line.price_total, -23.0)
        self.assertAlmostEqual(order.amount_total, 207.0, places=2)

    def test_dedicated_line_follows_fiscal_position(self):
        fiscal_position = self.env['account.fiscal.position'].create({
            'name': 'Export (ASD)',
            'tax_ids': [Command.create({'tax_src_id': self.tax_15.id,
                                        'tax_dest_id': self.tax_0.id})],
        })
        order = self._create_order([
            Command.create({'product_id': self.prod_a.id, 'product_uom_qty': 1,
                            'price_unit': 100.0}),
        ], fiscal_position_id=fiscal_position.id)
        self.assertEqual(order.order_line.tax_id, self.tax_0)
        self._apply(order, mode='line', discount_type='fixed', discount_value=10.0)
        self.assertEqual(self._discount_lines(order).tax_id, self.tax_0)
        self.assertAlmostEqual(order.amount_total, 90.0, places=2)

    def test_dedicated_line_analytic_distribution(self):
        plan = self.env['account.analytic.plan'].sudo().create({'name': 'ASD Plan'})
        analytic = self.env['account.analytic.account'].sudo().create({
            'name': 'ASD Project', 'plan_id': plan.id})
        order = self._create_order([
            Command.create({'product_id': self.prod_a.id, 'product_uom_qty': 1,
                            'price_unit': 100.0, 'tax_id': [Command.set(self.tax_15.ids)],
                            'analytic_distribution': {str(analytic.id): 100}}),
        ])
        self._apply(order, mode='line', discount_type='percent', discount_value=5.0)
        self.assertEqual(self._discount_lines(order).analytic_distribution,
                         {str(analytic.id): 100})

    # ------------------------------------------------------------------
    # Re-apply, reset, stale detection
    # ------------------------------------------------------------------
    def test_reapply_does_not_compound(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        self.assertEqual(set(self._regular_lines(order).mapped('discount')), {10.0})
        self.assertAlmostEqual(order.amount_untaxed, 900.0, places=2)
        # switching mode cleans the previous application
        self._apply(order, mode='line', discount_type='fixed', discount_value=50.0)
        self.assertEqual(set(self._regular_lines(order).mapped('discount')), {0.0})
        self.assertAlmostEqual(order.amount_untaxed, 950.0, places=2)

    def test_reset_restores_document(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15, discount=5.0),
            self._line(self.prod_c, 1, 100.0, self.tax_0),
        ])
        untaxed = order.amount_untaxed
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=33.33)
        order.action_asd_reset_discount()
        self.assertEqual(order.order_line.mapped('discount'), [5.0, 0.0])
        self.assertFalse(self._discount_lines(order))
        self.assertFalse(order.asd_discount_mode)
        self.assertAlmostEqual(order.amount_untaxed, untaxed)
        self.assertFalse(any(order.order_line.mapped('asd_discount_applied')))

    def test_stale_when_lines_change(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        self.assertFalse(order.asd_discount_stale)
        order.order_line[0].discount = 3.0
        self.assertTrue(order.asd_discount_stale)
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        self.assertFalse(order.asd_discount_stale)
        order.write({'order_line': [self._line(self.prod_b, 1, 10.0, self.tax_15)]})
        self.assertTrue(order.asd_discount_stale)

    def test_update_prices_keeps_discount_line(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='fixed', discount_value=100.0)
        discount_prices = self._discount_lines(order).mapped('price_unit')
        order.action_update_prices()
        self.assertEqual(self._discount_lines(order).mapped('price_unit'), discount_prices)

    def test_copy_order_keeps_discount(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='fixed', discount_value=100.0)
        copy = order.copy()
        self.assertAlmostEqual(copy.amount_untaxed, 900.0, places=2)
        self.assertEqual(len(self._discount_lines(copy)), 2)
        copy.action_asd_reset_discount()
        self.assertAlmostEqual(copy.amount_untaxed, 1000.0, places=2)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def test_validation_errors(self):
        order = self._std_order()
        for values in (
            {'mode': 'proportional', 'discount_type': 'percent', 'discount_value': 0.0},
            {'mode': 'proportional', 'discount_type': 'percent', 'discount_value': -1.0},
            {'mode': 'proportional', 'discount_type': 'percent', 'discount_value': 100.5},
            {'mode': 'proportional', 'discount_type': 'fixed', 'discount_value': 1000.01},
            {'mode': 'line', 'discount_type': 'fixed', 'discount_value': 5000.0},
        ):
            with self.assertRaises(UserError, msg=values):
                self._apply(order, **values)
        self.assertAlmostEqual(order.amount_untaxed, 1000.0, places=2)

    def test_wizard_preview_reports_error_without_raising(self):
        order = self._std_order()
        wizard = self._wizard(order, mode='proportional', discount_type='fixed',
                              discount_value=5000.0)
        self.assertTrue(wizard.preview_error)
        wizard.discount_value = 100.0
        self.assertFalse(wizard.preview_error)
        self.assertAlmostEqual(wizard.total_discount, 100.0, places=2)
        self.assertAlmostEqual(sum(wizard.line_ids.mapped('preview_amount')), 100.0, places=2)

    def test_no_eligible_lines(self):
        order = self._create_order([self._line(self.prod_a, 1, 0.0, self.tax_15)])
        with self.assertRaises(UserError):
            self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)

    def test_sections_and_notes_ignored(self):
        order = self._create_order([
            Command.create({'display_type': 'line_section', 'name': 'Section'}),
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            Command.create({'display_type': 'line_note', 'name': 'Note'}),
        ])
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(order.amount_untaxed, 90.0, places=2)

    def test_disabled_company_blocks(self):
        order = self._std_order()
        self.company.sudo().asd_discount_enabled = False
        with self.assertRaises(UserError):
            order.action_open_asd_discount_wizard()

    def test_cancelled_or_invoiced_order_blocks(self):
        order = self._std_order()
        order._action_cancel()
        with self.assertRaises(UserError):
            order.action_open_asd_discount_wizard()
        order = self._std_order()
        order.action_confirm()
        order._create_invoices()
        with self.assertRaises(UserError):
            self._apply(order, mode='proportional', discount_type='percent', discount_value=5.0)

    def test_locked_order_blocks(self):
        # Odoo 17+: a locked order stays in state 'sale' with locked=True
        order = self._std_order()
        order.action_confirm()
        order.action_lock()
        self.assertTrue(order.locked)
        with self.assertRaises(UserError):
            order.action_open_asd_discount_wizard()

    def test_confirmed_order_can_be_discounted_and_reset(self):
        order = self._std_order()
        order.action_confirm()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(order.amount_untaxed, 900.0, places=2)
        order.action_asd_reset_discount()
        self.assertFalse(self._discount_lines(order))

    def test_access_right(self):
        user = self.env['res.users'].sudo().create({
            'name': 'ASD Salesman', 'login': 'asd_salesman',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'groups_id': [Command.set(self.env.ref('sales_team.group_sale_salesman_all_leads').ids)],
        })
        order = self._std_order()
        with self.assertRaises(AccessError):
            order.with_user(user).action_open_asd_discount_wizard()
