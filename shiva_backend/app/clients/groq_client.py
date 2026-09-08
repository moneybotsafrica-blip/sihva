from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class ChatMessage:
    """Chat message for LLM interactions."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    confidence: float
    metadata: Optional[Dict[str, Any]] = None


class GroqClientInterface(ABC):
    """Abstract interface for Groq LLM client."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate chat completion using Groq LLM."""
        pass


class GroqClient(GroqClientInterface):
    """Real implementation of Groq client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        )

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate chat completion using Groq API."""
        model = model or self.model

        try:
            payload = {
                "model": model,
                "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
                "temperature": temperature,
            }

            if max_tokens:
                payload["max_tokens"] = max_tokens

            response = await self.client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]

            # Extract confidence - Groq doesn't provide this directly, so we estimate based on response quality
            # For now, use a reasonable default confidence
            confidence = 0.8

            # Adjust confidence based on response characteristics
            if content and len(content) > 50:
                confidence = min(0.9, confidence + 0.1)  # Longer responses tend to be more confident
            if content and "i don't know" in content.lower() or "not sure" in content.lower():
                confidence = max(0.3, confidence - 0.3)  # Uncertain responses have lower confidence

            return LLMResponse(
                content=content,
                confidence=confidence,
                metadata={"model": model, "usage": data.get("usage")},
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq API request failed",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Error calling Groq API",
                error=str(e),
            )
            raise

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class MockGroqClient(GroqClientInterface):
    """Mock implementation for testing with knowledge base awareness."""

    def __init__(self):
        self.responses: Dict[str, LLMResponse] = {}

    async def analyze_user_problem(self, user_input: str) -> Dict[str, Any]:
        """Mock implementation of problem analysis."""
        # Simple rule-based analysis for testing
        user_input_lower = user_input.lower()
        
        if any(tech in user_input_lower for tech in ["error", "crash", "bug", "500", "404"]):
            return {
                "problem_type": "technical_issue",
                "urgency": 4,
                "summary": "Technical issue detected in user input",
                "solution_approach": "Route to Code AI for analysis",
                "confidence": 0.85
            }
        elif any(support in user_input_lower for support in ["password", "billing", "account", "delivery"]):
            return {
                "problem_type": "support_query",
                "urgency": 2,
                "summary": "General support query",
                "solution_approach": "Route to Support AI with knowledge base",
                "confidence": 0.90
            }
        else:
            return {
                "problem_type": "general",
                "urgency": 3,
                "summary": "General inquiry",
                "solution_approach": "Handle with default support flow",
                "confidence": 0.70
            }

    def set_mock_response(self, key: str, response: LLMResponse):
        """Set a mock response for testing."""
        self.responses[key] = response

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Return mock response based on input and knowledge base context."""
        # Extract system prompt for knowledge base context
        system_message = next((msg for msg in messages if msg.role == "system"), None)
        kb_context = ""
        if system_message:
            # Extract knowledge base content from system prompt
            if "KNOWLEDGE BASE CONTEXT:" in system_message.content:
                kb_section = system_message.content.split("KNOWLEDGE BASE CONTEXT:")[1]
                if "-------------------" in kb_section:
                    kb_content = kb_section.split("-------------------")[0]
                    kb_context = kb_content.strip()

        # Get the latest user message
        user_messages = [msg for msg in messages if msg.role == "user"]
        if not user_messages:
            return LLMResponse(
                content="I couldn't understand your request.",
                confidence=0.3,
            )
        
        user_message = user_messages[-1].content.lower()

        # Check for predefined mock responses first
        for key, response in self.responses.items():
            if key.lower() in user_message:
                return response

        # Generate response based on knowledge base context
        if kb_context:
            # For testing purposes, provide enhanced step-by-step responses for diverse categories
            if "password" in user_message:
                enhanced_response = "To reset your password, follow these steps: Step 1: Go to Settings by clicking the gear icon. Step 2: Select Security from the menu. Step 3: Click on 'Change Password'. Step 4: Enter your current password. Step 5: Enter your new password. Step 6: Click 'Confirm'. Step 7: Check your email for verification link. Step 8: Click the link within 24 hours. You should see a confirmation message: 'Password successfully reset'."
                return LLMResponse(content=enhanced_response, confidence=0.95)
            elif "billing" in user_message or "payment" in user_message or "pay" in user_message or "charge" in user_message or "invoice" in user_message:
                enhanced_response = "To resolve payment issues, follow these steps: Step 1: Check your payment method details in Settings > Billing. Step 2: Verify your card has sufficient funds and isn't expired. Step 3: Ensure billing address matches your card statement. Step 4: Try a different payment method (credit card, PayPal). Step 5: Clear browser cache and try incognito mode. Step 6: Disable VPN or proxy temporarily. Step 7: Check if the payment gateway is experiencing issues. Step 8: Contact your bank to authorize the transaction. If issues persist, the payment will be processed within 24-48 hours. You should see a confirmation email and receipt once successful."
                return LLMResponse(content=enhanced_response, confidence=0.92)
            elif "account" in user_message or "access" in user_message:
                enhanced_response = "If you can't access your account: Step 1: Try the password reset option first. Step 2: Check your email for password reset link (check spam folder). Step 3: If link doesn't work, request a new reset link. Step 4: Clear browser cache and cookies. Step 5: Try a different browser or incognito mode. Step 6: If still blocked, contact support with your account details and email address."
                return LLMResponse(content=enhanced_response, confidence=0.88)
            elif "error" in user_message or "500" in user_message or "404" in user_message:
                enhanced_response = "For 500 Internal Server Error: Step 1: Refresh the page (F5 or Ctrl+R). Step 2: Check your internet connection. Step 3: Clear browser cache and cookies. Step 4: Try a different browser. Step 5: Check if other users are experiencing the same issue. Step 6: If error persists, note the exact time, page URL, and error message. Step 7: Contact support with these details for faster resolution."
                return LLMResponse(content=enhanced_response, confidence=0.85)
            elif "feature" in user_message or "report" in user_message or "export" in user_message:
                enhanced_response = "To use reporting features: Step 1: Navigate to Reports section in main menu. Step 2: Select report type from dropdown. Step 3: Set date range and filters. Step 4: Click 'Generate Report' button. Step 5: Wait for processing (usually 10-30 seconds). Step 6: Review report in preview pane. Step 7: Click 'Export' to download (PDF, CSV, Excel options). Step 8: Save report to desired location."
                return LLMResponse(content=enhanced_response, confidence=0.90)
            elif "subscription" in user_message or "plan" in user_message or "upgrade" in user_message:
                enhanced_response = "To manage subscription: Step 1: Go to Settings > Subscription. Step 2: View current plan details and billing cycle. Step 3: To upgrade, click 'Change Plan' and select new tier. Step 4: To cancel, click 'Cancel Subscription' and confirm. Step 5: For refunds, contact support within 30 days. Step 6: Plan changes take effect immediately for upgrades, next cycle for downgrades."
                return LLMResponse(content=enhanced_response, confidence=0.87)
            elif "data" in user_message or "export" in user_message or "import" in user_message:
                enhanced_response = "To export your data: Step 1: Navigate to Settings > Data Management. Step 2: Click 'Export Data' button. Step 3: Select data types to export (messages, files, settings). Step 4: Choose export format (CSV, JSON, PDF). Step 5: Click 'Start Export'. Step 6: Wait for completion notification. Step 7: Download exported file from notification. Step 8: Verify data integrity."
                return LLMResponse(content=enhanced_response, confidence=0.86)
            elif "security" in user_message or "2fa" in user_message or "auth" in user_message:
                enhanced_response = "To enhance account security: Step 1: Go to Settings > Security. Step 2: Enable two-factor authentication (2FA). Step 3: Choose 2FA method (SMS, authenticator app, hardware key). Step 4: Verify 2FA setup with backup codes. Step 5: Set strong password (12+ characters, mixed types). Step 6: Enable login notifications. Step 7: Review connected devices and remove unknown ones."
                return LLMResponse(content=enhanced_response, confidence=0.91)
            elif "api" in user_message or "integration" in user_message or "webhook" in user_message:
                enhanced_response = "To integrate with API: Step 1: Go to Settings > API Keys. Step 2: Click 'Generate New API Key'. Step 3: Set key permissions and scope. Step 4: Copy API key (store securely, not shown again). Step 5: Review API documentation in Developer Portal. Step 6: Test API endpoints using provided sandbox. Step 7: Implement webhook handlers for events. Step 8: Set up rate limiting alerts."
                return LLMResponse(content=enhanced_response, confidence=0.84)
            else:
                response = self._generate_kb_response(user_message, kb_context)
                return response

        # Fallback responses based on common queries - enhanced to prevent user frustration
        # Check for greetings first
        if any(greeting in user_message for greeting in ["hi", "hello", "hey"]):
            return LLMResponse(
                content="I am here to help with any Shiva-related questions or issues you might have—feel free to ask about your account, service, payments, or anything else Shivasoftwares! What can I assist with today?",
                confidence=0.95,
            )
        elif "password" in user_message:
            return LLMResponse(
                content="I can help you reset your password. Here's what to do: Step 1: Go to Settings by clicking the gear icon. Step 2: Select Security from the menu. Step 3: Click 'Change Password'. Step 4: Enter your current password. Step 5: Create a new password (8+ characters with letters and numbers). Step 6: Click 'Confirm'. Step 7: Check your email for a verification link and click it within 24 hours. You should see 'Password successfully reset' when done. If you don't receive the email, check your spam folder or request a new link.",
                confidence=0.92,
            )
        elif "billing" in user_message or "payment" in user_message or "pay" in user_message:
            return LLMResponse(
                content="I understand payment issues can be frustrating. Let me help you resolve this: Step 1: Go to Settings > Billing to check your payment method. Step 2: Verify your card has funds and isn't expired. Step 3: Ensure your billing address matches your card statement. Step 4: Try a different payment method (credit card, PayPal). Step 5: Clear your browser cache and try incognito mode. Step 6: Disable VPN temporarily as it can block payments. Step 7: Contact your bank to authorize the transaction if needed. Most payment issues resolve within 24-48 hours. You'll receive a confirmation email when successful. If you're still having trouble after trying these steps, I can help you contact support with specific details.",
                confidence=0.88,
            )
        elif "delivery" in user_message or "shipping" in user_message:
            return LLMResponse(
                content="I can help you with delivery information. Standard delivery takes 3-5 business days. Express delivery is available for 1-2 business days. International orders may have customs delays. To track your order: Step 1: Go to Orders > Select Your Order. Step 2: Click 'Track Package'. Step 3: Enter your tracking number if needed. Step 4: You'll see the current location and estimated delivery date. If your order is delayed beyond the estimated date, contact support with your order number for investigation.",
                confidence=0.85,
            )
        elif "account" in user_message or "login" in user_message:
            structured_response = """**Solution – Resolve Login Problems on Shiva AI Platform**

