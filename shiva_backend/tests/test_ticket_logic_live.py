"""
Comprehensive test for ticket creation logic for Shiva Softwares.
Tests various edge cases to ensure tickets are only created when the system understands the problem.
NOTE: This test requires the server to be running on localhost:8000
"""
import requests
import json

BASE_URL = "http://localhost:8000/test-groq-analysis"

test_cases = [
    # Gibberish/Random keystrokes - should NOT create tickets
    {
        "name": "Random Gibberish",
        "message": "HELLO GEHCEHVCGSHDWJDNBEQJDHEWIKJFNEWJFDGEWQDHWKRH WYUGEFEHFJEWHFUEWHDKJWJDKSJCXWKWD",
        "should_create_ticket": False,
        "expected_action": "out_of_scope"
    },

    # Vague/No details - should ask for details, NOT create tickets
    {
        "name": "Vague - Not Working",
        "message": "not working",
        "should_create_ticket": False,
        "expected_action": "gather_details"
    },

    # Ticket inquiries without problem - should ask for problem, NOT create tickets
    {
        "name": "Ticket Request No Problem",
        "message": "raise a ticket",
        "should_create_ticket": False,
        "expected_action": "gather_issue_info"
    },
    {
        "name": "How To Raise Ticket",
        "message": "How do I raise a ticket",
        "should_create_ticket": False,  # Informational question - no ticket
        "expected_action": "auto_resolve"
    },

    # Proper problem descriptions - should try to solve, NOT immediately create tickets
    {
        "name": "Checkout Error Description",
        "message": "my checkout shows error 500 when paying",
        "should_create_ticket": True,  # 500 errors get escalated for safety
        "expected_action": "queue_for_staff"
    },

    # Staff-only issues WITH problem description - should try to solve first (conservative)
    {
        "name": "Account Locked",
        "message": "account locked help",
        "should_create_ticket": False,  # Groq should try to solve first
        "expected_action": "auto_resolve"
    },
    {
        "name": "Site Down",
        "message": "site down server error 500",
        "should_create_ticket": False,  # Groq should try to solve first
        "expected_action": "auto_resolve"
    },

    # Additional edge cases for comprehensive testing
    {
        "name": "Hello Only",
        "message": "hello",
        "should_create_ticket": False,
        "expected_action": "auto_resolve"  # Simple greetings get natural response
    },
    {
        "name": "Help With Specific Issue",
        "message": "I need help with my login",
        "should_create_ticket": False,  # Groq should try to solve first
        "expected_action": "auto_resolve"
    },
    {
        "name": "Out of Scope - President",
        "message": "who is the president of kenya",
        "should_create_ticket": False,  # Out of scope - no ticket
        "expected_action": "out_of_scope"
    },
    {
        "name": "Out of Scope - Weather",
        "message": "what is the weather in nairobi",
        "should_create_ticket": False,  # Out of scope - no ticket
        "expected_action": "out_of_scope"
    },
    {
        "name": "Out of Scope - Sports",
        "message": "what is the football score today",
        "should_create_ticket": False,  # Out of scope - no ticket
        "expected_action": "out_of_scope"
    },
    {
        "name": "Security Issue - Hacked Account",
        "message": "my account was hacked",
        "should_create_ticket": True,  # Critical security issue should still escalate
        "expected_action": "queue_for_staff"
    },
    {
        "name": "Unauthorized Charge",
        "message": "I see an unauthorized charge on my card",
        "should_create_ticket": True,  # Financial security issue should escalate
        "expected_action": "queue_for_staff"
    },
    # Shiva Softwares specific cases
    {
        "name": "Order Tracking",
        "message": "where is my order",
        "should_create_ticket": False,  # Should try to solve first
        "expected_action": "auto_resolve"
    },
    {
        "name": "Return Request",
        "message": "I want to return my order",
        "should_create_ticket": False,  # Should provide return policy info
        "expected_action": "auto_resolve"
    },
]

def run_test(test_case):
    """Run a single test case."""
    payload = {
        "message": test_case["message"],
        "customer_id": f"test_{test_case['name'].replace(' ', '_')}",
        "customer_data": {
            "application": "shiva_softwares",
            "name": "Test User",
            "email": "test@example.com",
            "plan": "standard"
        }
    }

    try:
        response = requests.post(BASE_URL, json=payload, timeout=90)
        result = response.json()

        # Handle nested response structure
        if "analysis" in result:
            analysis = result["analysis"]
            actual_should_queue = analysis.get("needs_ticket", False)
            actual_action = analysis.get("action", "unknown")
            response_text = analysis.get("response", "")
        else:
            actual_should_queue = result.get("should_queue", False)
            actual_action = result.get("action", "unknown")
            response_text = result.get("response", "")

        passed = (
            actual_should_queue == test_case["should_create_ticket"] and
            actual_action == test_case["expected_action"]
        )

        return {
            "name": test_case["name"],
            "message": test_case["message"],
            "expected": test_case,
            "actual": {
                "should_queue": actual_should_queue,
                "action": actual_action
            },
            "passed": passed,
            "response_text": response_text[:100]
        }
    except Exception as e:
        return {
            "name": test_case["name"],
            "message": test_case["message"],
            "expected": test_case,
            "actual": {"error": str(e)},
            "passed": False,
            "response_text": "ERROR"
        }

def main():
    """Run all tests."""
    print("Running comprehensive ticket creation logic tests for Shiva Softwares...\n")
    print("=" * 80)

    results = []
    for test_case in test_cases:
        result = run_test(test_case)
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] - {result['name']}")
        print(f"  Message: {result['message'][:50]}...")
        print(f"  Expected: should_queue={test_case['should_create_ticket']}, action={test_case['expected_action']}")
        print(f"  Actual: {result['actual']}")
        print(f"  Response: {result['response_text'].encode('ascii', 'ignore').decode('ascii')}")
        print()

    print("=" * 80)
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    print(f"\nResults: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("[SUCCESS] All tests passed!")
    else:
        print("[FAILURE] Some tests failed:")
        for result in results:
            if not result["passed"]:
                print(f"  - {result['name']}")

if __name__ == "__main__":
    main()
