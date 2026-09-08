---
id: KB-GETTING-001
title: Browse, search, and find products
category: getting-started
tags: [browse, catalogue, catalog, search, collection, product]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/App.jsx, backend/app/Http/Controllers/Api/V1/ProductController.php, backend/routes/api.php]
confidence: high
---

# Browse, search, and find products

## How it works

The storefront shows only products whose status is active. Customers can open the product catalogue, browse a collection, or use product search. Search matches a product name, description, or SKU. Product-list results are paginated; each request can return 1–48 items, with 12 as the default.

## Steps

1. Open `Products`, `Shop`, or a collection page.
2. Use search to enter a product name, description term, or SKU.
3. Open a product to see its details, images, and active options.

## Common problems

**A product is not visible.** It may be inactive or archived, which is intentionally excluded from public catalogue results. Support should confirm the product status with an administrator; do not promise availability from an old link or screenshot.

## Related articles

- KB-CHECKOUT-001
- KB-PRODUCT-001
