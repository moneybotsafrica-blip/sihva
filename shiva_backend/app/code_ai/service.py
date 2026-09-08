from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import structlog

from app.clients.codex_client import (
    CodexClientInterface,
    CodeAnalysisRequest,
    FixRecommendation as CodexFixRecommendation,
)
from app.code_ai.readers import LogReaderInterface, CodeReaderInterface
from app.ticket_center.service import TicketCenterService
from app.db.models import TicketMessage, MessageSender
from app.config import settings

logger = structlog.get_logger(__name__)


class CodeAIService:
    """Code/Server AI service for analyzing technical issues and suggesting fixes."""

    def __init__(
        self,
        codex_client: CodexClientInterface,
        log_reader: LogReaderInterface,
        code_reader: CodeReaderInterface,
    ):
        self.codex_client = codex_client
        self.log_reader = log_reader
        self.code_reader = code_reader

    async def handle_technical_issue(
        self,
        ticket_id: str,
        message: str,
        ticket_service: TicketCenterService,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Handle a technical issue routed to Code/Server AI.
        
        Process:
        1. Extract error information from message and attachments
        2. Retrieve relevant logs
        3. Retrieve relevant source code
        4. Use Codex to analyze and suggest a fix
        5. Create fix recommendation in ticket system
        6. Queue for staff review
        
        Returns:
            Dict with keys: success, fix_recommendation_id, error
        """
        try:
            # Step 1: Extract error information
            error_info = self._extract_error_info(message, attachments or [])
            
            # Step 2: Retrieve relevant logs
            log_context = await self._retrieve_relevant_logs(error_info)
            
            # Step 3: Retrieve relevant source code
            code_context = await self._retrieve_relevant_code(error_info)
            
            # Step 4: Analyze with Codex
            fix_recommendation = await self._analyze_with_codex(
                error_info=error_info,
                log_context=log_context,
                code_context=code_context,
            )
            
            # Step 5: Create fix recommendation in ticket system
            fix_rec = await ticket_service.create_fix_recommendation(
                ticket_id=ticket_id,
                diff=fix_recommendation.diff,
                explanation=fix_recommendation.explanation,
            )
            
            # Step 6: Queue for staff review
            await ticket_service.queue_for_staff(
                ticket_id=ticket_id,
                reason=f"Fix recommendation generated (confidence: {fix_recommendation.confidence:.2f})",
            )
            
            logger.info(
                "Code AI generated fix recommendation",
                ticket_id=ticket_id,
                fix_rec_id=fix_rec.id,
                confidence=fix_recommendation.confidence,
                affected_files=len(fix_recommendation.affected_files),
            )
            
            return {
                "success": True,
                "fix_recommendation_id": fix_rec.id,
                "confidence": fix_recommendation.confidence,
                "affected_files": fix_recommendation.affected_files,
            }
            
        except Exception as e:
            logger.error(
                "Code AI processing failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            # Queue for staff even on error
            await ticket_service.queue_for_staff(
                ticket_id=ticket_id,
                reason=f"Code AI analysis failed: {str(e)}",
            )
            
            return {
                "success": False,
                "error": str(e),
            }

    def _extract_error_info(
        self,
        message: str,
        attachments: List[str],
    ) -> Dict[str, Any]:
        """Extract error information from message and attachments."""
        error_info = {
            "message": message,
            "attachments": attachments,
            "error_code": None,
            "error_message": None,
            "stack_trace": None,
            "service": None,
        }
        
        # Extract HTTP error codes
        import re
        http_error_match = re.search(r'\b[45]\d{2}\b', message)
        if http_error_match:
            error_info["error_code"] = http_error_match.group()
        
        # Extract error messages
        error_patterns = [
            r"Error:\s*(.+)",
            r"Exception:\s*(.+)",
            r"TypeError:\s*(.+)",
            r"ValueError:\s*(.+)",
        ]
        for pattern in error_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                error_info["error_message"] = match.group(1)
                break
        
        # Extract stack traces
        if "Traceback" in message or "stack trace" in message.lower():
            error_info["stack_trace"] = message
        
        # Extract service name if mentioned
        service_patterns = [
            r"service:\s*(\w+)",
            r"in\s+(\w+)\s+service",
        ]
        for pattern in service_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                error_info["service"] = match.group(1)
                break
        
        return error_info

    async def _retrieve_relevant_logs(
        self,
        error_info: Dict[str, Any],
    ) -> str:
        """Retrieve relevant logs based on error information."""
        try:
            service = error_info.get("service", "app")
            query = error_info.get("error_message") or error_info.get("error_code") or "error"
            
            # Search logs for the error
            log_entries = await self.log_reader.search_logs(
                query=query,
                service=service,
                limit=50,
            )
            
            # Also get recent logs for context
            recent_logs = await self.log_reader.get_logs(
                service=service,
                start_time=datetime.now(timezone.utc) - timedelta(hours=1),
                limit=100,
            )
            
            # Combine and deduplicate
            all_logs = list(set(log_entries + recent_logs))
            
            logger.debug(
                "Retrieved relevant logs",
                service=service,
                log_count=len(all_logs),
            )
            
            return "\n".join(all_logs) if all_logs else "No relevant logs found"
            
        except Exception as e:
            logger.error(
                "Failed to retrieve logs",
                error=str(e),
            )
            return "Failed to retrieve logs"

    async def _retrieve_relevant_code(
        self,
        error_info: Dict[str, Any],
    ) -> Dict[str, str]:
        """Retrieve relevant source code based on error information."""
        try:
            code_context = {}
            
            # If we have an error message, search for related code
            if error_info.get("error_message"):
                search_pattern = error_info["error_message"].split()[0]  # Use first word
                search_results = await self.code_reader.search_code(
                    pattern=search_pattern,
                    file_pattern=".py",  # Assume Python for now
                )
                
                for result in search_results[:5]:  # Limit to top 5 results
                    file_path = result["file_path"]
                    content = await self.code_reader.get_file_content(file_path)
                    if content:
                        code_context[file_path] = content
            
            # If stack trace is present, extract file paths
            if error_info.get("stack_trace"):
                import re
                file_matches = re.findall(r'File "([^"]+)"', error_info["stack_trace"])
                for file_path in file_matches[:3]:  # Limit to top 3 files
                    content = await self.code_reader.get_file_content(file_path)
                    if content:
                        code_context[file_path] = content
            
            logger.debug(
                "Retrieved relevant code",
                file_count=len(code_context),
            )
            
            return code_context
            
        except Exception as e:
            logger.error(
                "Failed to retrieve code",
                error=str(e),
            )
            return {}

    async def _analyze_with_codex(
        self,
        error_info: Dict[str, Any],
        log_context: str,
        code_context: Dict[str, str],
    ) -> CodexFixRecommendation:
        """Use Codex to analyze the issue and suggest a fix."""
        
        # Build code snippet from context
        code_snippet = ""
        if code_context:
            # Combine relevant code files
            for file_path, content in code_context.items():
                code_snippet += f"\n# File: {file_path}\n{content}\n"
        
        # Create analysis request
        request = CodeAnalysisRequest(
            code_snippet=code_snippet,
            error_message=error_info.get("error_message"),
            log_context=log_context if log_context != "No relevant logs found" else None,
            file_path=list(code_context.keys())[0] if code_context else None,
        )
        
        # Get fix recommendation from Codex
        fix_recommendation = await self.codex_client.analyze_and_suggest_fix(request)
        
        logger.info(
            "Codex analysis complete",
            confidence=fix_recommendation.confidence,
            affected_files=len(fix_recommendation.affected_files),
        )
        
        return fix_recommendation

    async def validate_fix(
        self,
        ticket_id: str,
        diff: str,
        ticket_service: TicketCenterService,
    ) -> bool:
        """
        Validate a fix before applying.
        This is a safety check before staff applies the fix.
        """
        try:
            # Get the code context for validation
            # In a real implementation, this would run static analysis or tests
            is_valid = await self.codex_client.validate_fix(
                diff=diff,
                context="Validation before applying fix",
            )
            
            logger.info(
                "Fix validation complete",
                ticket_id=ticket_id,
                is_valid=is_valid,
            )
            
            return is_valid
            
        except Exception as e:
            logger.error(
                "Fix validation failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            return False
