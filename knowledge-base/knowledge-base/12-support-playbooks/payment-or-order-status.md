---
id: KB-PLAYBOOK-002
title: Support playbook for payment or order-status questions
category: support-playbooks
tags: [playbook, payment, order status, Stripe, confirmation]
audience: [support-agent]
visibility: internal
source: [backend/app/Http/Controllers/Api/V1/CheckoutController.php, backend/app/Http/Controllers/Api/V1/StripeWebhookController.php, backend/app/Services/OrderService.php]
confidence: high
---

# Support playbook for payment or order-status questions

## Questions Shiva AI should ask

1. What is the order number?
2. Did Stripe show a successful payment confirmation?
3. Is the question about payment, dispatch, delivery, cancellation, or refund?

## Checks

- Confirm the payment and order status through approved internal tools.
- A paid Stripe session should result in payment status `paid` and order status `paid`.
- Check order status history and available transitions before requesting a manual update.

## Possible resolutions

For a completed card payment whose order remains pending, escalate for payment/session investigation. For fulfilment questions, give only the current approved order status and delivery information. For refunds or cancellation, gather order and reason, then follow the internal refund process.

## Escalate when

Payment is disputed, the Stripe/session status conflicts with the stored order, a customer reports duplicate payment, or a refund is requested.

## Related articles

- KB-CHECKOUT-001
- KB-ORDER-001
- KB-ADMIN-002
