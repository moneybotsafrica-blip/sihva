---
id: KB-ADMIN-001
title: Administrator access and roles
category: admin-operations
tags: [admin, administrator, role, permission, dashboard]
audience: [support-agent, administrator]
visibility: internal
source: [backend/app/Models/User.php, backend/app/Http/Middleware/EnsureAdmin.php, backend/app/Http/Controllers/Api/V1/Admin/AuthController.php, frontend/src/components/admin/AdminApp.jsx]
confidence: high
---

# Administrator access and roles

## Access rule

Administration is available only to an authenticated user with at least one assigned role. The `admin` middleware rejects other users with HTTP 403 and “Administrator access is required.” Admin login also refuses a valid password if the user has no role.

## Administration modules

The admin interface includes catalogue, variants, categories, collections, inventory, orders, customers, registered users, payments, refunds, shipping, homepage content, artisans, stories, journal, coupons, reviews, and settings.

## Permission limitation

The project does not implement per-role capability checks. Any role makes a user an administrator and policy checks grant that user access. Role names and labels are configurable, but their functional permissions are not differentiated. Do not tell users that an “order manager” or another role has restricted permissions unless the implementation changes.

## Related articles

- KB-ADMIN-002
