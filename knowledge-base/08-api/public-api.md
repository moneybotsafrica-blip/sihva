---
id: KB-API-001
title: Public catalogue, shipping, and contact API
category: api
tags: [API, products endpoint, shipping endpoint, contact endpoint]
audience: [support-agent, developer]
visibility: internal
source: [backend/routes/api.php, backend/app/Http/Controllers/Api/V1/ProductController.php, backend/app/Http/Controllers/Api/V1/ShippingMethodController.php, backend/app/Http/Controllers/Api/V1/ContactController.php]
confidence: high
---

# Public catalogue, shipping, and contact API

## Product catalogue

`GET /api/v1/products` returns active products. Optional query parameters are `q` (name, description, or SKU search), `category` (category slug), `bestseller` (boolean), and `per_page` (1–48; default 12). `GET /api/v1/products/{slug}` returns an active product; inactive products return 404.

## Shipping methods

`GET /api/v1/shipping-methods` accepts optional `country`, `currency`, and `subtotal`. It returns active compatible methods with amount and estimated delivery range. Defaults are `KE` and `USD` when query values are omitted.

## Contact

`POST /api/v1/contact` accepts customer identity, a defined topic, and 10–5,000-character message. It is rate limited to five requests per 10 minutes. A successful request returns 201; temporary Telegram delivery failure returns 503 after saving the message.

## Related articles

- KB-GETTING-001
- KB-SUPPORT-001
