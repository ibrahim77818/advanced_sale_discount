# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _name = 'account.move.line'
    _inherit = ['account.move.line', 'asd.discount.line.mixin']

    asd_discount_amount = fields.Monetary(
        string='Global Discount Amount', compute='_compute_asd_discount_amount',
        currency_field='currency_id')

    asd_discount_origin = fields.Selection(
        [('sale', 'Sales Order'), ('invoice', 'Invoice')],
        string='Discount Origin', readonly=True,
        help='Document on which the global discount of this line was applied.')

    def _asd_document(self):
        return self.move_id

    @api.depends('price_unit', 'discount', 'quantity', 'tax_ids', 'price_subtotal',
                 'asd_base_discount', 'asd_extra_discount', 'asd_is_discount_line')
    def _compute_asd_discount_amount(self):
        return super()._compute_asd_discount_amount()

    def _compute_tax_ids(self):
        # Discount lines carry the taxes of the lines they discount (already
        # mapped by the fiscal position), not the discount product's taxes.
        discount_lines = self.filtered(lambda l: l.asd_is_discount_line and l.tax_ids)
        res = super(AccountMoveLine, self - discount_lines)._compute_tax_ids()
        for line in discount_lines:
            fiscal_position = line.move_id.fiscal_position_id
            if fiscal_position:
                line.tax_ids = fiscal_position.map_tax(line.tax_ids)
        return res
