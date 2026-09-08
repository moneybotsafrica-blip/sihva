---
id: KB-ADMIN-002
title: Process orders and refunds as an administrator
category: admin-operations
tags: [refund, order management, Stripe, payment, status]
audience: [administrator, support-agent]
visibility: internal
source: [backend/app/Http/Controllers/Api/V1/Admin/OrderController.php, backend/app/Services/OrderService.php, backend/app/Http/Controllers/Api/V1/Admin/RefundController.php, backend/app/Services/RefundService.php]
confidence: high
---

# Process orders and refunds as an administrator

## Order processing

Administrators can search and inspect orders, view available next status transitions, and submit a permitted status change with an optional note. The service enforces the transition rules; it records each change in order status history.

## Refund processing

Refund creation is an internal administrator operation. It targets an existing payment and amount, calls Stripe, persists the provider refund result, and updates payment status. A partial refund changes payment/order payment state to `partially_refunded`; a full refund changes it to `refunded`.

## Support handoff

Before asking an administrator to refund, collect the order number, reason, requested amount/currency, and whether the item is a return, fault, or cancellation. The project does not establish approval rules, return-label procedures, or customer notification wording for refunds; use the approved operational policy.

## Related articles

- KB-ORDER-001
- KB-POLICY-001
