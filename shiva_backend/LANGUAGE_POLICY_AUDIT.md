# Language Policy Audit

## Overview
This document audits all `role="system"` occurrences in the codebase to ensure the English/Kiswahili-only language policy is properly applied to customer and staff-facing AI prompts.

## Shared Language Policy
**Location:** `app/common/prompts.py`

```python
LANGUAGE_POLICY = """
LANGUAGE POLICY:
- Always respond only in English or Kiswahili (Kiswahili sanifu or natural Sheng-inflected Kiswahili are both fine).
- Match the language the customer is using if it's English or Kiswahili; if it's mixed, mirror the mix.
- If the customer writes in any other language, reply in English and politely let them know you currently support English and Kiswahili only.
- Never respond in a third language, and never mix in words from a third language.
"""
```

## Audit Results

### ✅ Customer-Facing Prompts (INCLUDE LANGUAGE_POLICY)

#### 1. `app/support_ai/agents.py` - SupportAgent.get_system_prompt()
- **Line 131**: `ChatMessage(role="system", content=system_prompt)`
- **Usage**: Base prompt for all specialized support agents (Technical, Billing, etc.)
- **Status**: ✅ INCLUDES LANGUAGE_POLICY (appended at line 74)
- **Post-generation enforcement**: ✅ Applied in agents.py handle methods via service.py wrappers

#### 2. `app/support_ai/service.py` - Inline Customer Prompts
All 8 inline prompts include LANGUAGE_POLICY:

- **Line 150**: Gibberish handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 193**: Greeting handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 246**: Ticket explainer - ✅ INCLUDES LANGUAGE_POLICY
- **Line 346**: No-description handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 414**: Vague-technical handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 473**: Out-of-scope handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 584**: Speak-to-staff handler - ✅ INCLUDES LANGUAGE_POLICY
- **Line 668**: Speak-to-staff variant - ✅ INCLUDES LANGUAGE_POLICY

**Post-generation enforcement**: ✅ All have `enforce_language_policy()` applied after Groq response

#### 3. `app/main.py` - conversation_ai_chat()
- **Line 2355**: `ChatMessage(role="system", content=...)`
- **Usage**: Standalone AI chat endpoint for conversations
- **Status**: ✅ INCLUDES LANGUAGE_POLICY (imported and appended)
- **Post-generation enforcement**: ✅ Applied after Groq response

### ✅ Staff-Facing Prompts (INCLUDE LANGUAGE_POLICY)

#### 4. `app/staff_ai/service.py` - Staff Assistant
- **Line 253**: `ChatMessage(role="system", content=system_prompt)`
- **Usage**: `_build_staff_assistant_prompt()` - helps staff draft customer replies
- **Status**: ✅ INCLUDES LANGUAGE_POLICY (line 289)
- **Post-generation enforcement**: ✅ Applied after Groq response

#### 5. `app/support_ai/service.py` - generate_chat_summary()
- **Usage**: Internal staff-facing summary generator
- **Status**: ✅ INCLUDES LANGUAGE_POLICY (appended at line 1272)
- **Post-generation enforcement**: Not applied (internal only, but still English/Kiswahili compliant)

### ❌ Internal Classifier Prompts (EXCLUDED - Not Prose to Users)

#### 6. `app/staff_ai/service.py` - Analysis Prompt
- **Line 125**: `ChatMessage(role="system", content=analysis_prompt)`
- **Usage**: `_build_analysis_prompt()` - internal ticket context analysis
- **Output**: Structured JSON (ISSUE_SUMMARY, CUSTOMER_SENTIMENT, etc.)
- **Status**: ❌ EXCLUDED (marked as internal classifier in docstring)
- **Reason**: Output is parsed as structured data, not shown as prose to staff

#### 7. `app/staff_ai/service.py` - Escalation Prompt
- **Line 177**: `ChatMessage(role="system", content=escalation_prompt)`
- **Usage**: `_build_escalation_prompt()` - internal escalation decision
- **Output**: Structured JSON (SHOULD_ESCALATE, SUGGESTED_ESCALATION_TARGET, etc.)
- **Status**: ❌ EXCLUDED (marked as internal classifier in docstring)
- **Reason**: Output is parsed as structured data, not shown as prose to staff

#### 8. `app/clients/groq_client.py` - Out-of-Scope Classifier
- **Line 245**: `ChatMessage(role="system", content=system_prompt)`
- **Usage**: `is_out_of_scope()` - internal scope classification
- **Output**: Structured JSON (is_out_of_scope, reasoning, confidence)
- **Status**: ❌ EXCLUDED (internal classifier)
- **Reason**: Output is parsed as structured data, not shown to users

#### 9. `app/clients/groq_client.py` - Title Generator
- **Line 329**: `ChatMessage(role="system", content=system_prompt)`
- **Usage**: `generate_conversation_title()` - internal title generation
- **Output**: Short 3-8 word title for internal organization
- **Status**: ❌ EXCLUDED (internal utility)
- **Reason**: Output is used for internal organization, not shown as prose to users

## Post-Generation Safety Net

**Implementation:** `app/common/language_check.py`

**Function:** `enforce_language_policy(response_text, original_message)`

**Logic:**
1. Detects language using word-based heuristics (English/Kiswahili word lists)
2. If response is English, Kiswahili, or mixed: returns original response
3. If response is another language: returns fallback message
4. Logs language policy violations

**Fallback Message:**
```
"I apologize, but I currently only support English and Kiswahili. Please write your question in English or Kiswahili, and I'll be happy to help you."
```

**Applied to:**
- All 8 inline prompts in `support_ai/service.py`
- Staff assistant in `staff_ai/service.py`
- Conversation AI chat in `main.py`

## Product Identity Updates

As part of this change, product references were updated from "Shiva" to "Shiva Softwares" in:
- `app/support_ai/agents.py` - SupportAgent base prompt
- `app/support_ai/service.py` - Out-of-scope fallback message
- `app/clients/groq_client.py` - Out-of-scope classifier prompt

## Tests

**File:** `tests/test_language_policy.py`

**Coverage:**
- LANGUAGE_POLICY constant existence and content
- LANGUAGE_POLICY presence in SupportAgent.get_system_prompt()
- Language detection (English, Kiswahili, mixed, other)
- Language policy enforcement function
- Product identity (Shiva Softwares vs Shiva)
- Import verification for all touched modules

## Summary

✅ **9 customer/staff-facing prompts** include LANGUAGE_POLICY
❌ **3 internal classifier prompts** are excluded (intentional - not prose to users)
✅ **Post-generation safety net** implemented and applied to all customer-facing paths
✅ **Product identity** updated to Shiva Softwares throughout
✅ **Tests** added to verify policy membership and functionality
