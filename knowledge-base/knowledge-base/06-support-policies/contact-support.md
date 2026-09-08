---
id: KB-SUPPORT-001
title: Contact the Sidai support team
category: support-policies
tags: [contact, support, help, order shipping, product question]
audience: [customer, support-agent]
visibility: customer
source: [frontend/src/components/contact/ContactPage.jsx, backend/app/Http/Controllers/Api/V1/ContactController.php]
confidence: high
---

# Contact the Sidai support team

## Steps

Use the contact page and provide first name, last name, email, topic, and a message of 10–5,000 characters. Supported topics are order/shipping, product question, wholesale, press/collaboration, and general.

## Expected result

When Telegram support delivery succeeds, the site confirms that the message was sent to the Telegram support team. It may also send a support email when that feature is enabled.

## Common problem

If the form says the message was saved but Telegram support is temporarily unavailable, the backend returned HTTP 503. Ask the customer to try again shortly. The system stores the message before attempting Telegram delivery, but it does not expose a customer-facing case number.

## Related articles

- KB-TROUBLE-003
