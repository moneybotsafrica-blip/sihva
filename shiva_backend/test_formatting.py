"""Test markdown formatting constraints in agent system prompts."""
import re
from app.support_ai.agents import TechnicalSupportAgent, BillingSupportAgent, GeneralSupportAgent, AccountSupportAgent, SecuritySupportAgent

def test_agent_formatting_rules():
    """Test that all agent system prompts contain the critical formatting rules."""
    print("Testing Markdown Formatting Rules in Agent System Prompts\n")
    print("=" * 80)
    
    # Create mock groq client (we only need the system prompt, not actual API calls)
    class MockGroqClient:
        pass
    
    # Test all agent types
    agents = [
        TechnicalSupportAgent(MockGroqClient()),
        BillingSupportAgent(MockGroqClient()),
        AccountSupportAgent(MockGroqClient()),
        SecuritySupportAgent(MockGroqClient()),
        GeneralSupportAgent(MockGroqClient())
    ]
    
    critical_rules = [
        "NEVER use markdown headers",
        "NEVER use markdown tables", 
        "NEVER use horizontal rules",
        "short paragraphs",
        "plain text chat"
    ]
    
    all_passed = True
    
    for agent in agents:
        system_prompt = agent.get_system_prompt()
        print(f"\n{agent.name}:")
        print("-" * 80)
        
        agent_passed = True
        for rule in critical_rules:
            if rule in system_prompt:
                print(f"  ✅ Contains rule: '{rule}'")
            else:
                print(f"  ❌ Missing rule: '{rule}'")
                agent_passed = False
                all_passed = False
        
        if agent_passed:
            print(f"  ✅ {agent.name} PASSED")
        else:
            print(f"  ❌ {agent.name} FAILED")
    
    print("\n" + "=" * 80)
    
    if all_passed:
        print("[PASS] All agent system prompts contain critical formatting rules!")
        return True
    else:
        print("[FAIL] Some agent system prompts are missing critical formatting rules")
        return False

def test_no_forbidden_patterns_in_prompts():
    """Test that agent prompts don't encourage forbidden markdown patterns."""
    print("\n\nTesting that prompts don't encourage forbidden markdown patterns\n")
    print("=" * 80)
    
    class MockGroqClient:
        pass
    
    agents = [
        TechnicalSupportAgent(MockGroqClient()),
        BillingSupportAgent(MockGroqClient()),
        GeneralSupportAgent(MockGroqClient())
    ]
    
    forbidden_patterns = [
        r'Use markdown headers',
        r'Create tables',
        r'Use horizontal rules',
        r'\|.*\|.*\|',  # Table pattern
    ]
    
    all_passed = True
    
    for agent in agents:
        system_prompt = agent.get_system_prompt()
        print(f"\n{agent.name}:")
        print("-" * 80)
        
        agent_passed = True
        for pattern in forbidden_patterns:
            if re.search(pattern, system_prompt, re.IGNORECASE):
                print(f"  ❌ Contains forbidden pattern: '{pattern}'")
                agent_passed = False
                all_passed = False
            else:
                print(f"  ✅ No forbidden pattern: '{pattern}'")
        
        if agent_passed:
            print(f"  ✅ {agent.name} PASSED")
        else:
            print(f"  ❌ {agent.name} FAILED")
    
    print("\n" + "=" * 80)
    
    if all_passed:
        print("[PASS] No agent prompts encourage forbidden markdown patterns!")
        return True
    else:
        print("[FAIL] Some agent prompts encourage forbidden markdown patterns")
        return False

if __name__ == "__main__":
    test1_passed = test_agent_formatting_rules()
    test2_passed = test_no_forbidden_patterns_in_prompts()
    
    print("\n" + "=" * 80)
    print("FINAL RESULTS:")
    print(f"  Formatting Rules Test: {'PASS' if test1_passed else 'FAIL'}")
    print(f"  Forbidden Patterns Test: {'PASS' if test2_passed else 'FAIL'}")
    print("=" * 80)
    
    exit(0 if (test1_passed and test2_passed) else 1)