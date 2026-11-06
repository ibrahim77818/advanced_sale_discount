# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Both fields share one inverse so that the company is written in a single
    # call: the company constraint then sees the flag and the product together.
    asd_discount_enabled = fields.Boolean(
        string='Advanced Sale Discounts',
        compute='_compute_asd_discount_settings',
        inverse='_inverse_asd_discount_settings',
        readonly=False,
    )
    asd_discount_product_id = fields.Many2one(
        'product.product',
        string='Sale Discount Product',
        compute='_compute_asd_discount_settings',
        inverse='_inverse_asd_discount_settings',
        readonly=False,
        domain="[('type', '=', 'service'), ('sale_ok', '=', True), "
               "'|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    @api.depends('company_id')
    def _compute_asd_discount_settings(self):
        for settings in self:
            settings.asd_discount_enabled = settings.company_id.asd_discount_enabled
            settings.asd_discount_product_id = settings.company_id.asd_discount_product_id

    def _inverse_asd_discount_settings(self):
        for settings in self:
            company = settings.company_id
            values = {}
            if company.asd_discount_enabled != settings.asd_discount_enabled:
                values['asd_discount_enabled'] = settings.asd_discount_enabled
            if company.asd_discount_product_id != settings.asd_discount_product_id:
                values['asd_discount_product_id'] = settings.asd_discount_product_id.id
            if values:
                company.write(values)
