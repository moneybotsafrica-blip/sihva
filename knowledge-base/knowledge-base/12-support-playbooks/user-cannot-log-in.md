---
id: KB-PLAYBOOK-001
title: Support playbook for a customer who cannot log in
category: support-playbooks
tags: [playbook, login, password reset, account access]
audience: [support-agent]
visibility: internal
source: [backend/app/Http/Controllers/Api/V1/AccountController.php, frontend/src/components/account/AccountRecovery.jsx, backend/routes/api.php]
confidence: high
---

# Support playbook for a customer who cannot log in

## Questions Shiva AI should ask

1. What exact message appears after you submit sign-in?
2. Are you using the email address originally used to register?
3. Have you tried the password-recovery flow and checked spam/junk mail?

## Checks

- Do not ask for or accept the customer password.
- Confirm that the customer understands the generic invalid-credentials message does not reveal whether an account exists.
- Confirm the password-reset form requires a token from the recovery link and a new qualifying password.

## Possible resolutions

Guide the customer to `/account/forgot-password`, then sign in after a successful reset. If profile email change is the issue, explain that the self-service profile flow does not support it.

## Escalate when

Escalate a repeat failure after a known successful reset, or persistent failure to receive recovery email for a known account. Include timestamps, affected email only through approved support channels, browser/error information, and never a password or session cookie.

## Related articles

- KB-ACCOUNT-001
- KB-TROUBLE-003
