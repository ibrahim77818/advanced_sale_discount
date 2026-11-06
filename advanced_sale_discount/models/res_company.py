# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    asd_discount_enabled = fields.Boolean(
        string='Advanced Sale Discounts',
        default=False,
        help='Allow percentage and fixed-amount discounts on sales orders '
             'and customer invoices for this company.',
    )
    asd_discount_product_id = fields.Many2one(
        'product.product',
        string='Sale Discount Product',
        ondelete='restrict',
        domain="[('type', '=', 'service'), ('sale_ok', '=', True), "
               "'|', ('company_id', '=', False), ('company_id', '=', id)]",
        help='Service product used on dedicated discount lines and on rounding '
             'adjustment lines. Its income account receives the discount.',
    )

    @api.constrains('asd_discount_enabled', 'asd_discount_product_id')
    def _check_asd_discount_product(self):
        for company in self:
            if not company.asd_discount_enabled:
                continue
            if not company.asd_discount_product_id:
                raise ValidationError(_(
                    'Please select a discount product to enable advanced sale '
                    'discounts for the company %s.', company.name))
            company._asd_validate_discount_product(company.asd_discount_product_id)

    def _asd_validate_discount_product(self, product):
        """Check that ``product`` can be used as discount product for ``self``.

        Raises a ValidationError explaining the first problem found.
        """
        self.ensure_one()
        if product.type != 'service':
            raise ValidationError(_(
                'The discount product "%s" must be a service.', product.display_name))
        if product.company_id and product.company_id != self:
            raise ValidationError(_(
                'The discount product "%(product)s" belongs to another company '
                'than %(company)s.', product=product.display_name, company=self.name))
        if product.invoice_policy != 'order':
            raise ValidationError(_(
                'The discount product "%s" must use the "Ordered quantities" '
                'invoicing policy.', product.display_name))
        accounts = product.product_tmpl_id.with_company(self).get_product_accounts()
        if not accounts.get('income'):
            raise ValidationError(_(
                'The discount product "%(product)s" has no income account for '
                'the company %(company)s. Set one on the product or on its '
                'category.', product=product.display_name, company=self.name))
        wrong_taxes = product.taxes_id.filtered(
            lambda t: t.company_id == self and t.type_tax_use not in ('sale', 'none'))
        if wrong_taxes:
            raise ValidationError(_(
                'The customer taxes of the discount product "%s" must be sales taxes.',
                product.display_name))
        return True
