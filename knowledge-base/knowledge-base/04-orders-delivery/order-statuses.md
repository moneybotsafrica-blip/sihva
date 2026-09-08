---
id: KB-ORDER-001
title: Understand order and payment statuses
category: orders-delivery
tags: [order status, payment status, pending, paid, shipped, delivered, cancelled]
audience: [support-agent, administrator]
visibility: internal
source: [backend/app/Services/OrderService.php, backend/app/Services/CheckoutService.php, backend/app/Http/Controllers/Api/V1/CheckoutController.php]
confidence: high
---

# Understand order and payment statuses

## Order lifecycle

Storefront checkout creates an order as `pending` and payment as `pending`. Confirmed payment changes both to `paid`. Administrators can move an order only through these transitions:

- `pending` → `paid` or `cancelled`
- `paid` → `processing` or `cancelled`
- `processing` → `shipped` or `cancelled`
- `shipped` → `delivered`

`delivered`, `cancelled`, and `refunded` have no outgoing transitions in the order service. Every permitted manual transition is written to order status history with the administrator and optional note.

## Important implementation observation

The transition request accepts `refunded`, but the transition map has no path into it. Refund processing instead updates payment/order payment status through the refund workflow. Confirm the intended customer-visible meaning of an order’s `refunded` status before publishing customer guidance.

## Related articles

- KB-CHECKOUT-001
- KB-ADMIN-002
