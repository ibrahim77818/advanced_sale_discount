# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from ..models.asd_discount_mixin import (
    AMOUNT_BASES, DISCOUNT_MODES, DISCOUNT_TYPES, RESIDUAL_POLICIES, WEIGHTED_METHODS,
)
from ..utils.discount_engine import compose_discount


class AsdDiscountWizard(models.TransientModel):
    _name = 'asd.discount.wizard'
    _description = 'Apply Sales Discount'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True)
    move_id = fields.Many2one('account.move', string='Invoice', readonly=True)
    company_id = fields.Many2one('res.company', compute='_compute_document_info')
    currency_id = fields.Many2one('res.currency', compute='_compute_document_info')

    mode = fields.Selection(
        DISCOUNT_MODES, string='Distribution', required=True, default='proportional',
        help='Proportional: spread the discount on the lines in proportion to their value.\n'
             'Manual Weighted: decide yourself how much each line receives.\n'
             'Dedicated Discount Line: add one negative line per tax group.\n'
             'Smart Tiered Volume: apply the volume discount rules reached by the lines.')
    discount_type = fields.Selection(
        DISCOUNT_TYPES, string='Discount Type', required=True, default='percent')
    discount_value = fields.Float(string='Discount', digits=(16, 4))
    amount_base = fields.Selection(
        AMOUNT_BASES, string='Amount Expressed On', required=True, default='untaxed',
        help='Whether the fixed amount is deducted from the untaxed amount or from '
             'the total including taxes.')
    weighted_method = fields.Selection(
        WEIGHTED_METHODS, string='Allocation Method', required=True, default='weight')
    residual_policy = fields.Selection(
        RESIDUAL_POLICIES, string='Rounding Difference', required=True, default='line',
        help='Percentages are stored with limited decimals. When the discount reached '
             'on the lines differs from the requested amount by a few cents, the '
             'difference can be posted on a small adjustment line so totals are exact.')
    tier_rule_ids = fields.Many2many(
        'sale.discount.tier.rule', string='Volume Rules',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Leave empty to evaluate all active volume discount rules.')
    line_ids = fields.One2many('asd.discount.wizard.line', 'wizard_id', string='Lines')

    show_global_value = fields.Boolean(compute='_compute_visibility')
    show_amount_base = fields.Boolean(compute='_compute_visibility')
    total_base = fields.Monetary(
        string='Discountable Amount', compute='_compute_preview', currency_field='currency_id')
    total_discount = fields.Monetary(
        string='Discount Preview', compute='_compute_preview', currency_field='currency_id')
    preview_error = fields.Char(string='Preview Error', compute='_compute_preview')

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        doc = self._asd_document_from_values(res)
        if not doc:
            return res
        if 'line_ids' in fields_list and not res.get('line_ids'):
            res['line_ids'] = [Command.create(vals) for vals in doc._asd_wizard_line_vals()]
        if doc.asd_discount_mode:
            # Re-open with the settings used last time.
            res.update({
                'mode': doc.asd_discount_mode,
                'discount_type': doc.asd_discount_type or 'percent',
                'discount_value': doc.asd_discount_value,
                'amount_base': doc.asd_discount_amount_base or 'untaxed',
            })
        return res

    @api.model
    def _asd_document_from_values(self, values):
        if values.get('sale_order_id'):
            return self.env['sale.order'].browse(values['sale_order_id'])
        if values.get('move_id'):
            return self.env['account.move'].browse(values['move_id'])
        return None

    def _asd_document(self):
        self.ensure_one()
        return self.sale_order_id or self.move_id

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('sale_order_id', 'move_id')
    def _compute_document_info(self):
        for wizard in self:
            doc = wizard.sale_order_id or wizard.move_id
            wizard.company_id = doc.company_id if doc else self.env.company
            wizard.currency_id = doc.currency_id if doc else self.env.company.currency_id

    @api.depends('mode', 'discount_type', 'weighted_method')
    def _compute_visibility(self):
        for wizard in self:
            global_value = wizard.mode in ('proportional', 'line') or (
                wizard.mode == 'weighted' and wizard.weighted_method == 'weight')
            wizard.show_global_value = global_value
            wizard.show_amount_base = (global_value and wizard.discount_type == 'fixed') or (
                wizard.mode == 'weighted' and wizard.weighted_method == 'line_amount')

    def _asd_params(self):
        self.ensure_one()
        return {
            'mode': self.mode,
            'discount_type': self.discount_type,
            'value': self.discount_value,
            'amount_base': self.amount_base,
            'weighted_method': self.weighted_method,
            'residual_policy': self.residual_policy,
            'tier_rule_ids': self.tier_rule_ids.ids,
        }

    def _asd_items(self):
        self.ensure_one()
        return [{
            'key': line._asd_key(),
            'name': line.name or '',
            'subtotal': line.base_subtotal,
            'total': line.base_total,
            'weight': line.weight,
            'line_percent': line.line_percent,
            'line_amount': line.line_amount,
            'product': line.product_id,
            'qty_uom': line.qty_product_uom,
        } for line in self.line_ids]

    def _asd_preview_plan(self):
        """Return ``(plan, error_message)`` without raising."""
        self.ensure_one()
        doc = self._asd_document()
        if not doc or not self.line_ids:
            return {}, False
        try:
            return doc._asd_compute_plan(self._asd_items(), self._asd_params()), False
        except UserError as error:
            return {}, error.args[0]

    @api.depends('mode', 'discount_type', 'discount_value', 'amount_base', 'weighted_method',
                 'tier_rule_ids', 'line_ids.weight', 'line_ids.line_percent',
                 'line_ids.line_amount', 'line_ids.base_subtotal', 'line_ids.base_total')
    def _compute_preview(self):
        for wizard in self:
            plan, error = wizard._asd_preview_plan()
            base_key = 'base_total' if (
                wizard.show_amount_base and wizard.amount_base == 'total') else 'base_subtotal'
            wizard.total_base = sum(wizard.line_ids.mapped(base_key))
            wizard.total_discount = sum(entry['target'] for entry in plan.values())
            wizard.preview_error = error

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        doc = self._asd_document()
        if not doc:
            raise UserError(_('The discount wizard is not linked to any document.'))
        line_inputs = {}
        for line in self.line_ids:
            doc_line = line.sale_line_id or line.move_line_id
            if doc_line:
                line_inputs[doc_line.id] = {
                    'weight': line.weight,
                    'line_percent': line.line_percent,
                    'line_amount': line.line_amount,
                }
        doc._asd_apply_discount(self._asd_params(), line_inputs)
        return {'type': 'ir.actions.act_window_close'}


class AsdDiscountWizardLine(models.TransientModel):
    _name = 'asd.discount.wizard.line'
    _description = 'Apply Sales Discount - Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('asd.discount.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    sale_line_id = fields.Many2one('sale.order.line', string='Order Line')
    move_line_id = fields.Many2one('account.move.line', string='Invoice Line')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    name = fields.Char(string='Description')
    product_id = fields.Many2one('product.product', string='Product')
    qty_product_uom = fields.Float(
        string='Quantity', digits='Product Unit of Measure',
        help='Quantity expressed in the product unit of measure.')
    base_subtotal = fields.Monetary(string='Untaxed Amount', currency_field='currency_id')
    base_total = fields.Monetary(string='Total', currency_field='currency_id')
    current_discount = fields.Float(string='Current Discount (%)', digits='Discount')
    weight = fields.Float(string='Weight', default=1.0, digits=(16, 4))
    line_percent = fields.Float(string='Line Discount (%)', digits=(16, 4))
    line_amount = fields.Monetary(string='Line Discount Amount', currency_field='currency_id')
    preview_discount = fields.Float(
        string='New Discount (%)', digits='Discount', compute='_compute_preview')
    preview_amount = fields.Monetary(
        string='Discount Amount', compute='_compute_preview', currency_field='currency_id')
    tier_rule_id = fields.Many2one(
        'sale.discount.tier.rule', string='Volume Rule', compute='_compute_preview')

    def _asd_key(self):
        """Stable key of a wizard line: the id of the document line it mirrors."""
        self.ensure_one()
        return (self.sale_line_id or self.move_line_id).id

    @api.depends('wizard_id.mode', 'wizard_id.discount_type', 'wizard_id.discount_value',
                 'wizard_id.amount_base', 'wizard_id.weighted_method', 'wizard_id.tier_rule_ids',
                 'wizard_id.line_ids.weight', 'wizard_id.line_ids.line_percent',
                 'wizard_id.line_ids.line_amount', 'weight', 'line_percent', 'line_amount')
    def _compute_preview(self):
        plans = {}
        for line in self:
            wizard = line.wizard_id
            if wizard not in plans:
                plans[wizard] = wizard._asd_preview_plan()[0] if wizard else {}
            entry = plans[wizard].get(line._asd_key())
            if entry:
                line.preview_discount = compose_discount(line.current_discount, entry['extra'])
                line.preview_amount = entry['target']
                line.tier_rule_id = entry.get('rule') or False
            else:
                line.preview_discount = line.current_discount
                line.preview_amount = 0.0
                line.tier_rule_id = False
