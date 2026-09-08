---
id: KB-API-002
title: Account and checkout API behavior
category: api
tags: [API, account API, checkout API, authentication, Stripe]
audience: [support-agent, developer]
visibility: internal
source: [backend/routes/api.php, backend/app/Http/Requests/CheckoutRequest.php, backend/app/Http/Controllers/Api/V1/AccountController.php, backend/app/Http/Controllers/Api/V1/CheckoutController.php, backend/app/Http/Controllers/Api/V1/NonceController.php]
confidence: high
---

# Account and checkout API behavior

## Account endpoints

Public account endpoints include registration, login, forgot password, and reset password. Credential requests require a single-use nonce flow; clients first call `GET /api/v1/nonce` with `X-Cf-Requestid`, then submit protected credentials with the required nonce headers. Authenticated account endpoints include profile, password, addresses, orders, order detail, and logout.

## Checkout endpoint

`POST /api/v1/checkout` accepts buyer details, address, items, optional notes/coupon/shipping method. It returns HTTP 201 with order totals and a Stripe checkout URL. It returns HTTP 503 with “Card checkout is temporarily unavailable.” when Stripe is unavailable. `GET /api/v1/checkout/session/{session}` checks a Stripe session that begins with `cs_` and returns order/payment status.

## Security note

Do not include secret keys, encrypted credential payloads, or browser session cookies in support tickets or knowledge articles.

## Related articles

- KB-ACCOUNT-001
- KB-CHECKOUT-001
