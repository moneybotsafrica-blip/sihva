---
id: KB-TROUBLE-002
title: Troubleshoot checkout, stock, coupon, and delivery errors
category: troubleshooting
tags: [checkout failed, stock unavailable, coupon invalid, shipping unavailable, payment]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Services/CheckoutService.php, backend/app/Http/Requests/CheckoutRequest.php, backend/app/Http/Controllers/Api/V1/CheckoutController.php]
confidence: high
---

# Troubleshoot checkout, stock, coupon, and delivery errors

## Problem: An item or option is unavailable

**Possible cause:** The product is inactive, the selected option is inactive/wrong for that product, or stock changed.

**How to check:** Refresh the product page and confirm the selected option and quantity.

**Resolution:** Choose an available option, reduce quantity, or remove the item.

**Escalate when:** The site displays stock that repeatedly conflicts with checkout.

## Problem: Coupon is rejected

**Possible cause:** The coupon is inactive, expired, not started, at its use limit, or the subtotal is below its minimum.

**Resolution:** Confirm code spelling and cart total. Support can ask an administrator to check eligibility.

## Problem: Delivery method is unavailable

**Possible cause:** The method does not support the destination or order currency.

**Resolution:** Check the country code and cart currency; select another displayed method.

## Problem: Card checkout is unavailable

**Possible cause:** Stripe is not configured or temporarily unavailable.

**Resolution:** Ask the customer to try again later; escalate persistent failures with time, error, and cart details.

## Related articles

- KB-CHECKOUT-001
- KB-CHECKOUT-002
