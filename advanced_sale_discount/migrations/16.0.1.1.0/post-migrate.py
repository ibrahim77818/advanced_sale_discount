# -*- coding: utf-8 -*-
"""1.1.0: snapshot the lines of documents that already carry a global discount,
so later changes to product, quantity, unit, price, taxes or lines are detected."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sale.order'].search([
        ('asd_discount_mode', '!=', False),
        ('state', 'in', ('draft', 'sent')),
    ])._asd_refresh_fingerprint()
    env['account.move'].search([
        ('asd_discount_mode', '!=', False),
        ('state', '=', 'draft'),
        ('move_type', 'in', ('out_invoice', 'out_refund')),
    ])._asd_refresh_fingerprint()
