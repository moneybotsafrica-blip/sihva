---
id: KB-PRODUCT-001
title: Add products and required options to the cart
category: shopping-checkout
tags: [cart, product option, variant, stock, quantity]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/components/product/ProductDetailPage.jsx, frontend/src/lib/cart.js, backend/app/Services/CheckoutService.php]
confidence: high
---

# Add products and required options to the cart

## How it works

Customers select a product and, where presented, an available product option before adding it to the cart. At checkout, the server is the authority for product status, option availability, price, currency, and stock.

## Important rules

- A product must be active.
- If a product has active options, an option must be selected.
- A selected option must belong to that product and be active.
- Quantities must be from 1 to 25 per checkout line.
- The requested quantity cannot exceed available stock.
- Products using different currencies cannot be placed in one order.

## Common problems

If checkout says an item or option is unavailable, the catalogue information may have changed after it was placed in the cart. Ask the customer to refresh the product page and select an available option or reduce the quantity.

## Related articles

- KB-CHECKOUT-001
- KB-TROUBLE-002
