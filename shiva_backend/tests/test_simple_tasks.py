"""Test simple task detection in AI agents for Shiva Softwares."""
import asyncio
from app.support_ai.agents import AgentOrchestrator

async def test_simple_tasks():
    print("Testing Simple Task Detection for Shiva Softwares\n")
    print("=" * 50)

    # Create orchestrator (we'll pass None for groq_client since we're just testing detection)
    # In real usage, this would be initialized with the actual GroqClient
    class MockGroqClient:
        async def chat_completion(self, messages):
            pass

    orchestrator = AgentOrchestrator(MockGroqClient())

    test_cases = [
        ("How do I reset my password?", True, "Simple - how-to question"),
        ("Where can I find my order history?", True, "Simple - where-is question"),
        ("Can I track my delivery?", True, "Simple - can-i question"),
        ("How do I apply a coupon?", True, "Simple - how-to question"),
        ("My checkout keeps failing with payment errors", False, "Complex - payment issue"),
        ("I see unauthorized charges on my card", False, "Complex - security issue"),
        ("The entire site is down and I can't access anything", False, "Complex - site down issue"),
        ("I need help with product browsing", True, "Simple - help with question"),
        ("Explain how returns work", True, "Simple - explain question"),
        ("Show me how to contact support", True, "Simple - show me question"),
    ]

    print(f"{'Message':<40} {'Expected':<10} {'Actual':<10} {'Status'}")
    print("-" * 70)

    all_passed = True
    for message, expected, description in test_cases:
        actual = orchestrator.is_simple_task(message)
        status = "PASS" if actual == expected else "FAIL"
        if actual != expected:
            all_passed = False

        print(f"{message[:38]:<40} {str(expected):<10} {str(actual):<10} {status}")

    print("=" * 50)
    if all_passed:
        print("All simple task detection tests passed!")
    else:
        print("Some tests failed")

if __name__ == "__main__":
    asyncio.run(test_simple_tasks())