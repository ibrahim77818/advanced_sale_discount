# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'asd.discount.mixin']

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

    @api.depends('order_line.price_subtotal', 'order_line.asd_discount_amount',
                 'order_line.asd_is_discount_line')
    def _compute_asd_discount_total(self):
        return super()._compute_asd_discount_total()

    @api.depends('asd_discount_mode', 'asd_discount_type', 'asd_discount_target',
                 'asd_discount_amount_base', 'asd_discount_fingerprint', 'order_line',
                 'order_line.product_id', 'order_line.product_uom_qty',
                 'order_line.product_uom', 'order_line.price_unit', 'order_line.tax_id',
                 'order_line.display_type', 'order_line.discount',
                 'order_line.asd_base_discount', 'order_line.asd_extra_discount',
                 'order_line.asd_discount_applied', 'order_line.price_subtotal',
                 'order_line.asd_is_discount_line')
    def _compute_asd_discount_stale(self):
        return super()._compute_asd_discount_stale()

    # ------------------------------------------------------------------
    # Adapter API
    # ------------------------------------------------------------------
    def _asd_lines(self):
        return self.order_line.filtered(lambda l: not l.display_type)

    def _asd_structural_lines(self):
        return self.order_line.filtered(
            lambda l: not l.display_type
            and not l.asd_is_discount_line
            and not l.is_downpayment
            and l.product_id
            and not getattr(l, 'is_delivery', False)
            and not getattr(l, 'is_reward_line', False))

    def _asd_own_applied_lines(self):
        return self.order_line.filtered('asd_discount_applied')

    def _asd_removable_discount_lines(self):
        return self.order_line.filtered('asd_is_discount_line')

    def _asd_line_qty(self, line):
        return line.product_uom_qty

    def _asd_line_qty_product_uom(self, line):
        if line.product_id and line.product_uom and line.product_uom != line.product_id.uom_id:
            return line.product_uom._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
        return line.product_uom_qty

    def _asd_line_taxes(self, line):
        return line.tax_id

    def _asd_line_uom(self, line):
        return line.product_uom

    def _asd_partner(self):
        return self.partner_id

    def _asd_date(self):
        return self.date_order.date() if self.date_order else fields.Date.context_today(self)

    def _asd_line_model(self):
        return 'sale.order.line'

    def _asd_wizard_doc_field(self):
        return 'sale_order_id'

    def _asd_wizard_line_ref(self, line):
        return 'sale_line_id'

    def _asd_check_editable(self):
        for order in self:
            if order.state not in ('draft', 'sent', 'sale') or order.locked:
                raise UserError(_(
                    'Global discounts can only be changed on quotations and on '
                    'confirmed sales orders that are not locked or cancelled.'))
            if any(line.qty_invoiced for line in order.order_line):
                raise UserError(_(
                    'The sales order %s is already (partially) invoiced: its global '
                    'discount can no longer be changed. Apply the discount on the '
                    'invoice instead.', order.name))

    def _asd_write_line_values(self, updates):
        for line, vals in updates.items():
            line.write(vals)

    def _asd_create_discount_lines(self, vals_list):
        sequence = max(self.order_line.mapped('sequence') or [10]) + 1
        for offset, vals in enumerate(vals_list):
            vals.update(order_id=self.id, sequence=sequence + offset)
        return self.env['sale.order.line'].create(vals_list)

    def _asd_unlink_discount_lines(self, lines):
        lines.unlink()

    def _asd_discount_line_vals(self, product, price_unit, taxes, name, analytic):
        return {
            'product_id': product.id,
            'name': name,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'price_unit': price_unit,
            'discount': 0.0,
            'tax_id': [Command.set(taxes.ids)],
            'asd_is_discount_line': True,
            'analytic_distribution': analytic,
        }

    def _asd_source_lines_for(self, discount_line):
        """Regular lines sharing the tax set of ``discount_line``."""
        key = self._asd_tax_key(discount_line.tax_id)
        return self._asd_structural_lines().filtered(
            lambda l: self._asd_tax_key(l.tax_id) == key)

    # ------------------------------------------------------------------
    # Native hooks
    # ------------------------------------------------------------------
    def action_confirm(self):
        self._asd_check_not_stale(_(
            'The global discount of %s is out of date: the order lines changed after '
            'it was applied. Apply the discount again, or remove it, before confirming.'))
        return super().action_confirm()

    def copy(self, default=None):
        new_order = super().copy(default)
        # New line ids: take a fresh snapshot so the copy is not seen as changed.
        new_order._asd_refresh_fingerprint()
        return new_order

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.asd_discount_mode:
            vals.update({
                'asd_discount_mode': self.asd_discount_mode,
                'asd_discount_type': self.asd_discount_type,
                'asd_discount_value': self.asd_discount_value,
                'asd_discount_amount_base': self.asd_discount_amount_base,
            })
        return vals

    def _get_update_prices_lines(self):
        # "Update Prices" must never reprice global discount lines.
        lines = super()._get_update_prices_lines()
        return lines.filtered(lambda l: not l.asd_is_discount_line)
