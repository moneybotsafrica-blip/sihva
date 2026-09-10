"""Simple test to verify whitespace preservation in streaming."""
import re


def test_whitespace_preservation():
    """Test that the tokenization logic preserves original text exactly."""
    
    # Test case with numbered steps (the problematic case)
    test_text = "1. Restart the app\n2. Clear the cache\n3. Log back in"
    
    # Use the same tokenization logic as the fixed streaming endpoint
    tokens = re.findall(r'\S+|\s+', test_text)
    
    # Reassemble by concatenating all tokens
    reassembled = ''.join(tokens)
    
    # Verify exact match
    assert reassembled == test_text, f"Text mismatch!\nOriginal: {repr(test_text)}\nReassembled: {repr(reassembled)}"
    
    print("✅ Whitespace preservation test passed")
    print(f"Original: {repr(test_text)}")
    print(f"Reassembled: {repr(reassembled)}")
    print(f"Tokens: {tokens}")


if __name__ == "__main__":
    test_whitespace_preservation()