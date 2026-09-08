---
id: KB-CHECKOUT-002
title: Use a coupon at checkout
category: shopping-checkout
tags: [coupon, discount code, promo code, checkout]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Models/Coupon.php, backend/app/Services/CheckoutService.php, backend/database/migrations/2026_08_27_000800_create_coupons_table.php]
confidence: high
---

# Use a coupon at checkout

## How it works

Enter a coupon code during checkout. The system normalizes the code to uppercase, validates it against the product subtotal, then applies either a fixed amount or percentage discount. A discount cannot exceed the subtotal.

## Eligibility rules

A coupon must be active, within its configured start/end period, meet any minimum order amount, and remain below any usage limit. The discount is recorded against the resulting order.

## If a coupon fails

The checkout response states: “This coupon is invalid, expired, or unavailable for this order.” Ask the customer to confirm the code and their cart total. Support should check its active state, date window, minimum amount, and remaining usage internally. Do not expose unpublished coupon configuration.

## Related articles

- KB-CHECKOUT-001
- KB-TROUBLE-002
