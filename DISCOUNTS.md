# Discount codes

Open **Admin → Payments → Discount codes → Add discount code**.

- **Code / name**: a case-insensitive customer code and an internal description.
- **Discount type / value**: percentage (0.01–100) or one fixed CAD amount off the eligible products together.
- **All products**: all paid classes, recorded courses and payment-page products. Disable it to select teachers (their paid classes), courses or payment-page products. Donations and free trials do not receive discounts.
- **Minimum amount / basis**: either the combined subtotal of eligible products, or each individual product's price. The threshold is inclusive; use `100.01` if the rule must be strictly above 100 CAD. Products outside the selection do not contribute to the minimum.
- **Allowed user**: optional restriction to one signed-in native/Google-linked account. Entering that customer's email as a guest is not enough.
- **Starts at / ends at / active**: optional validity dates and an on/off switch. Django's date widgets indicate the admin timezone.

Examples (documentation only; no live codes are created):

| Goal | Configuration |
| --- | --- |
| 20% off purchases of at least 100 CAD | Percentage, value 20, minimum 100, combined eligible subtotal |
| 15% off individual products priced at least 50 CAD | Percentage, value 15, minimum 50, each individual product price |
| 10 CAD off Mohammed's paid classes | Fixed, value 10, all products off, select Mohammed under Teachers |
| Personal offer | Choose the eligible account in Allowed user |

Customers apply the code in the academy cart/checkout or the existing product payment form. The page shows original subtotal, discount and total. One code is allowed per checkout; codes can be reused while valid. Only the code is retained in the browser between cart and checkout, and its amount is fetched again from the server.

## Calculation and payment safety

- The backend reads prices and eligibility from its database. Browser-submitted amounts never define a discount.
- Checkout revalidates a previewed code before creating a reservation. Disabled, expired or ineligible codes create no new booking hold.
- Discounts apply only to eligible paid lines. Fixed discounts are allocated proportionally with a deterministic largest-remainder calculation; all amounts sum to the exact cent and never go below zero.
- A fixed discount is capped at the eligible subtotal. Fully discounted orders confirm without Stripe or a payment card. A remaining paid balance must be at least 0.50 CAD, Stripe's minimum for this checkout currency.
- Original subtotal, discount code, discount amount and net total are frozen on each order. Each booking retains its original and discounted amount. Editing/deleting a promotion does not reprice an existing checkout; reservations still expire normally.
- Stripe receives the discounted line amounts. Signed webhook validation continues to require the exact net amount and matching currency/mode. No Stripe promotion objects or keys are exposed to customers.
- Personal code eligibility uses authenticated account identity. Coupon previews are throttled. Codes have no public listing endpoint and are not exposed by the unauthenticated payment-status endpoint.
- Creation/editing uses normal Django model permissions and audit history. Read-only order fields and existing booking/payment protections remain unchanged.

The migrations preserve old order subtotals and booking prices, with database defaults compatible with the previous deployment during rollout. Product checkout availability still follows the existing course/payment settings.

## Validation

`catalog.test_discounts` covers percentage/fixed values, scope, minimum basis, date/account restrictions, proportional rounding, full discounts, invalid-code rollback, checkout retries and discounted webhook amounts. The full existing suite continues to exercise booking concurrency, slot ownership, authentication, admin permissions and donation payments.
