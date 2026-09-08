---
id: KB-TROUBLE-003
title: Troubleshoot account access and support contact problems
category: troubleshooting
tags: [login failed, password reset, account, contact form, Telegram]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Http/Controllers/Api/V1/AccountController.php, frontend/src/components/account/AccountRecovery.jsx, backend/app/Http/Controllers/Api/V1/ContactController.php]
confidence: high
---

# Troubleshoot account access and support contact problems

## Problem: Login fails

**Possible cause:** Incorrect email/password or an invalid protected credential request.

**How to check:** Confirm email spelling and retry with the current password.

**Resolution:** Use password recovery if needed. The service intentionally provides a generic invalid-credentials message.

**Escalate when:** The customer can reproduce a failure after a confirmed password reset.

## Problem: No password-recovery email arrives

**Possible cause:** The address may not match an account, delivery may be delayed, or mail configuration/delivery may be failing.

**Resolution:** Check spam and confirm the email entered. Do not disclose whether an account exists.

**Escalate when:** A known account consistently does not receive recovery mail.

## Problem: Contact form says Telegram support is unavailable

**Resolution:** Ask the customer to retry shortly. The message was saved before the temporary Telegram-delivery failure.

## Related articles

- KB-ACCOUNT-001
- KB-SUPPORT-001
