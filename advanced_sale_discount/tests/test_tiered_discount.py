# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestTieredDiscount(AsdCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Keep each test independent from rules created by other modules/data.
        cls.env['sale.discount.tier.rule'].search([]).write({'active': False})

    def _rule(self, tiers, **values):
        vals = {
            'name': 'ASD Rule',
            'scope': 'line',
            'basis': 'quantity',
            'tier_ids': [Command.create({'min_value': threshold, 'discount_percent': percent})
                         for threshold, percent in tiers],
        }
        vals.update(values)
        return self.env['sale.discount.tier.rule'].sudo().create(vals)

    def _tiered(self, order, **values):
        return self._apply(order, mode='tiered', **values)

    def test_line_quantity_tiers(self):
        self._rule([(10, 5.0), (50, 10.0)])
        order = self._create_order([
            self._line(self.prod_a, 5, 10.0, self.tax_15),
            self._line(self.prod_a, 20, 10.0, self.tax_15),
            self._line(self.prod_a, 60, 10.0, self.tax_15),
        ])
        self._tiered(order)
        self.assertEqual(order.order_line.mapped('discount'), [0.0, 5.0, 10.0])
        self.assertEqual(order.asd_discount_mode, 'tiered')

    def test_quantity_uses_product_uom(self):
        self._rule([(24, 8.0)])
        uom_dozen = self.env.ref('uom.product_uom_dozen')
        order = self._create_order([Command.create({
            'product_id': self.prod_a.id, 'product_uom_qty': 2, 'product_uom_id': uom_dozen.id,
            'price_unit': 120.0, 'tax_ids': [Command.set(self.tax_15.ids)]})])
        self._tiered(order)
        self.assertEqual(order.order_line.discount, 8.0)

    def test_order_amount_tier(self):
        self._rule([(1000, 7.0)], scope='order', basis='amount')
        order = self._create_order([
            self._line(self.prod_a, 6, 100.0, self.tax_15),
            self._line(self.prod_b, 1, 400.0, self.tax_15),
        ])
        self._tiered(order)
        self.assertEqual(order.order_line.mapped('discount'), [7.0, 7.0])
        self.assertAlmostEqual(order.amount_untaxed, 930.0, places=2)

    def test_amount_threshold_in_company_currency(self):
        self._rule([(1000, 7.0)], scope='order', basis='amount')
        currency = self.other_currency  # rate 2.0 against the company currency
        pricelist = self.env['product.pricelist'].create({
            'name': 'ASD foreign', 'currency_id': currency.id})
        order_low = self._create_order([self._line(self.prod_a, 1, 1500.0, self.tax_15)],
                                       pricelist_id=pricelist.id)
        with self.assertRaises(UserError):  # 1500 / 2 = 750 < 1000
            self._tiered(order_low)
        order_high = self._create_order([self._line(self.prod_a, 1, 2500.0, self.tax_15)],
                                        pricelist_id=pricelist.id)
        self._tiered(order_high)  # 2500 / 2 = 1250 >= 1000
        self.assertEqual(order_high.order_line.discount, 7.0)

    def test_contract_rule_takes_precedence(self):
        self._rule([(1, 5.0)], sequence=1)
        self._rule([(1, 12.0)], sequence=99, partner_ids=[Command.set(self.customer.ids)])
        order = self._create_order([self._line(self.prod_a, 2, 100.0, self.tax_15)])
        self._tiered(order)
        self.assertEqual(order.order_line.discount, 12.0)
        other = self._create_order([self._line(self.prod_a, 2, 100.0, self.tax_15)],
                                   partner=self.partner_b)
        self._tiered(other)
        self.assertEqual(other.order_line.discount, 5.0)

    def test_contract_rule_matches_commercial_partner(self):
        contact = self.env['res.partner'].create({
            'name': 'ASD Contact', 'parent_id': self.customer.id, 'type': 'invoice'})
        self._rule([(1, 12.0)], partner_ids=[Command.set(self.customer.ids)])
        order = self._create_order([self._line(self.prod_a, 1, 100.0, self.tax_15)],
                                   partner=contact)
        self._tiered(order)
        self.assertEqual(order.order_line.discount, 12.0)

    def test_product_and_category_filters(self):
        self._rule([(1, 9.0)], categ_ids=[Command.set(self.categ_bulk.ids)])  # parent category
        self._rule([(1, 4.0)], product_ids=[Command.set(self.prod_c.ids)])
        order = self._create_order([
            self._line(self.prod_a, 1, 100.0, self.tax_15),  # child category
            self._line(self.prod_b, 1, 100.0, self.tax_15),  # no rule
            self._line(self.prod_c, 1, 100.0, self.tax_0),
        ])
        self._tiered(order)
        self.assertEqual(order.order_line.mapped('discount'), [9.0, 0.0, 4.0])

    def test_validity_dates_and_company(self):
        today = fields.Date.today()
        self._rule([(1, 9.0)], date_end=today - timedelta(days=1))
        self._rule([(1, 9.0)], date_start=today + timedelta(days=1))
        self._rule([(1, 9.0)], company_id=self.company_data_2['company'].id)
        order = self._create_order([self._line(self.prod_a, 1, 100.0, self.tax_15)])
        with self.assertRaises(UserError):
            self._tiered(order)

    def test_selected_rules_only(self):
        rule_5 = self._rule([(1, 5.0)], sequence=1)
        self._rule([(1, 15.0)], sequence=2)
        order = self._create_order([self._line(self.prod_a, 1, 100.0, self.tax_15)])
        self._tiered(order, tier_rule_ids=[Command.set(rule_5.ids)])
        self.assertEqual(order.order_line.discount, 5.0)

    def test_tier_constraints(self):
        with self.assertRaises(ValidationError):
            self._rule([(1, 0.0)])
        with self.assertRaises(ValidationError):
            self._rule([(1, 101.0)])
        with self.assertRaises(ValidationError):
            self._rule([(-1, 5.0)])
        with self.assertRaises(ValidationError):
            self._rule([(1, 5.0)], date_start=fields.Date.today(),
                       date_end=fields.Date.today() - timedelta(days=1))
