import os
import uuid
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from pydantic import BaseModel

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog

from app.config import settings
from app.graphql_schema.schema import schema
from app.gateway.auth import AuthContext
from app.gateway.rate_limit import RateLimitMiddleware, rate_limit_exception_handler
from app.db.session import init_db, get_db_context
from app.db.mock_db import (
    seed_mock_database, 
    clear_mock_database, 
    get_mock_customer_ids, 
    get_mock_staff_ids,
    get_mock_customer_info,
    get_mock_staff_info
)
from app.api_keys.service import APIKeyService

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Create rate limiter for specific endpoints
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Shiva AI Support Platform Backend")
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        # Don't fail startup if DB init fails - might be handled elsewhere
    
    yield
    
    # Shutdown
    logger.info("Shutting down Shiva AI Support Platform Backend")


# Create FastAPI app
app = FastAPI(
    title="Shiva AI Support Platform Backend",
    description="Backend API for Shiva AI Support Platform with AI-powered ticket routing",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Add exception handler for rate limiting
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)


@app.middleware("http")
async def cleanup_session_middleware(request: Request, call_next):
    """Middleware to cleanup database sessions after requests."""
    response = await call_next(request)
    
    # Cleanup database session if it exists
    if hasattr(request.state, "db_session"):
        session = request.state.db_session
        try:
            await session.close()
        except Exception as e:
            logger.error("Error closing database session", error=str(e))
    
    return response

# Create upload directory if it doesn't exist
upload_dir = Path(settings.upload_dir)
upload_dir.mkdir(parents=True, exist_ok=True)


# Request models for API endpoints
class APIKeyCreateRequest(BaseModel):
    name: str
    scope: str = "frontend"
    expires_in_days: Optional[int] = None

# Create GraphQL router with auth context
graphql_app = GraphQLRouter(
    schema,
    context_getter=AuthContext.get_context,
)

# Mount GraphQL endpoint using the router's built-in handling
app.include_router(graphql_app, prefix="/graphql")


@app.get("/healthz")
async def health_check():
    """
    Health check endpoint for liveness probes.
    Returns 200 if the service is running.
    """
    return {
        "status": "healthy",
        "service": "shiva-backend",
        "version": "0.1.0",
    }


