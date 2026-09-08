---
id: KB-REVIEW-001
title: Submit and view product reviews
category: product-content
tags: [review, rating, verified purchase, moderation]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Http/Controllers/Api/V1/ReviewController.php, backend/routes/api.php, frontend/src/components/product/ProductReviews.jsx]
confidence: high
---

# Submit and view product reviews

## How it works

Published reviews are visible on a product page, along with review count and average rating. A signed-in customer can submit a rating from 1 to 5, an optional title of up to 120 characters, and a review body of 10–2,000 characters.

New reviews are created as pending and require moderation before becoming public. A review is marked as a verified purchase only when the customer account has an eligible order containing that product; eligible order statuses are paid, processing, shipped, or delivered.

## Common problems

A newly submitted review not appearing immediately is expected: the system responds that it was submitted for moderation. Support should not promise a publication time because none is defined in the project.

## Related articles

- KB-ADMIN-003
