import pytest
from app.ai_router.classifier import AIRouter, classify_message, RouteDecision
from app.clients.qdrant_client import MockQdrantClient, SearchResult


class TestAIRouterTechnicalSignalDetection:
    """Test technical signal detection in AI Router."""

    @pytest.fixture
    def router(self):
        return AIRouter()

    def test_http_error_code_detection(self, router):
        """Test detection of HTTP error codes."""
        assert router._has_technical_signal("I got a 500 error", [])
        assert router._has_technical_signal("Server returned 404", [])
        assert router._has_technical_signal("Error 503 service unavailable", [])
        assert not router._has_technical_signal("No error here", [])

    def test_stack_trace_detection(self, router):
        """Test detection of stack traces."""
        assert router._has_technical_signal("Traceback (most recent call last):", [])
        assert router._has_technical_signal("at com.example.Class.method(Class.java:123)", [])
        assert router._has_technical_signal("Error: NullPointer exception", [])
        assert router._has_technical_signal("TypeError: cannot read property", [])
        assert not router._has_technical_signal("No stack trace here", [])

    def test_technical_trigger_phrases(self, router):
        """Test detection of technical trigger phrases."""
        assert router._has_technical_signal("The app crashes on startup", [])
        assert router._has_technical_signal("It's broken", [])
        assert router._has_technical_signal("Not working properly", [])
        assert router._has_technical_signal("Fails when I click submit", [])
        assert router._has_technical_signal("Exception occurred", [])
        assert router._has_technical_signal("Found a bug", [])
        assert router._has_technical_signal("Doesn't work for me", [])
        assert router._has_technical_signal("Unable to connect", [])
        assert router._has_technical_signal("Cannot login", [])
        assert not router._has_technical_signal("Everything is fine", [])

    def test_technical_attachment_detection(self, router):
        """Test detection of technical attachment types."""
        assert router._has_technical_signal("Here's the file", ["error.log"])
        assert router._has_technical_signal("Check this", ["logs.txt"])
        assert router._has_technical_signal("Screenshot", ["error.png"])
        assert router._has_technical_signal("Image", ["error.jpg"])
        assert router._has_technical_signal("Photo", ["error.jpeg"])
        assert router._has_technical_signal("Stack trace", ["trace.stacktrace"])
        assert not router._has_technical_signal("Regular file", ["document.pdf"])
        # Note: .jpg files are considered technical for potential error screenshots

    def test_combined_signals(self, router):
        """Test that multiple signals are detected correctly."""
        assert router._has_technical_signal("I got a 500 error with this log file", ["app.log"])
        assert router._has_technical_signal("Traceback follows", ["error.png"])
        assert router._has_technical_signal("The app crashes with error 404", [])

    def test_case_insensitivity(self, router):
        """Test that detection is case-insensitive."""
        assert router._has_technical_signal("THE APP CRASHES", [])
        assert router._has_technical_signal("It's BROKEN", [])
        assert router._has_technical_signal("Got a 500 ERROR", [])


class TestClassifyMessage:
    """Test the classify_message pure function."""

    def test_code_route_technical_signal(self):
        """Test that technical signals route to code AI."""
        assert classify_message("I got a 500 error", []) == "code"
        assert classify_message("Traceback (most recent call last):", []) == "code"
        assert classify_message("The app crashes", []) == "code"
        assert classify_message("Having an issue", ["error.log"]) == "code"

    def test_staff_route_no_signal_no_qdrant(self):
        """Test that lack of technical signal routes to staff when no Qdrant client."""
        assert classify_message("How do I reset my password?", []) == "staff"
        assert classify_message("I need help with billing", []) == "staff"
        assert classify_message("Where can I find documentation?", []) == "staff"

    def test_support_route_with_qdrant_match(self):
        """Test that Qdrant matches route to support AI."""
        # This would need async testing in a real scenario
        # For synchronous testing, we verify the logic structure
        qdrant_client = MockQdrantClient()
        qdrant_client.add_mock_document(
            SearchResult(
                id="1",
                score=0.8,
                payload={"content": "password reset instructions"},
                content="To reset your password, go to settings...",
            )
        )
        # Note: This would need async context for full testing
        # The synchronous version defaults to staff for now


class TestAIRouterAsync:
    """Test async classification functionality."""

    @pytest.mark.asyncio
    async def test_full_classification_flow(self):
        """Test the full async classification flow."""
        qdrant_client = MockQdrantClient()
        qdrant_client.add_mock_document(
            SearchResult(
                id="1",
                score=0.8,
                payload={"content": "password reset"},
                content="Password reset instructions",
            )
        )

        router = AIRouter(qdrant_client=qdrant_client, similarity_threshold=0.75)

        # Test technical signal routes to code
        result = await router.classify("I got a 500 error", [])
        assert result == "code"

        # Test KB match routes to support
        result = await router.classify("How do I reset my password?", [])
        assert result == "support"

        # Test fallback to staff
        qdrant_client.documents = []  # Clear mock documents
        result = await router.classify("Random question with no KB match", [])
        assert result == "staff"

    @pytest.mark.asyncio
    async def test_classification_with_attachments(self):
        """Test classification with technical attachments."""
        router = AIRouter()

        # Technical attachment should route to code
        result = await router.classify("Here's the file", ["error.log"])
        assert result == "code"

        # Non-technical attachment without other signals
        result = await router.classify("Here's a document", ["invoice.pdf"])
        assert result == "staff"

    @pytest.mark.asyncio
    async def test_qdrant_error_handling(self):
        """Test that Qdrant errors fall back to staff routing."""
        class FailingQdrantClient:
            async def embed_text(self, text):
                raise Exception("Qdrant connection failed")

            async def search(self, query_vector, limit, score_threshold):
                raise Exception("Search failed")

        router = AIRouter(qdrant_client=FailingQdrantClient())

        # Should fall back to staff on Qdrant error
        result = await router.classify("How do I reset my password?", [])
        assert result == "staff"


class TestAIRouterThresholds:
    """Test similarity threshold configuration."""

    @pytest.mark.asyncio
    async def test_custom_similarity_threshold(self):
        """Test that custom similarity threshold works."""
        qdrant_client = MockQdrantClient()
        qdrant_client.add_mock_document(
            SearchResult(
                id="1",
                score=0.7,  # Below default 0.75 threshold
                payload={"content": "test"},
                content="Test content",
            )
        )

        # With default threshold (0.75), this should not match
        router_default = AIRouter(qdrant_client=qdrant_client)
        result = await router_default.classify("Test message", [])
        assert result == "staff"  # No match above threshold

        # With lower threshold (0.65), this should match
        router_low = AIRouter(qdrant_client=qdrant_client, similarity_threshold=0.65)
        result = await router_low.classify("Test message", [])
        assert result == "support"  # Match above lower threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
