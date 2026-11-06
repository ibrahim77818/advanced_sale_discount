# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class SaleDiscountTierRule(models.Model):
    _name = 'sale.discount.tier.rule'
    _description = 'Sales Volume Discount Rule'
    _order = 'sequence, id'

    name = fields.Char(string='Rule Name', required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
        help='Leave empty to use the rule in all companies.')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', compute='_compute_currency_id',
        help='Amount thresholds are expressed in the company currency.')
    scope = fields.Selection(
        [('line', 'Per Line'), ('order', 'Whole Document')],
        string='Applies On', required=True, default='line',
        help='Per Line: each matching line is evaluated on its own quantity or amount.\n'
             'Whole Document: the matching lines are summed and the reached tier '
             'is applied to all of them.')
    basis = fields.Selection(
        [('quantity', 'Quantity'), ('amount', 'Untaxed Amount')],
        string='Threshold Based On', required=True, default='quantity')
    partner_ids = fields.Many2many(
        'res.partner', string='Contract Customers',
        help='Restrict the rule to these customers (contract price agreement). '
             'Customer-specific rules take precedence over general rules.')
    product_ids = fields.Many2many('product.product', string='Products')
    categ_ids = fields.Many2many(
        'product.category', string='Product Categories',
        help='Products of these categories and their sub-categories.')
    date_start = fields.Date(string='Valid From')
    date_end = fields.Date(string='Valid Until')
    tier_ids = fields.One2many(
        'sale.discount.tier', 'rule_id', string='Tiers', copy=True)
    note = fields.Text(string='Notes')

    @api.depends('company_id')
    def _compute_currency_id(self):
        for rule in self:
            rule.currency_id = (rule.company_id or self.env.company).currency_id

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rule in self:
            if rule.date_start and rule.date_end and rule.date_end < rule.date_start:
                raise ValidationError(_(
                    'The end date of the rule "%s" must be after its start date.', rule.name))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def _asd_match_document(self, partner, date, company):
        self.ensure_one()
        if self.company_id and self.company_id != company:
            return False
        if self.date_start and date and date < self.date_start:
            return False
        if self.date_end and date and date > self.date_end:
            return False
        if self.partner_ids:
            partners = partner | partner.commercial_partner_id
            if not (partners & self.partner_ids):
                return False
        return True

    def _asd_match_product(self, product):
        self.ensure_one()
        if not product:
            return False
        if not self.product_ids and not self.categ_ids:
            return True
        if product in self.product_ids:
            return True
        category_path = product.categ_id.parent_path or ''
        return any(category_path.startswith(categ.parent_path or '/')
                   for categ in self.categ_ids)

    def _asd_tier_percent(self, value):
        self.ensure_one()
        for tier in self.tier_ids.sorted('min_value', reverse=True):
            if float_compare(value, tier.min_value, precision_digits=6) >= 0:
                return tier.discount_percent
        return 0.0

    def _asd_evaluate(self, items, partner, date, company):
        """Evaluate the rules in ``self`` on ``items``.

        :param items: list of dicts ``key, product, qty, amount`` where
            ``qty`` is in the product's UoM and ``amount`` is untaxed, in the
            company currency.
        :return: dict ``key -> (percent, rule)``. Customer-specific rules are
            evaluated first, then by sequence; the first rule whose tier is
            reached wins for a given line.
        """
        rules = self.filtered(lambda r: r.active and r._asd_match_document(partner, date, company))
        rules = rules.sorted(key=lambda r: (0 if r.partner_ids else 1, r.sequence, r.id))
        result = {}
        for rule in rules:
            matching = [item for item in items
                        if item['key'] not in result and rule._asd_match_product(item['product'])]
            if not matching:
                continue
            field = 'qty' if rule.basis == 'quantity' else 'amount'
            if rule.scope == 'line':
                for item in matching:
                    percent = rule._asd_tier_percent(item[field])
                    if percent:
                        result[item['key']] = (percent, rule)
            else:
                percent = rule._asd_tier_percent(sum(item[field] for item in matching))
                if percent:
                    for item in matching:
                        result[item['key']] = (percent, rule)
        return result


class SaleDiscountTier(models.Model):
    _name = 'sale.discount.tier'
    _description = 'Sales Volume Discount Tier'
    _order = 'rule_id, min_value'

    rule_id = fields.Many2one(
        'sale.discount.tier.rule', string='Rule', required=True, ondelete='cascade')
    min_value = fields.Float(
        string='Minimum Threshold', required=True, digits='Product Unit',
        help='Quantity or untaxed amount (company currency) from which this tier applies.')
    discount_percent = fields.Float(
        string='Discount (%)', required=True, digits='Discount')

    _rule_threshold_unique = models.Constraint(
        'unique(rule_id, min_value)',
        'Two tiers of the same rule cannot have the same threshold.',
    )

    @api.constrains('min_value', 'discount_percent')
    def _check_values(self):
        for tier in self:
            if tier.min_value < 0:
                raise ValidationError(_('A tier threshold cannot be negative.'))
            if tier.discount_percent <= 0 or tier.discount_percent > 100:
                raise ValidationError(_(
                    'A tier discount must be greater than 0% and at most 100%.'))
