# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import AsdCommon


@tagged('post_install', '-at_install', 'advanced_sale_discount')
class TestSettings(AsdCommon):

    def test_default_disabled(self):
        company = self.company_data_2['company']
        self.assertFalse(company.asd_discount_enabled)

    def test_enable_requires_product(self):
        company = self.company_data_2['company']
        with self.assertRaises(ValidationError):
            company.sudo().write({'asd_discount_enabled': True})

    def test_product_must_be_service(self):
        product = self.discount_product.sudo().copy({'type': 'consu'})
        with self.assertRaises(ValidationError):
            self.company.sudo().write({'asd_discount_product_id': product.id})

    def test_product_invoice_policy(self):
        product = self.discount_product.sudo().copy()
        product.invoice_policy = 'delivery'
        with self.assertRaises(ValidationError):
            self.company.sudo().write({'asd_discount_product_id': product.id})

    def test_product_other_company(self):
        product = self.discount_product.sudo().copy({'company_id': self.company_data_2['company'].id})
        with self.assertRaises(ValidationError):
            self.company.sudo().write({'asd_discount_product_id': product.id})

    def test_product_needs_income_account(self):
        category = self.env['product.category'].create({'name': 'No Accounts (ASD)'})
        category.property_account_income_categ_id = False
        product = self.env['product.product'].create({
            'name': 'Discount w/o account', 'type': 'service',
            'invoice_policy': 'order', 'categ_id': category.id,
            'taxes_id': [Command.clear()],
        })
        product.property_account_income_id = False
        with self.assertRaises(ValidationError):
            self.company.sudo().write({'asd_discount_product_id': product.id})

    def test_settings_write_flag_and_product_together(self):
        company = self.company_data_2['company']
        product = self.discount_product.sudo().copy({'company_id': False})
        product.with_company(company).sudo().property_account_income_id = \
            self.company_data_2['default_account_revenue']
        settings = self.env['res.config.settings'].with_company(company).sudo().create({
            'asd_discount_enabled': True,
            'asd_discount_product_id': product.id,
        })
        settings.execute()
        self.assertTrue(company.asd_discount_enabled)
        self.assertEqual(company.asd_discount_product_id, product)
