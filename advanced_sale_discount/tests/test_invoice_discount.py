# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestInvoiceDiscount(AsdCommon):

    def _std_invoice(self, move_type='out_invoice'):
        return self._create_invoice([
            (self.prod_a, 3, 100.0, self.tax_15),
            (self.prod_b, 7, 33.33, self.tax_15),
            (self.prod_c, 1, 466.69, self.tax_0),
        ], move_type=move_type)

    def _product_lines(self, move):
        return move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _assert_balanced(self, move):
        lines = move.line_ids
        self.assertAlmostEqual(sum(lines.mapped('debit')), sum(lines.mapped('credit')), places=2)
        receivable = lines.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertAlmostEqual(abs(sum(receivable.mapped('balance'))), move.amount_total, places=2)

    def test_invoice_proportional_percent(self):
        move = self._std_invoice()
        self._apply(move, mode='proportional', discount_type='percent', discount_value=10.0)
        self.assertEqual(set(self._product_lines(move).mapped('discount')), {10.0})
        self.assertAlmostEqual(move.amount_untaxed, 900.0, places=2)
        self.assertAlmostEqual(move.asd_discount_total, 100.0, places=2)
        self._assert_balanced(move)
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self._assert_balanced(move)

    def test_invoice_rounding_adjustment(self):
        move = self._create_invoice([(self.prod_a, 1, 999.99, self.tax_15)])
        self._apply(move, mode='proportional', discount_type='fixed', discount_value=33.33)
        adjustment = move.invoice_line_ids.filtered('asd_is_discount_line')
        self.assertEqual(len(adjustment), 1)
        self.assertEqual(adjustment.asd_discount_origin, 'invoice')
        self.assertAlmostEqual(move.amount_untaxed, 966.66, places=2)
        self._assert_balanced(move)

    def test_invoice_dedicated_lines_posting(self):
        move = self._std_invoice()
        self._apply(move, mode='line', discount_type='fixed', discount_value=100.0)
        discount_lines = move.invoice_line_ids.filtered('asd_is_discount_line')
        self.assertEqual(len(discount_lines), 2)
        self.assertEqual(discount_lines.account_id, self.discount_account,
                         'Discount lines post to the discount product income account')
        self.assertAlmostEqual(move.amount_untaxed, 900.0, places=2)
        move.action_post()
        self._assert_balanced(move)
        # revenue reduction booked as a debit on the discount account
        discount_balance = sum(move.line_ids.filtered(
            lambda l: l.account_id == self.discount_account).mapped('balance'))
        self.assertAlmostEqual(discount_balance, 100.0, places=2)

    def test_credit_note(self):
        refund = self._std_invoice(move_type='out_refund')
        self._apply(refund, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(refund.amount_untaxed, 900.0, places=2)
        refund.action_post()
        self._assert_balanced(refund)

    def test_invoice_weighted_and_reset(self):
        move = self._create_invoice([
            (self.prod_a, 1, 100.0, self.tax_15),
            (self.prod_b, 1, 100.0, self.tax_15),
        ])
        line_a, line_b = self._product_lines(move)
        self._apply(move, {line_a: {'weight': 3.0}, line_b: {'weight': 1.0}},
                    mode='weighted', weighted_method='weight',
                    discount_type='fixed', discount_value=40.0)
        self.assertAlmostEqual(line_a.price_subtotal, 70.0)
        self.assertAlmostEqual(line_b.price_subtotal, 90.0)
        move.action_asd_reset_discount()
        self.assertEqual(set(self._product_lines(move).mapped('discount')), {0.0})
        self.assertAlmostEqual(move.amount_untaxed, 200.0, places=2)

    def test_posted_invoice_blocked(self):
        move = self._std_invoice()
        move.action_post()
        with self.assertRaises(UserError):
            move.action_open_asd_discount_wizard()

    def test_vendor_bill_blocked(self):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.customer.id,
            'invoice_date': '2026-01-01',
            'invoice_line_ids': [(0, 0, {'name': 'x', 'quantity': 1, 'price_unit': 10.0})],
        })
        with self.assertRaises(UserError):
            bill.action_open_asd_discount_wizard()

    def test_invoice_without_product_line(self):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Consulting', 'quantity': 2, 'price_unit': 50.0,
                'account_id': self.income_account.id,
                'tax_ids': [(6, 0, self.tax_15.ids)],
            })],
        })
        self._apply(move, mode='line', discount_type='percent', discount_value=10.0)
        self.assertAlmostEqual(move.amount_untaxed, 90.0, places=2)
