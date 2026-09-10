"""Test that streaming preserves whitespace including newlines."""
import re
import json


def test_whitespace_preservation():
    """Test that tokenization and reassembly preserves original text exactly."""
    
    # Test case with numbered steps (the problematic case)
    test_text = "1. Restart the app\n2. Clear the cache\n3. Log back in"
    
    # Tokenize using the same logic as the streaming endpoint
    tokens = re.findall(r'\S+|\s+', test_text)
    
    # Reassemble by concatenating all tokens
    reassembled = ''.join(tokens)
    
    # Verify exact match
    assert reassembled == test_text, f"Text mismatch!\nOriginal: {repr(test_text)}\nReassembled: {repr(reassembled)}"
    
    # Verify individual tokens are correct
    expected_tokens = ['1.', ' ', 'Restart', ' ', 'the', ' ', 'app', '\n', '2.', ' ', 'Clear', ' ', 'the', ' ', 'cache', '\n', '3.', ' ', 'Log', ' ', 'back', ' ', 'in']
    assert tokens == expected_tokens, f"Token mismatch!\nExpected: {expected_tokens}\nActual: {tokens}"
    
    print("✅ Whitespace preservation test passed")


def test_multiline_formatting():
    """Test that complex multiline formatting is preserved."""
    
    test_text = """Here are the steps:
1. First step
2. Second step
3. Third step

Let me know if you need help."""
    
    tokens = re.findall(r'\S+|\s+', test_text)
    reassembled = ''.join(tokens)
    
    assert reassembled == test_text, f"Text mismatch!\nOriginal: {repr(test_text)}\nReassembled: {repr(reassembled)}"
    
    print("✅ Multiline formatting test passed")


def test_streaming_format():
    """Test that the streaming format produces correct SSE chunks."""
    
    test_text = "Hello\nWorld"
    tokens = re.findall(r'\S+|\s+', test_text)
    
    # Simulate streaming chunks
    chunks = []
    for token in tokens:
        chunk_data = {"delta": token}
        chunk = f"data: {json.dumps(chunk_data)}\n\n"
        chunks.append(chunk)
    
    # Reassemble from SSE format
    reassembled_deltas = []
    for chunk in chunks:
        if chunk.startswith("data: "):
            json_str = chunk[6:-2]  # Remove "data: " prefix and "\n\n" suffix
            try:
                data = json.loads(json_str)
                if "delta" in data:
                    reassembled_deltas.append(data["delta"])
            except json.JSONDecodeError:
                pass
    
    reassembled = ''.join(reassembled_deltas)
    
    assert reassembled == test_text, f"SSE format mismatch!\nOriginal: {repr(test_text)}\nReassembled: {repr(reassembled)}"
    
    print("✅ Streaming format test passed")


if __name__ == "__main__":
    test_whitespace_preservation()
    test_multiline_formatting()
    test_streaming_format()
    print("\n✅ All streaming whitespace tests passed!")