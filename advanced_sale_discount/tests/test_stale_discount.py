# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestStaleDiscount(AsdCommon):
    """A global discount must be flagged out of date (and block confirmation)
    as soon as the lines it was computed from change."""

    def _order_500(self):
        # 5 x 100.00 at list price, so changing the quantity keeps the price.
        return self._create_order([self._line(self.prod_a, 5, 100.0, self.tax_15)])

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def test_dedicated_line_quantity_change(self):
        order = self._order_500()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(self._discount_lines(order).price_subtotal, -50.0)
        self.assertFalse(order.asd_discount_stale)

        self._regular_lines(order).product_uom_qty = 13
        self.assertTrue(order.asd_discount_stale)
        self.assertAlmostEqual(self._discount_lines(order).price_subtotal, -50.0,
                               msg='Nothing is changed behind the user\'s back')
        with self.assertRaises(UserError):
            order.action_confirm()

        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(self._discount_lines(order).price_subtotal, -130.0)
        self.assertFalse(order.asd_discount_stale)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_proportional_price_change(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=100.0)
        self.assertFalse(order.asd_discount_stale)
        order.order_line[0].price_unit = 150.0
        self.assertTrue(order.asd_discount_stale)

    def test_proportional_line_deleted(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='fixed', discount_value=100.0)
        order.order_line[1].unlink()
        self.assertTrue(order.asd_discount_stale)

    def test_only_discounted_line_deleted(self):
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 0.0, self.tax_15),  # not discountable
        ])
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.order_line[0].unlink()
        self.assertTrue(order.asd_discount_stale)

    def test_tax_change(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self._regular_lines(order)[0].tax_id = self.tax_0
        self.assertTrue(order.asd_discount_stale)

    def test_unit_of_measure_change(self):
        order = self._order_500()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.order_line.product_uom = self.env.ref('uom.product_uom_dozen')
        self.assertTrue(order.asd_discount_stale)

    def test_product_change(self):
        order = self._order_500()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.order_line.product_id = self.prod_b
        self.assertTrue(order.asd_discount_stale)

    def test_discount_line_edited(self):
        order = self._create_order([self._line(self.prod_a, 2, 115.0, self.tax_15_incl)])
        self._apply(order, mode='line', discount_type='fixed', discount_value=23.0,
                    amount_base='total')
        self.assertFalse(order.asd_discount_stale)
        self._discount_lines(order).price_unit = -10.0
        self.assertTrue(order.asd_discount_stale)

    def test_detected_while_editing_the_form(self):
        order = self._order_500()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        order_form = Form(order)
        regular_index = list(order.order_line).index(self._regular_lines(order))
        with order_form.order_line.edit(regular_index) as line:
            line.product_uom_qty = 13
        self.assertTrue(order_form.asd_discount_stale)

    # ------------------------------------------------------------------
    # What is not flagged / not blocked
    # ------------------------------------------------------------------
    def test_untouched_order_confirms(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='fixed', discount_value=100.0)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.asd_discount_stale)

    def test_remove_discount_unblocks(self):
        order = self._order_500()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self._regular_lines(order).product_uom_qty = 13
        order.action_asd_reset_discount()
        self.assertFalse(order.asd_discount_stale)
        self.assertFalse(order.asd_discount_fingerprint)
        order.action_confirm()
        self.assertEqual(order.state, 'sale')

    def test_superuser_and_context_confirmation_not_blocked(self):
        # Portal acceptance and online payment confirm orders as superuser.
        order = self._order_500()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        self._regular_lines(order).product_uom_qty = 13
        order.sudo().action_confirm()
        self.assertEqual(order.state, 'sale')
        other = self._order_500()
        self._apply(other, mode='line', discount_type='percent', discount_value=10.0)
        self._regular_lines(other).product_uom_qty = 13
        other.with_context(asd_skip_stale_check=True).action_confirm()
        self.assertEqual(other.state, 'sale')

    def test_copy_is_not_stale(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='fixed', discount_value=100.0)
        copy = order.copy()
        self.assertTrue(copy.asd_discount_fingerprint)
        self.assertFalse(copy.asd_discount_stale)
        self._regular_lines(copy)[0].product_uom_qty = 9
        self.assertTrue(copy.asd_discount_stale)

    def test_document_discounted_before_upgrade(self):
        order = self._order_500()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        order.asd_discount_fingerprint = False  # as applied by version 1.0.0
        self._regular_lines(order).product_uom_qty = 6
        self.assertFalse(order.asd_discount_stale, 'Old documents keep the old checks')
        order._asd_refresh_fingerprint()  # what the 1.1.0 upgrade script does
        self._regular_lines(order).product_uom_qty = 13
        self.assertTrue(order.asd_discount_stale)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def test_invoice_quantity_change_blocks_posting(self):
        move = self._create_invoice([(self.prod_a, 5, 100.0, self.tax_15)])
        self._apply(move, mode='line', discount_type='percent', discount_value=10.0)
        self.assertFalse(move.asd_discount_stale)
        line = move.invoice_line_ids.filtered(lambda l: not l.asd_is_discount_line)
        move.write({'invoice_line_ids': [Command.update(line.id, {'quantity': 13})]})
        self.assertTrue(move.asd_discount_stale)
        with self.assertRaises(UserError):
            move.action_post()
        self._apply(move, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(move.amount_untaxed, 1170.0, places=2)
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_invoice_from_order_not_blocked(self):
        order = self._order_500()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.action_confirm()
        invoice = order._create_invoices()
        self.assertFalse(invoice.asd_discount_fingerprint)
        line = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        invoice.write({'invoice_line_ids': [Command.update(line.id, {'quantity': 4})]})
        self.assertFalse(invoice.asd_discount_stale)
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
