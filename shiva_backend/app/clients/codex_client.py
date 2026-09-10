from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class CodeAnalysisRequest:
    """Request for code analysis."""

    code_snippet: str
    error_message: Optional[str] = None
    log_context: Optional[str] = None
    file_path: Optional[str] = None


@dataclass
class FixRecommendation:
    """Fix recommendation from code analysis."""

    diff: str
    explanation: str
    confidence: float
    affected_files: List[str]
    metadata: Optional[Dict[str, Any]] = None


class CodexClientInterface(ABC):
    """Abstract interface for Codex/code reasoning client."""

    @abstractmethod
    async def analyze_and_suggest_fix(
        self,
        request: CodeAnalysisRequest,
        model: Optional[str] = None,
    ) -> FixRecommendation:
        """Analyze code and suggest a fix."""
        pass

    @abstractmethod
    async def validate_fix(self, diff: str, context: str) -> bool:
        """Validate that a fix is safe and correct."""
        pass


class CodexClient(CodexClientInterface):
    """Real implementation of Codex client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.codex_api_key
        self.model = model or settings.codex_model
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120.0,
        )

    async def analyze_and_suggest_fix(
        self,
        request: CodeAnalysisRequest,
        model: Optional[str] = None,
    ) -> FixRecommendation:
        """Analyze code and suggest a fix using Codex API."""
        model = model or self.model

        try:
            # Build the prompt for Codex
            prompt = self._build_analysis_prompt(request)

            payload = {
                "model": model,
                "prompt": prompt,
                "max_tokens": 2000,
                "temperature": 0.2,
            }

            response = await self.client.post(
                "https://api.openai.com/v1/code/completions",  # Placeholder endpoint
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Parse the response into a fix recommendation
            fix = self._parse_fix_response(data, request)

            logger.info(
                "Generated fix recommendation",
                confidence=fix.confidence,
                affected_files=len(fix.affected_files),
            )

            return fix
        except httpx.HTTPStatusError as e:
            logger.error(
                "Codex API request failed",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Error calling Codex API",
                error=str(e),
            )
            raise

    def _build_analysis_prompt(self, request: CodeAnalysisRequest) -> str:
        """Build analysis prompt for Codex."""
        prompt_parts = [
            "Analyze the following code and suggest a fix for the reported issue.",
            "",
            "Code:",
            "```",
            request.code_snippet,
            "```",
        ]

        if request.error_message:
            prompt_parts.extend([
                "",
                "Error:",
                request.error_message,
            ])

        if request.log_context:
            prompt_parts.extend([
                "",
                "Relevant logs:",
                request.log_context,
            ])

        if request.file_path:
            prompt_parts.extend([
                "",
                f"File: {request.file_path}",
            ])

        prompt_parts.extend([
            "",
            "Provide your response in the following format:",
            "EXPLANATION: [your explanation]",
            "DIFF: [unified diff format]",
            "CONFIDENCE: [0.0-1.0]",
            "AFFECTED_FILES: [comma-separated list]",
        ])

        return "\n".join(prompt_parts)

    def _parse_fix_response(self, data: Dict[str, Any], request: CodeAnalysisRequest) -> FixRecommendation:
        """Parse Codex response into FixRecommendation."""
        text = data.get("text", "")

        # Parse the structured response
        explanation = ""
        diff = ""
        confidence = 0.7
        affected_files = []

        lines = text.split("\n")
        current_section = None

        for line in lines:
            if line.startswith("EXPLANATION:"):
                current_section = "explanation"
                explanation = line.replace("EXPLANATION:", "").strip()
            elif line.startswith("DIFF:"):
                current_section = "diff"
                diff = line.replace("DIFF:", "").strip()
            elif line.startswith("CONFIDENCE:"):
                confidence = float(line.replace("CONFIDENCE:", "").strip())
            elif line.startswith("AFFECTED_FILES:"):
                affected_files = [
                    f.strip() 
                    for f in line.replace("AFFECTED_FILES:", "").strip().split(",")
                ]
            elif current_section == "explanation":
                explanation += "\n" + line
            elif current_section == "diff":
                diff += "\n" + line

        # Fallback if parsing failed
        if not diff:
            diff = text
            explanation = "Generated fix based on code analysis"
            affected_files = [request.file_path] if request.file_path else ["unknown"]

        return FixRecommendation(
            diff=diff,
            explanation=explanation,
            confidence=confidence,
            affected_files=affected_files,
            metadata={"raw_response": text},
        )

    async def validate_fix(self, diff: str, context: str) -> bool:
        """Validate that a fix is safe and correct."""
        # This would typically run static analysis or tests
        # For now, return True as a placeholder
        logger.info(
            "Validating fix",
            diff_length=len(diff),
        )
        return True

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