1. **Confirm Username & Password**
   - Verify you are entering the exact email address used for registration (case‑insensitive) and the correct password.
   - Watch for accidental leading/trailing spaces; type the credentials manually instead of copy‑pasting.

2. **Reset Your Password**
   - On the login page click **"Forgot password?"**.
   - Enter your registered email address and press **"Send Reset Link"**.
   - Check your inbox (and spam folder) for the reset email, click the link, and set a new password that meets the platform's complexity rules (minimum 8 characters, includes a letter, number, and special character).
   - Return to the login page and sign in with the new password.

3. **Verify Account Status**
   - If you never received the reset email, your account may be unverified or disabled.
   - Locate the original **"Welcome – Verify Your Email"** message sent after registration. Click the verification link inside.
   - If the account was disabled (e.g., due to multiple failed attempts), you'll see a banner on the login screen. Click **"Contact Support"** from that banner to request re‑activation.

4. **Clear Browser Cache & Cookies**
   - Open your browser settings → **Privacy & Security** → **Clear browsing data**.
   - Select **Cookies and other site data** and **Cached images and files** for the time range "All time".
   - Reload the Shiva AI login page and try again.

5. **Try a Different Browser or Incognito/Private Mode**
   - Open Chrome/Edge/Firefox in **Incognito/Private** mode and navigate to the login URL.
   - This bypasses extensions or stored cookies that might interfere.

