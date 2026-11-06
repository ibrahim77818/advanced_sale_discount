# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

CUSTOMER_MOVE_TYPES = ('out_invoice', 'out_refund')


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'asd.discount.mixin']

    asd_discount_enabled = fields.Boolean(
        related='company_id.asd_discount_enabled',
        string='Advanced Discounts Enabled',
    )
    asd_discount_target = fields.Monetary(
        string='Target Discount', readonly=True, currency_field='currency_id',
        help='Discount amount requested when the discount was last applied.')
    asd_discount_total = fields.Monetary(
        string='Total Discount', compute='_compute_asd_discount_total',
        currency_field='currency_id',
        help='Untaxed amount of all global discounts on this document: '
             'discounts spread on the lines plus dedicated discount lines.')

    @api.depends('invoice_line_ids.price_subtotal', 'invoice_line_ids.asd_discount_amount',
                 'invoice_line_ids.asd_is_discount_line')
    def _compute_asd_discount_total(self):
        return super()._compute_asd_discount_total()

    @api.depends('asd_discount_mode', 'asd_discount_type', 'asd_discount_target',
                 'asd_discount_amount_base', 'asd_discount_fingerprint', 'invoice_line_ids',
                 'invoice_line_ids.product_id', 'invoice_line_ids.quantity',
                 'invoice_line_ids.product_uom_id', 'invoice_line_ids.price_unit',
                 'invoice_line_ids.tax_ids', 'invoice_line_ids.display_type',
                 'invoice_line_ids.discount',
                 'invoice_line_ids.asd_base_discount', 'invoice_line_ids.asd_extra_discount',
                 'invoice_line_ids.asd_discount_applied', 'invoice_line_ids.price_subtotal',
                 'invoice_line_ids.asd_is_discount_line', 'invoice_line_ids.asd_discount_origin')
    def _compute_asd_discount_stale(self):
        return super()._compute_asd_discount_stale()

    # ------------------------------------------------------------------
    # Adapter API
    # ------------------------------------------------------------------
    def _asd_lines(self):
        return self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _asd_structural_lines(self):
        return self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product'
            and not l.asd_is_discount_line
            and not any(l.sale_line_ids.mapped('is_downpayment')))

    def _asd_own_applied_lines(self):
        return self.invoice_line_ids.filtered('asd_discount_applied')

    def _asd_removable_discount_lines(self):
        return self.invoice_line_ids.filtered(
            lambda l: l.asd_is_discount_line and l.asd_discount_origin == 'invoice')

    def _asd_line_qty(self, line):
        return line.quantity

    def _asd_line_qty_product_uom(self, line):
        if line.product_id and line.product_uom_id and line.product_uom_id != line.product_id.uom_id:
            return line.product_uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
        return line.quantity

    def _asd_line_taxes(self, line):
        return line.tax_ids

    def _asd_line_uom(self, line):
        return line.product_uom_id

    def _asd_partner(self):
        return self.partner_id

    def _asd_date(self):
        return self.invoice_date or fields.Date.context_today(self)

    def _asd_is_refund(self):
        return self.move_type == 'out_refund'

    def _asd_line_model(self):
        return 'account.move.line'

    def _asd_wizard_doc_field(self):
        return 'move_id'

    def _asd_wizard_line_ref(self, line):
        return 'move_line_id'

    def _asd_check_editable(self):
        for move in self:
            if move.move_type not in CUSTOMER_MOVE_TYPES:
                raise UserError(_(
                    'Global sale discounts can only be applied on customer invoices '
                    'and customer credit notes.'))
            if move.state != 'draft':
                raise UserError(_(
                    'The invoice %s is not in draft: reset it to draft before '
                    'changing its global discount.', move.name or _('(draft)')))

    def _asd_write_line_values(self, updates):
        self.write({'invoice_line_ids': [
            Command.update(line.id, vals) for line, vals in updates.items()]})

    def _asd_create_discount_lines(self, vals_list):
        before = self.invoice_line_ids
        self.write({'invoice_line_ids': [Command.create(vals) for vals in vals_list]})
        return (self.invoice_line_ids - before).sorted('id')

    def _asd_unlink_discount_lines(self, lines):
        self.write({'invoice_line_ids': [Command.delete(line.id) for line in lines]})

    def action_post(self):
        self.filtered(lambda m: m.move_type in CUSTOMER_MOVE_TYPES)._asd_check_not_stale(_(
            'The global discount of the invoice %s is out of date: its lines changed '
            'after it was applied. Apply the discount again, or remove it, before confirming.'))
        return super().action_post()

    def copy(self, default=None):
        new_move = super().copy(default)
        # New line ids: take a fresh snapshot so the copy is not seen as changed.
        new_move._asd_refresh_fingerprint()
        return new_move

    def _asd_discount_line_vals(self, product, price_unit, taxes, name, analytic):
        return {
            'product_id': product.id,
            'name': name,
            'quantity': 1.0,
            'product_uom_id': product.uom_id.id,
            'price_unit': price_unit,
            'discount': 0.0,
            'tax_ids': [Command.set(taxes.ids)],
            'asd_is_discount_line': True,
            'asd_discount_origin': 'invoice',
            'analytic_distribution': analytic,
        }
