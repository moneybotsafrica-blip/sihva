---
id: KB-TROUBLE-003
title: Troubleshoot payment issues and errors
category: troubleshooting
tags: [payment failed, card declined, payment error, stripe, checkout]
audience: [customer, support-agent]
visibility: customer
source: [backend/app/Services/CheckoutService.php, backend/app/Http/Controllers/Api/V1/CheckoutController.php]
confidence: high
---

# Troubleshoot payment issues and errors

## Problem: Payment failed or card declined

**Solution: Step-by-step troubleshooting**

**Step 1: Check your payment method details**
- Go to Settings > Billing in your account
- Verify your card number, expiration date, and CVV are correct
- Ensure the card is still active and not expired

**Step 2: Verify sufficient funds**
- Check your bank account or credit card balance
- Ensure you have sufficient funds for the purchase
- Some banks place holds on pending transactions

**Step 3: Match billing address exactly**
- Ensure your billing address matches your card statement exactly
- Check for correct street address, city, state, and ZIP code
- Even small differences can cause card declines

**Step 4: Try a different payment method**
- Use a different credit or debit card
- Try PayPal if available as an option
- Consider using bank transfer if offered

**Step 5: Clear browser cache and try incognito mode**
- Clear your browser cache and cookies
- Try the checkout in incognito/private browsing mode
- This resolves many browser-related payment issues

**Step 6: Disable VPN or proxy temporarily**
- VPNs and proxies can sometimes block payment gateways
- Disable any VPN or proxy connections
- Try the payment again with your direct internet connection

**Step 7: Check with your bank**
- Some banks block online transactions for security
- Contact your bank to authorize the transaction
- Ask if there are any holds or restrictions on your card

**Step 8: Verify payment gateway status**
- If other payment methods work, the issue may be temporary
- Try again in a few minutes
- Payment gateways occasionally experience brief outages

**Step 9: Check subscription renewal dates**
- For subscription payments, verify the renewal date has passed
- Check if your subscription is still active
- Ensure your account isn't past due or suspended

**Step 10: Verify account status**
- Check that your account is in good standing
- Ensure no outstanding balances or payment issues
- Contact support if your account appears suspended

**Expected result:** After following these steps, your payment should process successfully. You will receive a confirmation email and receipt once the payment is completed.

**What to expect:** Most payment issues are resolved within the first 3-4 steps. If issues persist after trying all steps, the payment will typically process within 24-48 hours as banks release holds.

**Alternative solutions:**
- If you continue to experience issues, try a different browser or device
- Consider splitting the payment into smaller amounts if possible
- Contact customer support with specific error messages for further assistance

**When to escalate:**
- Multiple payment methods fail consistently
- You receive specific error messages not covered here
- Your account shows a successful payment but order remains pending
- You suspect duplicate charges or unauthorized transactions

## Problem: Payment succeeded but order shows pending

**Solution: Verify payment status and wait for processing**

**Step 1: Check your email for payment confirmation**
- Look for Stripe payment confirmation email
- Verify the payment amount matches your order
- Check that the payment shows as successful

**Step 2: Allow processing time**
- Orders typically process within 5-15 minutes after payment
- During high traffic periods, processing may take up to 1 hour
- Your order status will update automatically

**Step 3: Check your order status**
- Go to Orders in your account
- Look for the recent order
- If still pending after 1 hour, contact support with your order number

**Expected result:** Your order status should update from pending to paid within the processing time.

## Related articles

- KB-CHECKOUT-001: Complete checkout and pay for an order
- KB-TROUBLE-002: Troubleshoot checkout, stock, coupon, and delivery errors
- KB-PLAYBOOK-002: Support playbook for payment or order-status questions