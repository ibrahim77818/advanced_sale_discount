# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class AsdCommon(AccountTestInvoicingCommon):
    """Shared fixtures: taxes, products, discount product and helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # v18: the second company and the foreign currency are opt-in.
        cls.company_data_2 = cls.setup_other_company()
        cls.other_currency = cls.setup_other_currency('EUR', rates=[('2016-01-01', 2.0)])
        cls.company = cls.company_data['company']
        groups = (
            cls.env.ref('account.group_account_manager')
            | cls.env.ref('sales_team.group_sale_manager')
            | cls.env.ref('advanced_sale_discount.group_sale_discount_user')
            | cls.env.ref('product.group_discount_per_so_line')
        )
        cls.env.user.sudo().write({'group_ids': [Command.link(g.id) for g in groups]})
        cls.income_account = cls.company_data['default_account_revenue']
        cls.discount_account = cls.income_account.copy({
            'name': 'Sales Discounts', 'code': 'ASD401'})

        Tax = cls.env['account.tax']
        cls.tax_15 = Tax.create({
            'name': 'VAT 15% (ASD)', 'amount': 15.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.tax_15_incl = Tax.create({
            'name': 'VAT 15% Included (ASD)', 'amount': 15.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'price_include': True, 'company_id': cls.company.id,
        })
        cls.tax_0 = Tax.create({
            'name': 'VAT 0% (ASD)', 'amount': 0.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })

        Product = cls.env['product.product']
        cls.discount_product = Product.create({
            'name': 'Global Discount',
            'type': 'service',
            'invoice_policy': 'order',
            'sale_ok': True,
            'taxes_id': [Command.clear()],
            'property_account_income_id': cls.discount_account.id,
        })
        cls.categ_bulk = cls.env['product.category'].create({'name': 'Bulk (ASD)'})
        cls.categ_bulk_child = cls.env['product.category'].create({
            'name': 'Bulk Child (ASD)', 'parent_id': cls.categ_bulk.id})
        cls.prod_a = Product.create({
            'name': 'ASD Product A', 'type': 'consu', 'invoice_policy': 'order',
            'list_price': 100.0, 'taxes_id': [Command.set(cls.tax_15.ids)],
            'categ_id': cls.categ_bulk_child.id,
            'property_account_income_id': cls.income_account.id,
        })
        cls.prod_b = Product.create({
            'name': 'ASD Product B', 'type': 'consu', 'invoice_policy': 'order',
            'list_price': 50.0, 'taxes_id': [Command.set(cls.tax_15.ids)],
            'property_account_income_id': cls.income_account.id,
        })
        cls.prod_c = Product.create({
            'name': 'ASD Product C', 'type': 'consu', 'invoice_policy': 'order',
            'list_price': 10.0, 'taxes_id': [Command.set(cls.tax_0.ids)],
            'property_account_income_id': cls.income_account.id,
        })
        cls.prod_service_delivered = Product.create({
            'name': 'ASD Delivered Service', 'type': 'service',
            'invoice_policy': 'delivery',
            'list_price': 100.0, 'taxes_id': [Command.set(cls.tax_15.ids)],
            'property_account_income_id': cls.income_account.id,
        })
        cls.company.sudo().write({
            'asd_discount_enabled': True,
            'asd_discount_product_id': cls.discount_product.id,
        })
        cls.customer = cls.partner_a

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _line(cls, product, qty, price, taxes=None, discount=0.0):
        vals = {
            'product_id': product.id,
            'product_uom_qty': qty,
            'price_unit': price,
            'discount': discount,
        }
        if taxes is not None:
            vals['tax_ids'] = [Command.set(taxes.ids)]
        return Command.create(vals)

    def _create_order(self, lines, partner=None, **extra):
        vals = {
            'partner_id': (partner or self.customer).id,
            'order_line': lines,
        }
        vals.update(extra)
        return self.env['sale.order'].create(vals)

    def _std_order(self):
        """Untaxed 1000.00: 300.00 + 233.31 (VAT 15%) + 466.69 (VAT 0%)."""
        return self._create_order([
            self._line(self.prod_a, 3, 100.0, self.tax_15),
            self._line(self.prod_b, 7, 33.33, self.tax_15),
            self._line(self.prod_c, 1, 466.69, self.tax_0),
        ])

    def _wizard(self, doc, line_values=None, **values):
        action = doc.action_open_asd_discount_wizard()
        wizard = self.env['asd.discount.wizard'].with_context(**action['context']).create(values)
        for doc_line, vals in (line_values or {}).items():
            wizard_line = wizard.line_ids.filtered(
                lambda l: (l.sale_line_id or l.move_line_id) == doc_line)
            wizard_line.write(vals)
        return wizard

    def _apply(self, doc, line_values=None, **values):
        wizard = self._wizard(doc, line_values=line_values, **values)
        wizard.action_apply()
        return wizard

    def _regular_lines(self, order):
        return order.order_line.filtered(lambda l: not l.asd_is_discount_line)

    def _discount_lines(self, order):
        return order.order_line.filtered('asd_is_discount_line')

    def _create_invoice(self, lines, move_type='out_invoice', partner=None):
        return self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': (partner or self.customer).id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'quantity': qty,
                'price_unit': price,
                'tax_ids': [Command.set(taxes.ids)],
            }) for product, qty, price, taxes in lines],
        })
