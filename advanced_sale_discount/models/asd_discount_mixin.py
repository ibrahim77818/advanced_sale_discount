# -*- coding: utf-8 -*-
"""Document-agnostic discount logic shared by sales orders and invoices.

Concrete models (``sale.order`` and ``account.move``) inherit the document
mixin and implement the small adapter API (``_asd_*`` methods marked
"adapter" below). Everything else - validation, allocation, residual
handling, reset, traceability - lives here once.
"""
import json
from collections import OrderedDict

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round
from odoo.tools.misc import format_amount

from ..utils.discount_engine import EngineError, build_plan, compose_discount

DISCOUNT_MODES = [
    ('proportional', 'Proportional'),
    ('weighted', 'Manual Weighted'),
    ('line', 'Dedicated Discount Line'),
    ('tiered', 'Smart Tiered Volume'),
]
DISCOUNT_TYPES = [
    ('percent', 'Percentage'),
    ('fixed', 'Fixed Amount'),
]
AMOUNT_BASES = [
    ('untaxed', 'Untaxed Amount'),
    ('total', 'Total (Tax Included)'),
]
WEIGHTED_METHODS = [
    ('weight', 'By Weight'),
    ('line_percent', 'Percentage per Line'),
    ('line_amount', 'Amount per Line'),
]
RESIDUAL_POLICIES = [
    ('line', 'Post Rounding Difference on a Discount Line'),
    ('ignore', 'Ignore Rounding Difference'),
]