6. **Check Two‑Factor Authentication (2FA)**
   - If you have 2FA enabled, after entering your password you'll be prompted for a code.
   - Open your authenticator app (Google Authenticator, Authy, etc.) and enter the 6‑digit code.
   - If you cannot access the authenticator, click **"Lost access to 2FA?"** on the 2FA screen and follow the recovery steps (email verification or backup codes).

7. **Network Restrictions**
   - Ensure you are not behind a corporate firewall or VPN that blocks Shiva AI domains.
   - Temporarily disable VPN or switch to a different network (e.g., mobile hotspot) and attempt login again.

8. **Account Lockout After Repeated Failures**
   - After 5 consecutive failed attempts the account locks for 15 minutes.
   - Wait the lockout period, then retry with the correct credentials or use the password‑reset link.

9. **Verify Browser Compatibility**
   - Shiva AI supports the latest versions of Chrome, Edge, and Firefox.
   - Update your browser to the newest version if it is outdated.

10. **Confirm URL**
    - Make sure you are accessing the official login page: `https://app.shivaai.com/login` 
    - Avoid bookmarked or third‑party links that may redirect to old or phishing pages.

**How to Verify Success**
- After completing the steps, you should land on the **Dashboard** showing your projects and the top navigation bar.
- The URL will change to `https://app.shivaai.com/dashboard`.
- No error messages should appear; if a welcome banner shows "You are logged in as Alice Johnson", the issue is resolved.

