# Advanced Sale Discount

Odoo app (`advanced_sale_discount`) for **global discounts on Sales Orders and Customer
Invoices / Credit Notes**: a percentage or a fixed amount off the whole document,
distributed the way you choose and exact to the cent all the way to the journal entry.

**This branch: Odoo 17.0** (Community & Enterprise) · module version `17.0.1.1.0`

## Branches

| Branch | Odoo | Status |
|---|---|---|
| [`16.0`](../../tree/16.0) | 16.0 | Community & Enterprise |
| [`17.0`](../../tree/17.0) | 17.0 | Community & Enterprise |
| [`18.0`](../../tree/18.0) | 18.0 | Community & Enterprise |
| [`19.0`](../../tree/19.0) | 19.0 | Community & Enterprise |

Use the branch that matches your Odoo version. Each one is ported from the previous one,
so the commits on a branch show exactly what changed for that version.

## Features

* **Four distribution modes** from one *Apply Discount* button:
  * **Proportional** – spread on the lines by value, combined with existing line discounts.
  * **Manual Weighted** – a weight, a percentage or an amount per line.
  * **Dedicated Discount Line** – one negative line per tax group, with the group's taxes
    (fiscal position mapped) and analytic distribution, posted to the discount product's
    income account.
  * **Smart Tiered Volume** – quantity or amount tiers, per line or per document, for
    products, categories, contract customers, dates and companies.
* Percentage or fixed amount, on the untaxed amount or the tax-included total.
* **No rounding leakage**: largest-remainder allocation plus automatic
  *Rounding Adjustment* lines per tax group.
* **Out-of-date detection**: a snapshot of the lines is saved when the discount is applied;
  any change to product, quantity, unit, price, taxes or lines shows a banner and blocks
  confirming the order / posting the invoice until the discount is re-applied or removed.
* Discounts flow to invoices; discount lines are invoiced **in proportion to delivery**.
* Company-level settings, multi-company record rules, dedicated security group.
* **Arabic** translation included (`i18n/ar.po`), plus a `.pot` template.

## Installation

1. Copy the `advanced_sale_discount` folder into your addons path
   (on Odoo.sh: push this branch, or add the repo as a submodule).
2. Update the apps list and install **Advanced Sale Discount**.
3. *Sales ▸ Configuration ▸ Settings ▸ Advanced Discounts*: enable it and choose the
   discount service product (it needs an income account, ideally *Sales Discounts*).
4. Grant **Apply Global Sales Discounts** to the salespeople who may give discounts
   (Sales and Billing administrators have it).

Volume rules: *Sales ▸ Configuration ▸ Volume Discount Rules*.

## Tests

```
odoo-bin -d <db> -i advanced_sale_discount --test-tags /advanced_sale_discount
```
87 automated tests (a chart of accounts must be installed). More detail in
[`advanced_sale_discount/README.md`](advanced_sale_discount/README.md).

## Author & license

Ibrahim Yahia · [LinkedIn](https://www.linkedin.com/in/ibrahim-yahia) ·
ibrahim.yahiah@gmail.com — License **LGPL-3**.