class AsdDiscountMixin(models.AbstractModel):
    _name = 'asd.discount.mixin'
    _description = 'Advanced Sale Discount Document'

    # Fields depending on company_id / currency_id (related, Monetary) are
    # declared on the concrete models: the abstract mixin has neither field.
    asd_discount_mode = fields.Selection(
        DISCOUNT_MODES, string='Discount Mode', readonly=True)
    asd_discount_type = fields.Selection(
        DISCOUNT_TYPES, string='Discount Type', readonly=True)
    asd_discount_value = fields.Float(
        string='Discount Value', readonly=True, digits=(16, 4))
    asd_discount_amount_base = fields.Selection(
        AMOUNT_BASES, string='Discount Computed On', readonly=True)
    asd_discount_fingerprint = fields.Text(
        string='Discount Lines Snapshot', readonly=True, copy=False,
        help='Technical: the lines of the document when the global discount was '
             'applied, used to detect later changes.')
    asd_discount_stale = fields.Boolean(
        string='Discount Needs Re-applying', compute='_compute_asd_discount_stale',
        help='Lines were changed after the discount was applied.')

    # ------------------------------------------------------------------
    # Adapter API - implemented by sale.order and account.move
    # ------------------------------------------------------------------
    def _asd_lines(self):
        """Adapter: all non-section lines of the document."""
        raise NotImplementedError()

    def _asd_structural_lines(self):
        """Adapter: lines that may receive a discount (ignoring amounts)."""
        raise NotImplementedError()

    def _asd_own_applied_lines(self):
        """Adapter: lines discounted by this document's own global discount."""
        raise NotImplementedError()

    def _asd_removable_discount_lines(self):
        """Adapter: discount lines created by this document's global discount."""
        raise NotImplementedError()

    def _asd_line_qty(self, line):
        raise NotImplementedError()

    def _asd_line_qty_product_uom(self, line):
        raise NotImplementedError()

    def _asd_line_uom(self, line):
        raise NotImplementedError()

    def _asd_line_taxes(self, line):
        raise NotImplementedError()

    def _asd_partner(self):
        raise NotImplementedError()

    def _asd_date(self):
        raise NotImplementedError()

    def _asd_is_refund(self):
        return False

    def _asd_check_editable(self):
        raise NotImplementedError()

    def _asd_write_line_values(self, updates):
        """Adapter: ``updates`` is an ordered dict ``line -> vals``."""
        raise NotImplementedError()

    def _asd_create_discount_lines(self, vals_list):
        """Adapter: create lines and return them in the order of ``vals_list``."""
        raise NotImplementedError()

    def _asd_unlink_discount_lines(self, lines):
        raise NotImplementedError()

    def _asd_discount_line_vals(self, product, price_unit, taxes, name, analytic):
        raise NotImplementedError()

    def _asd_wizard_line_ref(self, line):
        """Adapter: wizard line field pointing at ``line``."""
        raise NotImplementedError()

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _asd_own_discount_total(self):
        self.ensure_one()
        total = sum(self._asd_own_applied_lines().mapped('asd_discount_amount'))
        total -= sum(self._asd_removable_discount_lines().mapped('price_subtotal'))
        return total

    def _compute_asd_discount_total(self):
        for doc in self:
            lines = doc._asd_lines()
            regular = lines.filtered(lambda l: not l.asd_is_discount_line)
            discount_lines = lines - regular
            doc.asd_discount_total = (
                sum(regular.mapped('asd_discount_amount'))
                - sum(discount_lines.mapped('price_subtotal'))
            )

    def _compute_asd_discount_stale(self):
        digits = self.env['decimal.precision'].precision_get('Discount')
        for doc in self:
            doc.asd_discount_stale = doc._asd_is_discount_stale(digits)

    def _asd_fingerprint(self):
        """Snapshot of everything the global discount was computed from.

        One row per discountable line and per discount line created by this
        document: line, product, quantity, unit of measure, unit price, taxes
        and the line discount before the global discount. Works both on saved
        records and inside onchanges (new lines have no id yet).
        """
        self.ensure_one()
        rows = []
        for line in self._asd_structural_lines() | self._asd_removable_discount_lines():
            discount = line.discount if line.asd_is_discount_line else self._asd_line_base_discount(line)
            rows.append([
                line._origin.id or None,
                bool(line.asd_is_discount_line),
                line.product_id._origin.id or None,
                round(self._asd_line_qty(line) or 0.0, 6),
                self._asd_line_uom(line)._origin.id or None,
                round(line.price_unit or 0.0, 6),
                sorted(self._asd_line_taxes(line)._origin.ids),
                round(discount or 0.0, 6),
            ])
        rows.sort(key=lambda row: (row[0] is None, row[0] or 0, json.dumps(row[1:])))
        return json.dumps(rows)

    def _asd_refresh_fingerprint(self):
        """Snapshot documents carrying their own global discount (not, e.g., an
        invoice that only inherited line discounts from its sales order)."""
        for doc in self.filtered('asd_discount_mode'):
            if doc._asd_own_applied_lines() or doc._asd_removable_discount_lines():
                doc.asd_discount_fingerprint = doc._asd_fingerprint()

    def _asd_check_not_stale(self, message):
        # Portal acceptance and online payment confirm orders as superuser: never
        # break those flows. Internal users are blocked until they re-apply.
        if self.env.su or self.env.context.get('asd_skip_stale_check'):
            return
        stale = self.filtered('asd_discount_stale')
        if stale:
            raise UserError(message % ', '.join(stale.mapped(lambda d: d.name or _('(draft)'))))

    def _asd_is_discount_stale(self, digits):
        self.ensure_one()
        if not self.asd_discount_mode:
            return False
        # Any change to the lines the discount was computed from: product,
        # quantity, unit, price, taxes, a line added or removed.
        if self.asd_discount_fingerprint and self.asd_discount_fingerprint != self._asd_fingerprint():
            return True
        applied = self._asd_own_applied_lines()
        if not applied and not self._asd_removable_discount_lines():
            # e.g. an invoice that only carries the discount of its sales order
            return False
        for line in applied:
            expected = float_round(
                compose_discount(line.asd_base_discount, line.asd_extra_discount),
                precision_digits=digits)
            if float_compare(expected, line.discount, precision_digits=digits):
                return True
        rounding = self.currency_id.rounding
        # Dedicated lines are exact by construction: any gap means they were edited.
        if (self.asd_discount_mode == 'line'
                and self.asd_discount_amount_base == 'untaxed'
                and float_compare(self._asd_own_discount_total(), self.asd_discount_target,
                                  precision_rounding=rounding)):
            return True
        if self.asd_discount_mode == 'proportional':
            new_lines = self._asd_structural_lines().filtered(
                lambda l: not l.asd_discount_applied
                and float_compare(l.price_subtotal, 0.0, precision_rounding=rounding) > 0)
            if new_lines:
                return True
        return False

    # ------------------------------------------------------------------
    # Line values
    # ------------------------------------------------------------------
    def _asd_line_values_at_discount(self, line, discount):
        """Line amounts as if its discount were ``discount`` (in %)."""
        currency = line.currency_id or self.currency_id
        qty = self._asd_line_qty(line)
        price = line.price_unit * (1.0 - (discount or 0.0) / 100.0)
        gross = price * qty
        taxes = self._asd_line_taxes(line)
        if taxes:
            res = taxes.compute_all(
                price, currency, qty, product=line.product_id,
                partner=self._asd_partner(), is_refund=self._asd_is_refund())
            return {'subtotal': res['total_excluded'], 'total': res['total_included'],
                    'gross': gross}
        amount = currency.round(gross)
        return {'subtotal': amount, 'total': amount, 'gross': gross}

    def _asd_line_base_discount(self, line):
        """Discount of the line without this document's global discount."""
        return line.asd_base_discount if line.asd_discount_applied else line.discount

    def _asd_line_actual_values(self, line):
        qty = self._asd_line_qty(line)
        return {
            'subtotal': line.price_subtotal,
            'total': line.price_total,
            'gross': line.price_unit * qty * (1.0 - (line.discount or 0.0) / 100.0),
        }

    def _asd_eligible_lines(self):
        """Lines that can receive a discount, judged without the global discount."""
        rounding = self.currency_id.rounding
        return self._asd_structural_lines().filtered(
            lambda l: float_compare(
                self._asd_line_values_at_discount(l, self._asd_line_base_discount(l))['subtotal'],
                0.0, precision_rounding=rounding) > 0)

    @api.model
    def _asd_tax_key(self, taxes):
        return tuple(sorted(taxes.ids))

    def _asd_group_by_taxes(self, lines):
        groups = OrderedDict()
        for line in lines:
            groups.setdefault(self._asd_tax_key(self._asd_line_taxes(line)), []).append(line)
        return groups

    @api.model
    def _asd_common_analytic(self, lines):
        distributions = {str(line.analytic_distribution or {}) for line in lines}
        if len(distributions) == 1 and lines[0].analytic_distribution:
            return lines[0].analytic_distribution
        return False

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    def _asd_check_access(self):
        if not self.env.user.has_group('advanced_sale_discount.group_sale_discount_user'):
            raise AccessError(_('You are not allowed to apply global discounts.'))

    def _asd_check_ready(self):
        self.ensure_one()
        company = self.company_id
        if not company.asd_discount_enabled:
            raise UserError(_(
                'Advanced sale discounts are not enabled for the company %s. '
                'Enable them in Sales settings.', company.name))
        try:
            company._asd_validate_discount_product(company.asd_discount_product_id)
        except Exception as error:  # ValidationError re-raised as UserError
            raise UserError(error.args[0]) from error

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    @api.model
    def _asd_base_key(self, params):
        if params.get('amount_base') == 'total' and (
                (params.get('discount_type') == 'fixed'
                 and params.get('mode') in ('proportional', 'line'))
                or (params.get('discount_type') == 'fixed' and params.get('mode') == 'weighted'
                    and params.get('weighted_method') == 'weight')
                or (params.get('mode') == 'weighted'
                    and params.get('weighted_method') == 'line_amount')):
            return 'total'
        return 'subtotal'

    def _asd_engine_message(self, error):
        params = error.params
        currency = self.currency_id
        messages = {
            'no_lines': lambda: _('There are no lines eligible for a discount on this document.'),
            'value_not_positive': lambda: _('The discount value must be strictly positive.'),
            'percent_over_100': lambda: _('A percentage discount cannot exceed 100%.'),
            'amount_over_base': lambda: _(
                'The discount amount (%(amount)s) exceeds the discountable amount (%(base)s).',
                amount=format_amount(self.env, params.get('amount', 0.0), currency),
                base=format_amount(self.env, params.get('base', 0.0), currency)),
            'invalid_weights': lambda: _(
                'Weights must be positive and at least one weight must be greater than zero.'),
            'line_over_100': lambda: _(
                'The discount allocated to the line "%s" exceeds its value. '
                'Lower its weight or the discount.', params.get('line')),
            'line_percent_range': lambda: _(
                'The percentage of the line "%s" must be between 0 and 100.', params.get('line')),
            'line_amount_range': lambda: _(
                'The amount of the line "%s" must be between zero and the line value.',
                params.get('line')),
            'nothing_to_apply': lambda: _('Nothing to apply: all line discounts are zero.'),
        }
        return messages.get(error.code, lambda: error.code)()

    def _asd_plan_items(self, lines, values, line_inputs):
        items = []
        for line in lines:
            inputs = line_inputs.get(line.id, {})
            items.append({
                'key': line.id,
                'name': (line.name or line.product_id.display_name or '').split('\n')[0],
                'subtotal': values[line.id]['subtotal'],
                'total': values[line.id]['total'],
                'weight': inputs.get('weight', 1.0),
                'line_percent': inputs.get('line_percent', 0.0),
                'line_amount': inputs.get('line_amount', 0.0),
                'product': line.product_id,
                'qty_uom': self._asd_line_qty_product_uom(line),
            })
        return items

    def _asd_tier_extras(self, items, rule_ids=None):
        self.ensure_one()
        Rule = self.env['sale.discount.tier.rule']
        company = self.company_id
        if rule_ids:
            rules = Rule.browse(rule_ids)
        else:
            rules = Rule.search([('company_id', 'in', [False, company.id])])
        date = self._asd_date()
        data = []
        for item in items:
            data.append({
                'key': item['key'],
                'product': item['product'],
                'qty': item['qty_uom'],
                'amount': self.currency_id._convert(
                    item['subtotal'], company.currency_id, company, date),
            })
        return rules._asd_evaluate(data, self._asd_partner(), date, company)

    def _asd_compute_plan(self, items, params):
        """Return ``key -> {'extra', 'target', 'rule'}`` or raise UserError."""
        self.ensure_one()
        rounding = self.currency_id.rounding
        if not items:
            raise UserError(self._asd_engine_message(EngineError('no_lines')))
        mode = params.get('mode')
        if mode == 'tiered':
            extras = self._asd_tier_extras(items, params.get('tier_rule_ids'))
            if not extras:
                raise UserError(_('No volume discount rule applies to this document.'))
            plan = {}
            for item in items:
                if item['key'] not in extras:
                    continue
                percent, rule = extras[item['key']]
                plan[item['key']] = {
                    'extra': percent,
                    'target': float_round(item['subtotal'] * percent / 100.0,
                                          precision_rounding=rounding),
                    'rule': rule,
                }
            return plan
        try:
            plan = build_plan(
                items, mode, params.get('discount_type'), params.get('value') or 0.0,
                self._asd_base_key(params), params.get('weighted_method'), rounding)
        except EngineError as error:
            raise UserError(self._asd_engine_message(error)) from error
        if mode == 'line':
            for entry in plan.values():
                entry['extra'] = 0.0
        return plan

    # ------------------------------------------------------------------
    # Apply / reset
    # ------------------------------------------------------------------
    def _asd_apply_discount(self, params, line_inputs=None):
        """Apply a global discount described by ``params``.

        ``params`` keys: mode, discount_type, value, amount_base,
        weighted_method, residual_policy, tier_rule_ids.
        ``line_inputs``: ``line_id -> {'weight', 'line_percent', 'line_amount'}``.
        """
        self.ensure_one()
        self._asd_check_access()
        self._asd_check_ready()
        self._asd_check_editable()
        line_inputs = line_inputs or {}
        # Re-applying never compounds: start from the undiscounted document.
        self._asd_reset_discount(post_message=False)
        lines = self._asd_eligible_lines()
        if not lines:
            raise UserError(self._asd_engine_message(EngineError('no_lines')))
        base_key = self._asd_base_key(params)
        values = {line.id: self._asd_line_actual_values(line) for line in lines}
        items = self._asd_plan_items(lines, values, line_inputs)
        plan = self._asd_compute_plan(items, params)
        if params['mode'] == 'line':
            target = self._asd_apply_discount_lines(lines, values, plan, base_key)
        else:
            target = self._asd_apply_line_plan(
                lines, values, plan, base_key, params.get('residual_policy') or 'line')
        self.write({
            'asd_discount_mode': params['mode'],
            'asd_discount_type': params.get('discount_type') if params['mode'] != 'tiered' else 'percent',
            'asd_discount_value': params.get('value') or 0.0,
            'asd_discount_amount_base': 'total' if base_key == 'total' else 'untaxed',
            'asd_discount_target': target,
        })
        # Snapshot taken last, once every line (and any true-up) is final.
        self.asd_discount_fingerprint = self._asd_fingerprint()
        self._asd_post_message(params, target)
        return True

    def _asd_apply_line_plan(self, lines, values, plan, base_key, residual_policy):
        digits = self.env['decimal.precision'].precision_get('Discount')
        rounding = self.currency_id.rounding
        updates = OrderedDict()
        for line in lines:
            entry = plan.get(line.id)
            if not entry or float_is_zero(entry['extra'], precision_digits=6):
                continue
            current = line.discount or 0.0
            updates[line] = {
                'discount': float_round(compose_discount(current, entry['extra']),
                                        precision_digits=digits),
                'asd_discount_applied': True,
                'asd_base_discount': current,
                'asd_extra_discount': entry['extra'],
            }
        if not updates:
            raise UserError(self._asd_engine_message(EngineError('nothing_to_apply')))
        self._asd_write_line_values(updates)

        total_target = 0.0
        residual_vals, residual_expect = [], []
        product = self.company_id.asd_discount_product_id
        for glines in self._asd_group_by_taxes(list(updates)).values():
            target = float_round(sum(plan[l.id]['target'] for l in glines),
                                 precision_rounding=rounding)
            total_target += target
            achieved = sum(values[l.id][base_key] - self._asd_line_actual_values(l)[base_key]
                           for l in glines)
            residual = float_round(target - achieved, precision_rounding=rounding)
            if residual_policy != 'line' or float_is_zero(residual, precision_rounding=rounding):
                continue
            base_before = sum(values[l.id][base_key] for l in glines)
            gross_before = sum(values[l.id]['gross'] for l in glines)
            ratio = gross_before / base_before if base_before else 1.0
            taxes = self._asd_line_taxes(glines[0])
            residual_vals.append(self._asd_discount_line_vals(
                product, -residual * ratio, taxes,
                self._asd_discount_line_name(product, taxes, rounding_adjustment=True),
                self._asd_common_analytic(glines)))
            residual_expect.append((-residual, ratio))
        if residual_vals:
            self._asd_create_and_true_up(residual_vals, residual_expect, base_key)
        return float_round(total_target, precision_rounding=rounding)

    def _asd_apply_discount_lines(self, lines, values, plan, base_key):
        rounding = self.currency_id.rounding
        product = self.company_id.asd_discount_product_id
        vals_list, expected = [], []
        total = 0.0
        for glines in self._asd_group_by_taxes(lines).values():
            target = float_round(sum(plan[l.id]['target'] for l in glines),
                                 precision_rounding=rounding)
            if float_is_zero(target, precision_rounding=rounding):
                continue
            base_g = sum(values[l.id][base_key] for l in glines)
            gross_g = sum(values[l.id]['gross'] for l in glines)
            ratio = gross_g / base_g if base_g else 1.0
            taxes = self._asd_line_taxes(glines[0])
            vals_list.append(self._asd_discount_line_vals(
                product, -target * ratio, taxes,
                self._asd_discount_line_name(product, taxes),
                self._asd_common_analytic(glines)))
            expected.append((-target, ratio))
            total += target
        if not vals_list:
            raise UserError(self._asd_engine_message(EngineError('nothing_to_apply')))
        self._asd_create_and_true_up(vals_list, expected, base_key)
        return float_round(total, precision_rounding=rounding)

    def _asd_create_and_true_up(self, vals_list, expected, base_key):
        """Create discount lines then correct the unit price once so that each
        line's amount matches exactly what was allocated to it."""
        rounding = self.currency_id.rounding
        price_digits = self.env['decimal.precision'].precision_get('Product Price')
        keep_vals, keep_expected = [], []
        for vals, exp in zip(vals_list, expected):
            if float_is_zero(vals['price_unit'], precision_digits=price_digits):
                continue  # smaller than the price precision: cannot be represented
            keep_vals.append(vals)
            keep_expected.append(exp)
        if not keep_vals:
            return self.env[self._asd_line_model()]
        lines = self._asd_create_discount_lines(keep_vals)
        corrections = OrderedDict()
        for line, (amount, ratio) in zip(lines, keep_expected):
            actual = self._asd_line_actual_values(line)[base_key]
            diff = float_round(amount - actual, precision_rounding=rounding)
            if not float_is_zero(diff, precision_rounding=rounding):
                corrections[line] = {'price_unit': line.price_unit + diff * ratio}
        if corrections:
            self._asd_write_line_values(corrections)
        return lines

    def _asd_discount_line_name(self, product, taxes, rounding_adjustment=False):
        tax_names = ', '.join(taxes.mapped('name')) or _('No Taxes')
        if rounding_adjustment:
            return _('%(product)s - Rounding Adjustment (%(taxes)s)',
                     product=product.name, taxes=tax_names)
        return _('%(product)s (%(taxes)s)', product=product.name, taxes=tax_names)

    def _asd_reset_discount(self, post_message=True):
        self.ensure_one()
        self._asd_check_editable()
        applied = self._asd_own_applied_lines()
        removable = self._asd_removable_discount_lines()
        if applied:
            self._asd_write_line_values(OrderedDict(
                (line, {
                    'discount': line.asd_base_discount,
                    'asd_discount_applied': False,
                    'asd_base_discount': 0.0,
                    'asd_extra_discount': 0.0,
                }) for line in applied))
        if removable:
            self._asd_unlink_discount_lines(removable)
        self.write({
            'asd_discount_mode': False,
            'asd_discount_type': False,
            'asd_discount_value': 0.0,
            'asd_discount_amount_base': False,
            'asd_discount_target': 0.0,
            'asd_discount_fingerprint': False,
        })
        if post_message and (applied or removable):
            self.message_post(body=Markup('<p>%s</p>') % _('The global discount was removed.'))
        return True

    def _asd_post_message(self, params, target):
        modes = dict(self._fields['asd_discount_mode']._description_selection(self.env))
        if params['mode'] == 'tiered':
            detail = _('volume tiers')
        elif params['mode'] == 'weighted' and params.get('weighted_method') != 'weight':
            methods = dict(self.env['asd.discount.wizard']._fields['weighted_method']
                           ._description_selection(self.env))
            detail = methods.get(params.get('weighted_method'), '')
        elif params.get('discount_type') == 'percent':
            detail = '%s%%' % params.get('value')
        else:
            detail = format_amount(self.env, params.get('value') or 0.0, self.currency_id)
        body = _('Global discount applied - %(mode)s: %(detail)s. Discount amount: %(amount)s.',
                 mode=modes.get(params['mode'], params['mode']), detail=detail,
                 amount=format_amount(self.env, target, self.currency_id))
        self.message_post(body=Markup('<p>%s</p>') % body)

    # ------------------------------------------------------------------
    # Wizard support
    # ------------------------------------------------------------------
    def _asd_wizard_line_vals(self):
        self.ensure_one()
        vals_list = []
        for sequence, line in enumerate(self._asd_eligible_lines(), start=1):
            base_discount = self._asd_line_base_discount(line)
            values = self._asd_line_values_at_discount(line, base_discount)
            vals = {
                'sequence': sequence,
                'name': (line.name or line.product_id.display_name or '').split('\n')[0],
                'product_id': line.product_id.id,
                'qty_product_uom': self._asd_line_qty_product_uom(line),
                'base_subtotal': values['subtotal'],
                'base_total': values['total'],
                'current_discount': base_discount,
                'weight': 1.0,
            }
            vals[self._asd_wizard_line_ref(line)] = line.id
            vals_list.append(vals)
        return vals_list

    def action_open_asd_discount_wizard(self):
        self.ensure_one()
        self._asd_check_access()
        self._asd_check_ready()
        self._asd_check_editable()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apply Discount'),
            'res_model': 'asd.discount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {self._asd_wizard_doc_field(): self.id,
                        'default_' + self._asd_wizard_doc_field(): self.id},
        }

    def action_asd_reset_discount(self):
        for doc in self:
            doc._asd_check_access()
            doc._asd_reset_discount()
        return True


class AsdDiscountLineMixin(models.AbstractModel):
    _name = 'asd.discount.line.mixin'
    _description = 'Advanced Sale Discount Line'

    asd_is_discount_line = fields.Boolean(
        string='Discount Line', readonly=True,
        help='Line created by a global discount (dedicated line or rounding adjustment).')
    asd_discount_applied = fields.Boolean(
        string='Global Discount Applied', readonly=True)
    asd_base_discount = fields.Float(
        string='Discount Before Global Discount (%)', digits='Discount', readonly=True)
    asd_extra_discount = fields.Float(
        string='Global Discount (%)', digits=(16, 6), readonly=True)

    def _asd_document(self):
        raise NotImplementedError()

    def _compute_asd_discount_amount(self):
        for line in self:
            if line.asd_is_discount_line or float_is_zero(line.asd_extra_discount,
                                                          precision_digits=6):
                line.asd_discount_amount = 0.0
                continue
            doc = line._asd_document()
            before = doc._asd_line_values_at_discount(line, line.asd_base_discount)['subtotal']
            line.asd_discount_amount = before - line.price_subtotal