@app.post("/upload")
@limiter.limit(f"{settings.rate_limit_per_customer}/{settings.rate_limit_window_seconds}seconds")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Upload attachment endpoint.
    Accepts binary file uploads and returns an attachment ID.
    
    This is a REST endpoint (not GraphQL) because GraphQL isn't well-suited
    for multipart file uploads.
    """
    try:
        # Validate file size
        max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        file_size = 0
        content = b""
        
        # Read file in chunks to check size
        chunk_size = 8192
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > max_size_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File size exceeds maximum of {settings.max_upload_size_mb}MB",
                )
            content += chunk
        
        # Reset file position
        await file.seek(0)
        
        # Generate unique attachment ID
        attachment_id = str(uuid.uuid4())
        
        # Determine file extension
        file_extension = Path(file.filename).suffix if file.filename else ""
        
        # Create safe filename
        safe_filename = f"{attachment_id}{file_extension}"
        file_path = upload_dir / safe_filename
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(content)
        
        logger.info(
            "File uploaded successfully",
            attachment_id=attachment_id,
            filename=file.filename,
            size_bytes=file_size,
        )
        
        return {
            "attachment_id": attachment_id,
            "filename": file.filename,
            "size_bytes": file_size,
            "content_type": file.content_type,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("File upload failed", error=str(e), filename=file.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File upload failed",
        )


@app.get("/attachments/{attachment_id}")
async def get_attachment(attachment_id: str):
    """
    Get attachment metadata by ID.
    This endpoint can be used to retrieve attachment information.
    """
    # Find the file in the upload directory
    matching_files = list(upload_dir.glob(f"{attachment_id}.*"))
    
    if not matching_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    
    file_path = matching_files[0]
    file_size = file_path.stat().st_size
    
    return {
        "attachment_id": attachment_id,
        "filename": file_path.name,
        "size_bytes": file_size,
        "exists": True,
    }


@app.post("/mock/seed-database")
async def seed_database():
    """
    Seed the database with mock data for testing.
    This endpoint populates the database with realistic test data.
    """
    try:
        async with get_db_context() as session:
            await seed_mock_database(session)
        
        logger.info("Database seeded successfully with mock data")
        return {
            "status": "success",
            "message": "Database seeded successfully with mock data"
        }
    except Exception as e:
        logger.error("Failed to seed database", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to seed database: {str(e)}"
        )


@app.post("/mock/clear-database")
async def clear_database():
    """
    Clear all mock data from the database.
    This endpoint removes all test data for a clean state.
    """
    try:
        async with get_db_context() as session:
            await clear_mock_database(session)
        
        logger.info("Database cleared successfully")
        return {
            "status": "success",
            "message": "Database cleared successfully"
        }
    except Exception as e:
        logger.error("Failed to clear database", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear database: {str(e)}"
        )


@app.get("/mock/data-info")
async def get_data_info():
    """
    Get information about available mock data.
    This endpoint returns information about mock customers and staff.
    """
    try:
        customer_ids = get_mock_customer_ids()
        staff_ids = get_mock_staff_ids()
        
        customers = []
        for customer_id in customer_ids:
            customer_info = get_mock_customer_info(customer_id)
            if customer_info:
                customers.append({
                    "id": customer_id,
                    **customer_info
                })
        
        staff = []
        for staff_id in staff_ids:
            staff_info = get_mock_staff_info(staff_id)
            if staff_info:
                staff.append({
                    "id": staff_id,
                    **staff_info
                })
        
        return {
            "status": "success",
            "data": {
                "customers": customers,
                "staff": staff,
                "total_customers": len(customers),
                "total_staff": len(staff)
            }
        }
    except Exception as e:
        logger.error("Failed to get mock data info", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get mock data info: {str(e)}"
        )


# API Key Management Endpoints
@app.post("/api-keys")
async def create_api_key(request: Request):
    """
    Create a new API key for frontend/system access.
    
    This endpoint generates a secure API key that can be used to authenticate
    frontend applications or external systems.
    
    Args:
        name: Human-readable name for the key (e.g., "Frontend App", "Mobile App")
        scope: Access scope - "frontend" (default), "internal", or "admin"
        expires_in_days: Optional expiration time in days (None = never expires)
    
    Returns:
        The generated API key (shown only once) and key details
    """
    try:
        data = await request.json()
        name = data.get("name")
        scope = data.get("scope", "frontend")
        expires_in_days = data.get("expires_in_days")
        
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name is required"
            )
        
        result = await APIKeyService.create_api_key(
            name=name,
            scope=scope,
            expires_in_days=expires_in_days,
            created_by="system",
        )
        
        logger.info("API key created via endpoint", name=name, scope=scope)
        
        return {
            "status": "success",
            "data": result,
            "warning": "Save this API key securely. It will not be shown again."
        }
    except ValueError as e:
        logger.error("Invalid API key parameters", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Failed to create API key", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API key: {str(e)}"
        )


@app.get("/api-keys")
async def list_api_keys():
    """
    List all API keys (without the actual keys).
    
    Returns metadata about all API keys but not the keys themselves
    for security reasons.
    """
    try:
        api_keys = await APIKeyService.list_api_keys()
        
        return {
            "status": "success",
            "data": {
                "api_keys": api_keys,
                "total": len(api_keys)
            }
        }
    except Exception as e:
        logger.error("Failed to list API keys", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API keys: {str(e)}"
        )


@app.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str):
    """
    Delete an API key permanently.
    
    Args:
        key_id: The ID of the API key to delete
    
    Returns:
        Success confirmation
    """
    try:
        success = await APIKeyService.delete_api_key(key_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        logger.info("API key deleted via endpoint", key_id=key_id)
        
        return {
            "status": "success",
            "message": "API key deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete API key", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete API key: {str(e)}"
        )


@app.post("/api-keys/{key_id}/deactivate")
async def deactivate_api_key(key_id: str):
    """
    Deactivate an API key without deleting it.
    
    Args:
        key_id: The ID of the API key to deactivate
    
    Returns:
        Success confirmation
    """
    try:
        success = await APIKeyService.deactivate_api_key(key_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found"
            )
        
        logger.info("API key deactivated via endpoint", key_id=key_id)
        
        return {
            "status": "success",
            "message": "API key deactivated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to deactivate API key", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate API key: {str(e)}"
        )


@app.post("/test-groq-analysis")
async def test_groq_analysis(request: Request):
    """
    Real Groq AI analysis endpoint using knowledge base.
    This endpoint uses actual Groq LLM with Qdrant knowledge base for intelligent responses.
    """
    try:
        from app.support_ai.service import SupportAIService
        from app.clients.qdrant_client import QdrantClient
        from app.clients.groq_client import GroqClient
        from app.clients.customer_api import CustomerApiClient, MockCustomerApiClient

        data = await request.json()
        message = data.get("message", "")
        conversation_history = data.get("conversation_history", [])
        customer_id = data.get("customer_id", "gui_customer")

        # Initialize the AI services - use real Groq for dynamic responses
        from app.clients.qdrant_client import MockQdrantClient
        from app.clients.groq_client import GroqClient as RealGroqClient

        # Add mock customer for testing
        mock_customer_api = MockCustomerApiClient()
        from app.clients.customer_api import CustomerAccount
        mock_customer_api.add_mock_customer(
            CustomerAccount(
                customer_id="gui_customer",
                email="gui@example.com",
                name="GUI User",
                plan="pro",
                created_at="2024-01-01T00:00:00Z"
            )
        )

        support_ai = SupportAIService(
            qdrant_client=MockQdrantClient(),
            groq_client=RealGroqClient(),
            customer_api_client=mock_customer_api,
        )
        
        # Process the message with real AI
        result = await support_ai.handle_customer_message(
            ticket_id="gui_session",  # Use temporary ID for GUI session
            customer_id=customer_id,
            message=message,
            ticket_service=None,  # No ticket service for GUI chat
            is_agent_request=False,
            conversation_history=conversation_history,
        )
        
        # Extract the response details
        action = result.get("action", "auto_resolve")
        response = result.get("response", "")
        confidence = result.get("confidence", 0.0)
        should_queue = result.get("should_queue", False)
        kb_context_used = result.get("kb_context_used", False)
        complexity_analysis = result.get("complexity_analysis")
        
        # Ticket creation is decided by SupportAI's completeness and confidence
        # checks. Do not override a usable AI/knowledge-base solution because it
        # happens to include normal troubleshooting language.
        message_type = "general_inquiry"
        needs_ticket = should_queue
        escalation_reason = None

        # Check for out-of-scope messages - never create tickets for these
        if action == "out_of_scope":
            message_type = "out_of_scope"
            needs_ticket = False
            logger.info("Out-of-scope message detected - no ticket creation", message=message)

        # Additional check: don't create tickets for simple greetings even if AI suggests queueing
        simple_greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you", "bye", "goodbye"]
        is_simple_greeting = any(greeting in message.lower() for greeting in simple_greetings)

        # Check for staff-only issues that should always be escalated
        staff_only_indicators = [
            "charged twice", "unauthorized charge", "refund missing",
            "account locked", "account hacked", "security breach", "data loss",
            "cannot access", "outage", "production down", "server error", "500",
            "bug report", "integration failing", "api error", "legal", "complaint",
            "security vulnerability", "security issue", "security report", "vulnerability",
            "hack", "breach", "compromise", "exploit", "attack"
        ]
        has_staff_only_issue = any(indicator in message.lower() for indicator in staff_only_indicators)

        if is_simple_greeting:
            needs_ticket = False
            message_type = "simple_query"
            logger.info("Overriding escalation for simple greeting", message=message)
        elif action == "out_of_scope":
            needs_ticket = False
            message_type = "out_of_scope"
            logger.info("Overriding ticket creation for out-of-scope message", message=message)
        elif has_staff_only_issue:
            message_type = "complex_issue"
            escalation_reason = "Staff-only issue detected"
            needs_ticket = True  # Force ticket creation for staff-only issues
            logger.info("Forcing ticket creation for staff-only issue", message=message)
        elif complexity_analysis and complexity_analysis.get("is_complex"):
            message_type = "complex_issue"
            escalation_reason = ", ".join(complexity_analysis.get("reasons", []))
            needs_ticket = True  # Force ticket creation for complex issues
            logger.info("Forcing ticket creation for complex issue", message=message, reasons=complexity_analysis.get("reasons"))
        elif kb_context_used and not needs_ticket:
            message_type = "kb_resolved"
        elif not needs_ticket:
            message_type = "simple_query"

        ticket_details = None
        if needs_ticket and action != "out_of_scope":
            # The desktop client uses this endpoint too. Persist the escalation
            # so it reaches the real staff queue instead of creating a GUI-only
            # placeholder ticket.
            from app.db.models import TicketPath, TicketStatus
            from app.ticket_center.service import TicketCenterService

            async with get_db_context() as session:
                ticket_service = TicketCenterService(session)
                ticket = await ticket_service.get_customer_ticket(customer_id)
                if ticket:
                    # Only append message and re-queue if not already in staff queue
                    if ticket.status != TicketStatus.PENDING_STAFF:
                        await ticket_service.append_message(
                            ticket.id,
                            sender="customer",
                            content=message,
                        )

                        staff_history = await ticket_service.get_ticket_messages(ticket.id)
                        reason = escalation_reason or "Issue requires staff investigation"
                        chat_summary = await support_ai.generate_chat_summary(
                            ticket_id=ticket.id,
                            conversation_history=staff_history,
                            escalation_reason=reason,
                        )
                        await ticket_service.queue_for_staff(ticket.id, reason, chat_summary)
                        await ticket_service.auto_assign_staff(ticket.id)
                        # Refresh ticket to get the assigned staff ID
                        await session.refresh(ticket)
                        ticket_details = {
                            "id": ticket.id,
                            "status": "PENDING_STAFF",
                            "assigned_staff_id": ticket.assigned_staff_id,
                        }
                    else:
                        # Ticket already in staff queue, just return details
                        ticket_details = {
                            "id": ticket.id,
                            "status": ticket.status,
                            "assigned_staff_id": ticket.assigned_staff_id,
                        }
                else:
                    ticket = await ticket_service.create_ticket(
                        customer_id=customer_id,
                        initial_message=message,
                        path=TicketPath.SUPPORT,
                    )

                    staff_history = await ticket_service.get_ticket_messages(ticket.id)
                    reason = escalation_reason or "Issue requires staff investigation"
                    chat_summary = await support_ai.generate_chat_summary(
                        ticket_id=ticket.id,
                        conversation_history=staff_history,
                        escalation_reason=reason,
                    )
                    await ticket_service.queue_for_staff(ticket.id, reason, chat_summary)
                    await ticket_service.auto_assign_staff(ticket.id)
                    # Refresh ticket to get the assigned staff ID
                    await session.refresh(ticket)
                    ticket_details = {
                        "id": ticket.id,
                        "status": "PENDING_STAFF",
                        "assigned_staff_id": ticket.assigned_staff_id,
                    }
        
        return {
            "status": "success",
            "analysis": {
                "message_type": message_type,
                "response": response or "I am here to help with any Shiva-related questions or issues you might have—feel free to ask about your account, service, payments, or anything else Shivasoftwares! What can I assist with today?",
                "confidence": confidence,
                "needs_ticket": needs_ticket,
                "escalation_reason": escalation_reason,
                "kb_context_used": kb_context_used,
                "action": action,
                "ticket": ticket_details,
            }
        }
        
    except Exception as e:
        logger.error("Real Groq analysis failed", error=str(e), exc_info=True)
        # Return error with details for debugging
        return {
            "status": "error",
            "error": str(e),
            "analysis": {
                "message_type": "error",
                "response": f"I encountered an error: {str(e)}. Using fallback mode.",
                "confidence": 0.0,
                "needs_ticket": False,
                "escalation_reason": f"AI Error: {str(e)}"
            }
        }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
        },
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )
