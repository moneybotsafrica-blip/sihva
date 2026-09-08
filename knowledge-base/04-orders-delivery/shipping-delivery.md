---
id: KB-DELIVERY-001
title: Delivery availability, timing, and duties
category: orders-delivery
tags: [shipping, delivery, tracking, duties, international]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/components/info/InfoPage.jsx, backend/app/Models/ShippingMethod.php, backend/app/Http/Controllers/Api/V1/ShippingMethodController.php, backend/app/Services/CheckoutService.php]
confidence: medium
---

# Delivery availability, timing, and duties

## Customer guidance

The storefront says Sidai Artistry ships internationally from East Africa. In-stock pieces are normally prepared within 2–4 business days; handcrafted or custom work may take longer and should be confirmed before dispatch. Tracking details are shared after dispatch. The recipient is responsible for applicable international duties and local taxes.

## How delivery selection works

At checkout, the system lists active shipping methods that support the delivery country and order currency. Each method can have a price, free-shipping subtotal threshold, and estimated delivery-day range. The selected delivery cost is added after discounts.

## Needs confirmation

The public policy says delivery cost and timing are confirmed during order processing, while the checkout implementation calculates a shipping method and estimate before payment. Support should use the live checkout result as operational guidance and request product-owner clarification on the canonical customer promise.

## Related articles

- KB-CHECKOUT-001
- KB-POLICY-001
