---
id: KB-GLOSSARY-001
title: Sidai Artistry glossary
category: glossary
tags: [glossary, order, variant, coupon, payment, review]
audience: [customer, support-agent, administrator]
visibility: customer
source: [backend/app/Models/Order.php, backend/app/Models/ProductVariant.php, backend/app/Models/Coupon.php, backend/app/Models/ShippingMethod.php, backend/app/Http/Controllers/Api/V1/ReviewController.php]
confidence: high
---

# Sidai Artistry glossary

## Active product

A product available through the public catalogue and eligible for checkout.

## Product option / variant

A selectable version of a product. It can have its own SKU, price, stock, and attributes.

## Coupon

A discount configuration that can have a fixed or percentage value, dates, minimum subtotal, active state, and usage limit.

## Order status

The fulfilment state of an order, such as pending, paid, processing, shipped, or delivered.

## Payment status

The payment state, updated through Stripe payment and refund handling.

## Verified purchase review

A review whose author has an eligible order containing the reviewed product.

## Related articles

- KB-ORDER-001
- KB-PRODUCT-001
