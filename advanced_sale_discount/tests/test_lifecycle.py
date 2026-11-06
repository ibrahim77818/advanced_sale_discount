# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestLifecycle(AsdCommon):
    """Sales order -> delivery -> (partial) invoices -> journal entries."""

    def _assert_balanced(self, move):
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')), places=2)

    def test_proportional_discount_flows_to_invoice(self):
        order = self._std_order()
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.action_confirm()
        invoice = order._create_invoices()
        lines = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertEqual(set(lines.mapped('discount')), {10.0})
        self.assertEqual(set(lines.mapped('asd_discount_origin')), {'sale'})
        self.assertAlmostEqual(invoice.amount_untaxed, order.amount_untaxed, places=2)
        self.assertAlmostEqual(invoice.amount_total, order.amount_total, places=2)
        self.assertEqual(invoice.asd_discount_mode, 'proportional')
        self.assertAlmostEqual(invoice.asd_discount_total, 100.0, places=2)
        invoice.action_post()
        self._assert_balanced(invoice)

    def test_discount_lines_flow_to_invoice(self):
        order = self._std_order()
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        order.action_confirm()
        invoice = order._create_invoices()
        discount_lines = invoice.invoice_line_ids.filtered('asd_is_discount_line')
        self.assertEqual(len(discount_lines), 2)
        self.assertEqual(set(discount_lines.mapped('asd_discount_origin')), {'sale'})
        self.assertAlmostEqual(invoice.amount_untaxed, 900.0, places=2)
        self.assertAlmostEqual(invoice.amount_total, order.amount_total, places=2)
        self.assertEqual(order.invoice_status, 'invoiced')
        # an invoice-level reset must not remove discount lines coming from the order
        invoice.action_asd_reset_discount()
        self.assertEqual(len(invoice.invoice_line_ids.filtered('asd_is_discount_line')), 2)
        invoice.action_post()
        self._assert_balanced(invoice)

    def test_partial_delivery_prorates_discount_line(self):
        order = self._create_order([
            self._line(self.prod_service_delivered, 10, 100.0, self.tax_15)])
        self._apply(order, mode='line', discount_type='percent', discount_value=10.0)
        order.action_confirm()
        discount_line = self._discount_lines(order)
        regular = self._regular_lines(order)
        self.assertEqual(discount_line.qty_to_invoice, 0.0, 'Nothing delivered yet')

        regular.qty_delivered = 4
        self.assertAlmostEqual(discount_line.qty_to_invoice, 0.4)
        invoice_1 = order._create_invoices()
        self.assertAlmostEqual(invoice_1.amount_untaxed, 400.0 - 40.0, places=2)

        regular.qty_delivered = 10
        self.assertAlmostEqual(discount_line.qty_to_invoice, 0.6)
        invoice_2 = order._create_invoices()
        self.assertAlmostEqual(invoice_2.amount_untaxed, 600.0 - 60.0, places=2)

        total_invoiced = invoice_1.amount_untaxed + invoice_2.amount_untaxed
        self.assertAlmostEqual(total_invoiced, order.amount_untaxed, places=2)
        self.assertAlmostEqual(discount_line.qty_invoiced, 1.0)
        self.assertEqual(order.invoice_status, 'invoiced')
        (invoice_1 | invoice_2).action_post()
        self._assert_balanced(invoice_1)
        self._assert_balanced(invoice_2)

    def test_partial_delivery_converges_without_leakage(self):
        order = self._create_order([
            self._line(self.prod_service_delivered, 3, 33.33, self.tax_15)])
        self._apply(order, mode='line', discount_type='fixed', discount_value=10.0)
        order.action_confirm()
        regular = self._regular_lines(order)
        invoices = self.env['account.move']
        for delivered in (1, 2, 3):
            regular.qty_delivered = delivered
            invoices |= order._create_invoices()
        self.assertAlmostEqual(sum(invoices.mapped('amount_untaxed')),
                               order.amount_untaxed, places=2)
        self.assertAlmostEqual(self._discount_lines(order).qty_invoiced, 1.0)

    def test_invoice_level_discount_on_top_of_order_discount(self):
        order = self._create_order([self._line(self.prod_a, 1, 100.0, self.tax_15)])
        self._apply(order, mode='proportional', discount_type='percent', discount_value=10.0)
        order.action_confirm()
        invoice = order._create_invoices()
        self._apply(invoice, mode='proportional', discount_type='percent', discount_value=10.0)
        line = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertAlmostEqual(line.discount, 19.0)
        invoice.action_asd_reset_discount()
        self.assertAlmostEqual(line.discount, 10.0, msg='Order discount is kept')
