# Sidai Artistry Knowledge Base

Generated: 2026-09-07  
Project: Sidai Artistry  
Description: Search-oriented customer support and internal operations knowledge extracted from the repository source code and public storefront content.

## Categories and articles

| ID | Title | Category | Visibility | Confidence | Primary source |
|---|---|---|---|---|---|
| KB-OVERVIEW-001 | Sidai Artistry product overview | overview | customer | high | `README.md` |
| KB-GETTING-001 | Browse, search, and find products | getting-started | customer | high | `ProductController.php` |
| KB-ACCOUNT-001 | Register, sign in, and reset an account password | account-access | customer | high | `AccountController.php` |
| KB-ACCOUNT-002 | Manage profile, addresses, and order history | account-access | customer | high | `AccountController.php` |
| KB-PRODUCT-001 | Add products and required options to the cart | shopping-checkout | customer | high | `CheckoutService.php` |
| KB-CHECKOUT-001 | Complete checkout and pay for an order | shopping-checkout | customer | high | `CheckoutController.php` |
| KB-CHECKOUT-002 | Use a coupon at checkout | shopping-checkout | customer | high | `Coupon.php` |
| KB-DELIVERY-001 | Delivery availability, timing, and duties | orders-delivery | customer | medium | `InfoPage.jsx` |
| KB-ORDER-001 | Understand order and payment statuses | orders-delivery | internal | high | `OrderService.php` |
| KB-REVIEW-001 | Submit and view product reviews | product-content | customer | high | `ReviewController.php` |
| KB-POLICY-001 | Returns, privacy, and order terms | support-policies | customer | medium | `InfoPage.jsx` |
| KB-SUPPORT-001 | Contact the Sidai support team | support-policies | customer | high | `ContactController.php` |
| KB-ADMIN-001 | Administrator access and roles | admin-operations | internal | high | `EnsureAdmin.php` |
| KB-ADMIN-002 | Process orders and refunds as an administrator | admin-operations | internal | high | `RefundService.php` |
| KB-ADMIN-003 | Moderate customer reviews | admin-operations | internal | medium | `Admin/ReviewController.php` |
| KB-API-001 | Public catalogue, shipping, and contact API | api | internal | high | `routes/api.php` |
| KB-API-002 | Account and checkout API behavior | api | internal | high | `routes/api.php` |
| KB-TROUBLE-002 | Troubleshoot checkout, stock, coupon, and delivery errors | troubleshooting | customer | high | `CheckoutService.php` |
| KB-TROUBLE-003 | Troubleshoot account access and support contact problems | troubleshooting | customer | high | `AccountController.php` |
| KB-FAQ-001 | Customer frequently asked questions | faq | customer | high | `InfoPage.jsx` |
| KB-GLOSSARY-001 | Sidai Artistry glossary | glossary | customer | high | `Order.php` |
| KB-PLAYBOOK-001 | Support playbook for a customer who cannot log in | support-playbooks | internal | high | `AccountController.php` |
| KB-PLAYBOOK-002 | Support playbook for payment or order-status questions | support-playbooks | internal | high | `CheckoutController.php` |

## Ingestion notes

- Preserve each article’s front matter, especially `id`, `visibility`, `source`, and `confidence`.
- Filter `visibility: internal` from customer-facing retrieval unless the support workspace authorizes internal material.
- Treat medium-confidence articles as grounded but requiring policy-owner confirmation where noted.
