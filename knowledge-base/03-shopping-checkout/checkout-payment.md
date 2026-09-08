---
id: KB-CHECKOUT-001
title: Complete checkout and pay for an order
category: shopping-checkout
tags: [checkout, payment, Stripe, delivery, coupon, guest checkout]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/components/checkout/CheckoutPage.jsx, backend/app/Http/Requests/CheckoutRequest.php, backend/app/Services/CheckoutService.php, backend/app/Http/Controllers/Api/V1/CheckoutController.php]
confidence: high
---

# Complete checkout and pay for an order

## Steps

1. Add one or more products to the cart.
2. Provide email, first and last name, delivery address, and optionally phone and order notes.
3. Optionally enter a coupon and choose an available shipping method.
4. Continue to Stripe Checkout to pay by card.
5. After payment, the system checks the Stripe session and updates the order payment state.

## Expected result

Checkout creates an order initially marked pending with a pending payment. A successful Stripe payment changes the order and payment status to paid. The server creates an order number and returns the checkout URL.

Customers may check out as guests or while signed in. Stock is reduced when the order is created, before payment confirmation.

## Requirements and limits

The order needs at least one item, supports at most 50 lines, and requires a delivery address including country code. Card checkout is unavailable if Stripe is not configured.

## Related articles

- KB-PRODUCT-001
- KB-DELIVERY-001
- KB-TROUBLE-002
