# Advanced Sale Discount (`advanced_sale_discount`)

Odoo 19.0 Community & Enterprise. Global discounts on **Sales Orders** and
**Customer Invoices / Credit Notes**, the sales-side counterpart of
`advanced_purchase_discount`.

## Configuration
*Sales ▸ Configuration ▸ Settings ▸ Advanced Discounts* (per company)

* **Advanced Sale Discounts** – off by default.
* **Sale Discount Product** – required when enabled. Validated on save: service,
  "Ordered quantities" invoicing policy, same company (or shared), income account
  resolvable for the company, sales-type taxes.
* *Sales ▸ Configuration ▸ Volume Discount Rules* – tiers for mode D.
* Security group **Apply Global Sales Discounts** (implied by Sales Administrator
  and Billing Administrator; grant it to salespeople as needed).

## Modes (button **Apply Discount** on SO and draft customer invoice/credit note)
| Mode | What it does |
|---|---|
| A. Proportional | Percentage or fixed amount spread on eligible lines by value, composed with each line's existing discount (`5% + 10% = 14.5%`). |
| B. Manual Weighted | By weight (share ∝ value × weight), a percentage per line, or an amount per line. |
| C. Dedicated Discount Line | One negative line per tax group using the discount product, carrying the group's taxes (already fiscal-position mapped) and common analytic distribution. |
| D. Smart Tiered Volume | Quantity (product UoM) or untaxed amount (company currency) thresholds, per line or whole document, product / category / contract-customer / validity / company filters. Customer-specific rules win, then sequence. |

Fixed amounts can target the untaxed amount or the tax-included total.

## Financial integrity
* Largest-remainder allocation on the currency unit: allocated amounts always sum to
  the requested discount.
* Line discounts are stored with the `Discount` precision; any cent left over is
  posted on a *Rounding Adjustment* line per tax group (or ignored, if chosen), and
  dedicated lines are trued-up once after creation, so totals are exact.
* Native tax engine everywhere: price-included taxes, fiscal positions, tax rounding.
* Re-applying never compounds: the previous global discount is removed first.
  **Remove Discount** restores the original line discounts.
* Discount lines are excluded from *Update Prices* and keep their taxes on *Update Taxes*.
* A snapshot of the lines is saved when the discount is applied. Any later change
  (product, quantity, unit, price, taxes, a line added or removed, a discount line
  edited) shows an out-of-date banner and blocks **Confirm** on the order and on the
  invoice until the discount is re-applied or removed. Portal acceptance and online
  payment (superuser) are not blocked; context key `asd_skip_stale_check` skips the
  check for integrations. The 1.1.0 upgrade snapshots documents already discounted.

## Lifecycle
* Line discounts and discount lines flow to invoices (`asd_discount_origin = sale`).
* Discount lines are invoiced **in proportion** to what is invoiceable on the lines
  they discount (delivered qty for "Delivered quantities" products), so partial
  invoices carry their share and the final invoice settles the remainder.
* Changing an order discount is blocked once the order is locked or anything is invoiced; apply further
  discounts on the draft invoice (they compose on top and reset independently).
* Mode C posts the discount to the discount product's income account (use a
  dedicated *Sales Discounts* account); modes A/B/D reduce each product's revenue.

## Notes
* Precision: keep *Product Price* decimals ≥ currency decimals (e.g. 3 for KWD)
  so rounding lines can represent the smallest unit.
* With pricelists set to "Show discount to the customer", Odoo resets line discounts
  when quantity/product changes; the stale banner tells you to re-apply.
* Shipping (`is_delivery`), reward (`is_reward_line`) and down-payment lines are
  never discounted.

## Tests
`odoo-bin -d <db> -i advanced_sale_discount --test-tags /advanced_sale_discount`
(requires a chart of accounts, e.g. `l10n_generic_coa`).
