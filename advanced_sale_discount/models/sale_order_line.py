# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import float_round


class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = ['sale.order.line', 'asd.discount.line.mixin']

    asd_discount_amount = fields.Monetary(
        string='Global Discount Amount', compute='_compute_asd_discount_amount',
        currency_field='currency_id')

    def _asd_document(self):
        return self.order_id

    @api.depends('price_unit', 'discount', 'product_uom_qty', 'tax_id', 'price_subtotal',
                 'asd_base_discount', 'asd_extra_discount', 'asd_is_discount_line')
    def _compute_asd_discount_amount(self):
        return super()._compute_asd_discount_amount()

    # ------------------------------------------------------------------
    # Keep discount lines stable against native recomputations
    # ------------------------------------------------------------------
    def _compute_price_unit(self):
        # Like invoiced lines in core, discount lines keep their stored price.
        regular = self.filtered(lambda l: not l.asd_is_discount_line)
        return super(SaleOrderLine, regular)._compute_price_unit()

    def _compute_discount(self):
        regular = self.filtered(lambda l: not l.asd_is_discount_line)
        return super(SaleOrderLine, regular)._compute_discount()

    def _compute_tax_id(self):
        discount_lines = self.filtered('asd_is_discount_line')
        res = super(SaleOrderLine, self - discount_lines)._compute_tax_id()
        # A discount line follows the taxes of the lines it discounts (already
        # mapped by the fiscal position), e.g. after "Update Taxes".
        for line in discount_lines:
            order = line.order_id
            if not order:
                continue
            taxes = line.tax_id
            if order.fiscal_position_id:
                taxes = order.fiscal_position_id.map_tax(taxes)
            groups = {}
            for source in order._asd_structural_lines():
                groups.setdefault(order._asd_tax_key(source.tax_id), source.tax_id)
            if order._asd_tax_key(taxes) not in groups and len(groups) == 1:
                taxes = next(iter(groups.values()))
            line.tax_id = taxes
        return res

    @api.depends('order_id.order_line.qty_delivered', 'order_id.order_line.product_uom_qty',
                 'order_id.order_line.price_subtotal', 'order_id.order_line.tax_id')
    def _compute_qty_to_invoice(self):
        """Invoice discount lines in proportion to what is invoiceable on the
        lines they discount, so partial invoices carry their share of the
        discount and the last invoice settles the remainder exactly."""
        res = super()._compute_qty_to_invoice()
        for line in self:
            if not line.asd_is_discount_line or line.state not in ('sale', 'done'):
                continue
            sources = line.order_id._asd_source_lines_for(line)
            weight_total = sum(abs(s.price_subtotal) for s in sources)
            if not weight_total:
                continue
            invoiceable = 0.0
            for source in sources:
                if not source.product_uom_qty:
                    continue
                if source.product_id.invoice_policy == 'delivery':
                    ratio = min(source.qty_delivered / source.product_uom_qty, 1.0)
                else:
                    ratio = 1.0
                invoiceable += abs(source.price_subtotal) * ratio
            target = float_round(line.product_uom_qty * invoiceable / weight_total,
                                 precision_rounding=line.product_uom.rounding or 0.01)
            line.qty_to_invoice = target - line.qty_invoiced
        return res

    def _check_line_unlink(self):
        # Allow removing a not-yet-invoiced global discount line on a confirmed
        # order (re-applying or removing the discount).
        lines = super()._check_line_unlink()
        return lines.filtered(lambda l: not (l.asd_is_discount_line and not l.invoice_lines))

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        if self.asd_is_discount_line or self.asd_discount_applied:
            vals.update({
                'asd_is_discount_line': self.asd_is_discount_line,
                'asd_base_discount': self.asd_base_discount,
                'asd_extra_discount': self.asd_extra_discount,
                'asd_discount_origin': 'sale',
            })
        return vals
