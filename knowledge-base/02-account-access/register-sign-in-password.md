---
id: KB-ACCOUNT-001
title: Register, sign in, and reset an account password
category: account-access
tags: [account, register, sign in, login, forgot password, reset password]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/components/account/AccountPage.jsx, frontend/src/components/account/AccountRecovery.jsx, backend/app/Http/Controllers/Api/V1/AccountController.php, backend/routes/api.php]
confidence: high
---

# Register, sign in, and reset an account password

## Register or sign in

Customers can register from `/register` or sign in from `/login` and the account area. Registration requires a name, unique email address, password, and matching password confirmation. Passwords must be at least 12 characters and include letters, uppercase/lowercase characters, and numbers.

Successful account registration and login create an authenticated browser session. The site uses protected cookie-based sessions; customers should not need to handle an access token themselves.

## Reset a password

1. Open `/account/forgot-password`.
2. Enter the account email address.
3. Use the recovery link, if received, to choose and confirm a new qualifying password.
4. Sign in with the new password.

For privacy, the recovery request always says that a link has been sent if the account exists. It does not confirm whether an email address is registered.

## Common problems

Invalid credentials are deliberately reported with a generic message. Check email spelling and password first. A customer cannot change their email through profile editing; that flow says ownership verification is required and is not available there.

## Related articles

- KB-ACCOUNT-002
- KB-PLAYBOOK-001