**If the Issue Persists – Alternatives**
- **Use a Different Device** (mobile phone, tablet, another computer) to rule out device‑specific problems.
- **Check Email for Account Notices** – any suspension or verification notices will be sent to your registered email.
- **Run a Browser Extension Test** – disable all extensions, especially ad‑blockers or security plugins, then retry.

**Next Steps if Still Unresolved**
- Gather the following information before contacting support:
  1. Email address used for the account.
  2. Exact error message displayed (screenshot if possible).
  3. Browser name and version.
  4. Whether 2FA is enabled.
  5. Any recent changes to your account (password change, new device, etc.).

- Reach out to Shiva AI Support via **support@shivaai.com** or the in‑app **Help → Contact Support** form, attaching the details above. This will allow the support team to diagnose the problem quickly."""
            
            return LLMResponse(
                content=structured_response,
                confidence=0.87,
            )
        elif "checkout" in user_message or "cart" in user_message:
            return LLMResponse(
                content="I can help you complete your purchase. Here's how: Step 1: Add items to your cart by clicking 'Add to Cart'. Step 2: Review your cart and click 'Checkout'. Step 3: Enter your shipping information. Step 4: Select your payment method (credit card, PayPal, etc.). Step 5: Enter payment details and billing address. Step 6: Review your order and click 'Place Order'. Step 7: You should see a confirmation page and receive an email receipt. If payment fails, try a different payment method or contact your bank. If you encounter any errors during checkout, note the error message and try refreshing the page.",
                confidence=0.89,
            )
        else:
            # For unknown issues, return a response that indicates need for staff assistance
            return LLMResponse(
                content="I don't have specific information about this issue in my knowledge base. This appears to be a complex or unique situation that would benefit from personalized assistance. I recommend contacting our support team directly with details about what you're experiencing, including any error messages or screenshots if available. They'll be able to provide more targeted help for your specific situation.",
                confidence=0.3,
            )

    def _generate_kb_response(self, user_message: str, kb_context: str) -> LLMResponse:
        """Generate a response based on knowledge base context."""
        # Extract relevant information from KB context
        user_message_lower = user_message.lower()
        
        # Look for relevant content in the knowledge base
        if "password" in user_message_lower and "password" in kb_context.lower():
            # Extract password-related instructions
            lines = kb_context.split('\n')
            for line in lines:
                if "password" in line.lower() and ("reset" in line.lower() or "change" in line.lower()):
                    return LLMResponse(
                        content=f"{line.strip()}",
                        confidence=0.90,
                    )
        
        if "payment" in user_message_lower or "checkout" in user_message_lower:
            if "payment" in kb_context.lower() or "checkout" in kb_context.lower():
                lines = kb_context.split('\n')
                relevant_lines = [line for line in lines if any(word in line.lower() for word in ["payment", "checkout", "credit card", "paypal"])]
                if relevant_lines:
                    return LLMResponse(
                        content=f"{' '.join(relevant_lines[:2])}",
                        confidence=0.88,
                    )
        
        if "delivery" in user_message_lower or "shipping" in user_message_lower:
            if "delivery" in kb_context.lower() or "shipping" in kb_context.lower():
                lines = kb_context.split('\n')
                relevant_lines = [line for line in lines if any(word in line.lower() for word in ["delivery", "shipping", "business days"])]
                if relevant_lines:
                    return LLMResponse(
                        content=f"{' '.join(relevant_lines[:2])}",
                        confidence=0.85,
                    )
        
        # General response if no specific match found but KB context exists
        return LLMResponse(
            content=f"Based on our knowledge base, here's the relevant information: {kb_context[:200]}...",
            confidence=0.75,
        )
