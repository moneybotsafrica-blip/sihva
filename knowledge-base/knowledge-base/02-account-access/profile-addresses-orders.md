---
id: KB-ACCOUNT-002
title: Manage profile, addresses, and order history
category: account-access
tags: [profile, address, default address, order history, account]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Http/Controllers/Api/V1/AccountController.php, backend/routes/api.php, frontend/src/components/account/CustomerDashboard.jsx]
confidence: high
---

# Manage profile, addresses, and order history

## Overview

Signed-in customers can view their account details, addresses, and orders. They can update their display name and phone number, add, edit, or delete addresses, change password, and sign out.

## Important restrictions

- Profile email changes are not available in the profile update flow.
- Address operations require an authenticated account and apply to the account owner.
- An order-detail request verifies that the requested order belongs to the signed-in customer account.

## Support guidance

If a customer cannot see an order, first ask whether they placed it while signed in. The implementation also permits guest checkout, so guest purchases may not appear in a registered account’s history. Whether and how support should merge guest and registered purchase history needs product-owner confirmation.

## Related articles

- KB-ACCOUNT-001
- KB-CHECKOUT-001
