---
id: KB-ADMIN-003
title: Moderate customer reviews
category: admin-operations
tags: [review moderation, publish review, delete review]
audience: [administrator, support-agent]
visibility: internal
source: [backend/app/Http/Controllers/Api/V1/Admin/ReviewController.php, backend/app/Http/Controllers/Api/V1/ReviewController.php, backend/routes/api.php]
confidence: medium
---

# Moderate customer reviews

## How it works

Customers submit reviews as pending. Administrators can list reviews, update a review, or delete a review through internal admin routes. Public product pages show only reviews whose status is published.

## Support guidance

When a customer asks why a review is absent, explain that reviews are moderated before publication. Escalate alleged abusive content, personal information, or a disputed verified-purchase label to an administrator.

## Needs confirmation

The exact editable review fields and moderation-status values should be confirmed from the admin request/UI behavior before documenting a step-by-step moderator procedure.

## Related articles

- KB-REVIEW-001
