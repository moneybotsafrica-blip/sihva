"""
Live API test for Groq-based out-of-scope detection for Shiva Softwares.
Tests the actual Groq LLM classification instead of keyword matching.
NOTE: This test requires the server to be running on localhost:8000
Run with: pytest tests/test_groq_out_of_scope_live.py --run-live
"""

import requests
import json
import pytest
import sys


def pytest_addoption(parser):
    parser.addoption(
        "--run-live", action="store_true", default=False,
        help="Run live tests that require server on localhost:8000"
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: mark test as requiring live server"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        skip_live = pytest.mark.skip(reason="Need --run-live option to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)


@pytest.mark.live
def test_out_of_scope_live():
    """Test out-of-scope detection using the live API with Groq classification."""
    
    base_url = "http://localhost:8000/test-groq-analysis"
    
    test_cases = [
        # OUT-OF-SCOPE cases
        ("who is the president of kenya", True, "Politics - President"),
        ("what is the weather in nairobi", True, "Weather - Nairobi"),
        ("what is the football score", True, "Sports - Football"),
        ("basketball score today", True, "Sports - Basketball"),
        ("latest news today", True, "News - Latest"),
        ("stock price of apple", True, "Finance - Stock"),
        ("how do i cook pasta", True, "Food - Cooking"),
        ("translate this to spanish", True, "General - Translate"),
        ("best places to visit in japan", True, "Travel - Japan"),
        
        # LANGUAGE POLICY cases (third language - should be in-scope but respond in English)
        ("bonjour comment allez-vous", False, "Language Policy - French greeting", True),
        ("aidez-moi s'il vous plaît", False, "Language Policy - French request", True),
        
        # IN-SCOPE cases (Shiva Softwares specific)
        ("how do I track my order", False, "In-Scope - Order tracking", False),
        ("I need help with my account", False, "In-Scope - Account", False),
        ("checkout payment failed", False, "In-Scope - Payment", False),
        ("cannot login to my account", False, "In-Scope - Login", False),
        ("return policy for products", False, "In-Scope - Returns", False),
        ("help with browsing products", False, "In-Scope - Products", False),
        ("reset my password", False, "In-Scope - Account", False),
        ("apply coupon code", False, "In-Scope - Checkout", False),
    ]
    
    print("Groq-Based Out-of-Scope Detection Live Test (Shiva Softwares)")
    print("=" * 80)
    print(f"{'Category':<30} {'Message':<25} {'Expected':<10} {'Actual':<10} {'Lang':<6} {'Status'}")
    print("-" * 80)
    
    all_passed = True
    passed_count = 0
    failed_count = 0
    
    for test_case in test_cases:
        # Handle both old format (3-tuple) and new format (4-tuple with language check)
        if len(test_case) == 3:
            message, expected_out_of_scope, category = test_case
            check_language = False
        else:
            message, expected_out_of_scope, category, check_language = test_case
        try:
            payload = {
                "message": message,
                "customer_data": {
                    "name": "Test",
                    "email": "test@example.com",
                    "application": "shiva_softwares"
                },
                "conversation_history": []
            }
            
            response = requests.post(base_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            analysis = data.get("analysis", {})
            actual_out_of_scope = analysis.get("action") == "out_of_scope"
            
            # Check language policy for flagged cases
            language_ok = True
            if check_language:
                response_text = analysis.get("response", "")
                # Simple check: response should be in English (not French)
                if response_text:
                    # Check for French words
                    french_indicators = ["bonjour", "comment", "allez", "vous", "aidez", "s'il", "plaît", "merci", "français"]
                    response_lower = response_text.lower()
                    has_french = any(word in response_lower for word in french_indicators)
                    # Also check if it has English words
                    english_indicators = ["hello", "help", "please", "thank", "english", "language"]
                    has_english = any(word in response_lower for word in english_indicators)
                    language_ok = has_english and not has_french
            
            scope_ok = actual_out_of_scope == expected_out_of_scope
            status = "PASS" if (scope_ok and language_ok) else "FAIL"
            
            if scope_ok and language_ok:
                passed_count += 1
            else:
                failed_count += 1
                all_passed = False
            
            lang_status = "✓" if language_ok else "✗"
            print(f"{category:<30} {message[:23]:<25} {str(expected_out_of_scope):<10} {str(actual_out_of_scope):<10} {lang_status:<6} {status}")
            
        except Exception as e:
            print(f"{category:<30} {message[:23]:<25} {str(expected_out_of_scope):<10} {'ERROR':<10} {'N/A':<6} FAIL")
            failed_count += 1
            all_passed = False
            print(f"  Error: {str(e)}")
    
    print("=" * 80)
    print(f"Results: {passed_count}/{len(test_cases)} tests passed, {failed_count} failed")
    
    if all_passed:
        print("[PASS] All Groq-based out-of-scope detection tests passed!")
    else:
        print("[FAIL] Some tests failed - review failed cases above")
        
    return all_passed

if __name__ == "__main__":
    success = test_out_of_scope_live()
    exit(0 if success else 1)
