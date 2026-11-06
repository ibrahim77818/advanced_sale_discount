# -*- coding: utf-8 -*-
{
    'name': 'Advanced Sale Discount',
    'version': '17.0.1.1.0',
    'category': 'Sales/Sales',
    'summary': 'Percentage or fixed global discounts on sales orders and customer '
               'invoices: proportional, weighted, dedicated discount line and '
               'tiered volume modes',
    'description': """
Advanced Sale Discount
======================
Global discounts on Sales Orders and Customer Invoices / Credit Notes:

* Percentage or fixed amount, on the untaxed or tax-included total
* Proportional, manual weighted, dedicated discount line (one per tax group)
  and smart tiered volume / contract discounts
* Exact amounts: largest-remainder allocation and automatic rounding adjustment
* Discount carried from the sales order to (partial) invoices and journal entries
* Company-level settings, multi-company and Arabic translation
""",
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['sale', 'account'],
    'data': [
        'security/advanced_sale_discount_security.xml',
        'security/ir.model.access.csv',
        'wizard/asd_discount_wizard_views.xml',
        'views/sale_discount_tier_rule_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
