import uuid
import json
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pydantic import BaseModel
import asyncio

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.openapi.utils import get_openapi
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
from app.api_keys.service import APIKeyService
from app.chat_center.service import ChatCenterService
from app.ai_router.routing_service import RoutingRuleService, RoutingDestinationService, RoutingMetricsService
from app.common.prompts import LANGUAGE_POLICY
from app.common.language_check import enforce_language_policy

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


# Create FastAPI app with enhanced Swagger documentation
app = FastAPI(
    title="Shiva AI Support Platform API",
    description="""
    ## AI-Powered Customer Support System
    
    The Shiva AI Support Platform provides intelligent customer support through:
    
    * **AI Routing**: Automatically routes customer queries to appropriate AI systems
    * **Knowledge Base**: Integration with Qdrant vector database for context-aware responses
    * **Multi-Path Support**: Support, Bug, and Code AI processing paths
    * **GraphQL API**: Flexible query interface for complex data operations
    * **REST API**: Standard REST endpoints for common operations
    
    ### Authentication
    
    Most endpoints require authentication using either:
    * **API Key**: Include in Authorization header as `Bearer YOUR_API_KEY`
    * **JWT Token**: Include in Authorization header as `Bearer YOUR_JWT_TOKEN`
    
    ### Rate Limiting
    
    API endpoints are rate-limited to prevent abuse:
    * 100 requests per minute per customer
    * 50 requests per minute per IP address
    
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",           # Swagger UI
    redoc_url="/redoc",         # ReDoc
    openapi_url="/openapi.json", # OpenAPI schema
)


def custom_openapi():
    """Custom OpenAPI schema with enhanced documentation and security schemes."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Shiva AI Support Platform API",
        version="1.0.0",
        description="AI-powered customer support system with intelligent routing",
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "API Key authentication (format: Bearer YOUR_API_KEY)"
        },
        "JWTAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token authentication (format: Bearer YOUR_JWT_TOKEN)"
        }
    }
    
    # Add global security requirement (optional - can be overridden per endpoint)
    openapi_schema["security"] = [
        {"ApiKeyAuth": []},
        {"JWTAuth": []}
    ]
    
    # Add contact information
    openapi_schema["info"]["contact"] = {
        "name": "Shiva Support Team",
        "email": "support@shiva.com",
        "url": "https://shiva.com"
    }
    
    # Add license information
    openapi_schema["info"]["license"] = {
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    }
    
    # Add servers
    openapi_schema["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "Development server"
        },
        {
            "url": "http://10.61.20.203:8000",
            "description": "Local network server"
        },
        {
            "url": "https://api.shiva.com",
            "description": "Production server"
        }
    ]
    
    # Add tags for better organization
    openapi_schema["tags"] = [
        {
            "name": "Health",
            "description": "Health check and system status endpoints"
        },
        {
            "name": "Support",
            "description": "AI-powered support and customer service endpoints"
        },
        {
            "name": "GraphQL",
            "description": "GraphQL API endpoints"
        },
        {
            "name": "API Keys",
            "description": "API key management endpoints"
        },
        {
            "name": "Uploads",
            "description": "File upload and attachment management"
        },
        {
            "name": "Conversations",
            "description": "Conversation and chat session management (React frontend compatibility)"
        },
        {
            "name": "Notifications",
            "description": "Real-time notification streaming (React frontend compatibility)"
        },
        {
            "name": "Routing",
            "description": "Dynamic routing rule and destination management endpoints"
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
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

# Routing Rule Management Request Models
class RoutingRuleCreateRequest(BaseModel):
    name: str
    conditions: list
    actions: list
    description: Optional[str] = None
    priority: int = 100
    weight: float = 1.0
    is_active: bool = True
    is_experiment: bool = False
    parent_rule_id: Optional[str] = None

class RoutingRuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    conditions: Optional[list] = None
    actions: Optional[list] = None
    priority: Optional[int] = None
    weight: Optional[float] = None
    is_active: Optional[bool] = None

class RoutingDestinationCreateRequest(BaseModel):
    name: str
    display_name: str
    destination_type: str
    description: Optional[str] = None
    config: Optional[dict] = None
    is_active: bool = True
    priority: int = 100

class RoutingDestinationUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None

class RoutingFeedbackRequest(BaseModel):
    metric_id: str
    feedback_source: str
    feedback_type: str
    correct_destination: Optional[str] = None
    comment: Optional[str] = None
    rating: Optional[int] = None

# Create GraphQL router with auth context
graphql_app = GraphQLRouter(
    schema,
    context_getter=AuthContext.get_context,
)

# Mount GraphQL endpoint using the router's built-in handling
app.include_router(graphql_app, prefix="/graphql", tags=["GraphQL"])


# Dynamic Routing Management Endpoints
@app.post("/routing/rules", tags=["Routing"])
async def create_routing_rule(request: Request):
    """
    Create a new dynamic routing rule.
    
    **Request Body:**
    - `name` (required): Human-readable rule name
    - `conditions` (required): Array of condition objects
    - `actions` (required): Array of action objects
    - `description` (optional): Rule description
    - `priority` (optional): Rule evaluation priority (default: 100)
    - `weight` (optional): Scoring weight (default: 1.0)
    - `is_active` (optional): Whether rule is active (default: true)
    - `is_experiment` (optional): Whether this is an A/B test variant (default: false)
    - `parent_rule_id` (optional): Parent rule ID for A/B testing
    
    **Condition Object Format:**
    ```json
    {
      "type": "contains|regex|exact_match|length_greater_than|length_less_than|has_attachment|attachment_type|customer_plan|time_of_day|day_of_week",
      "field": "message|customer_id|customer_plan|customer_application",
      "value": "pattern or value to match",
      "case_sensitive": false
    }
    ```
    
    **Action Object Format:**
    ```json
    {
      "type": "route_to|set_priority|add_tag|escalate|require_human|use_ai_model|call_webhook",
      "destination": "support_ai|code_ai|staff|billing",
      "priority": 1
    }
    ```
    
    **Response:**
    - `rule_id`: Created rule ID
    - `name`: Rule name
    - `conditions`: Rule conditions
    - `actions`: Rule actions
    - `priority`: Rule priority
    - `weight`: Rule weight
    - `is_active`: Active status
    - `created_at`: Creation timestamp
    
    **Error Responses:**
    - `400`: Invalid request parameters
    - `500`: Server error
    """
    try:
        data = await request.json()
        
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rule = await service.create_rule(
                name=data.get("name"),
                conditions=data.get("conditions"),
                actions=data.get("actions"),
                description=data.get("description"),
                priority=data.get("priority", 100),
                weight=data.get("weight", 1.0),
                is_active=data.get("is_active", True),
                created_by="system",  # In production, get from auth
                is_experiment=data.get("is_experiment", False),
                parent_rule_id=data.get("parent_rule_id"),
            )
            
            return {
                "status": "success",
                "data": {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "conditions": rule.conditions,
                    "actions": rule.actions,
                    "priority": rule.priority,
                    "weight": rule.weight,
                    "is_active": rule.is_active,
                    "is_experiment": rule.is_experiment,
                    "parent_rule_id": rule.parent_rule_id,
                    "created_at": rule.created_at.isoformat(),
                }
            }
    except Exception as e:
        logger.error("Failed to create routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create routing rule: {str(e)}"
        )


@app.get("/routing/rules", tags=["Routing"])
async def list_routing_rules(
    is_active: Optional[bool] = None,
    is_experiment: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List routing rules with optional filters.
    
    **Query Parameters:**
    - `is_active`: Filter by active status
    - `is_experiment`: Filter by experiment status
    - `limit`: Maximum number of results (default: 100)
    - `offset`: Result offset for pagination (default: 0)
    
    **Response:**
    - `rules`: Array of routing rule objects
    - `total`: Total number of rules
    
    **Error Responses:**
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rules = await service.list_rules(
                is_active=is_active,
                is_experiment=is_experiment,
                limit=limit,
                offset=offset,
            )
            
            return {
                "status": "success",
                "data": {
                    "rules": [
                        {
                            "rule_id": rule.id,
                            "name": rule.name,
                            "description": rule.description,
                            "conditions": rule.conditions,
                            "actions": rule.actions,
                            "priority": rule.priority,
                            "weight": rule.weight,
                            "is_active": rule.is_active,
                            "is_experiment": rule.is_experiment,
                            "parent_rule_id": rule.parent_rule_id,
                            "total_matches": rule.total_matches,
                            "successful_matches": rule.successful_matches,
                            "last_matched_at": rule.last_matched_at.isoformat() if rule.last_matched_at else None,
                            "created_at": rule.created_at.isoformat(),
                            "updated_at": rule.updated_at.isoformat(),
                        }
                        for rule in rules
                    ],
                    "total": len(rules)
                }
            }
    except Exception as e:
        logger.error("Failed to list routing rules", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list routing rules: {str(e)}"
        )


@app.get("/routing/rules/{rule_id}", tags=["Routing"])
async def get_routing_rule(rule_id: str):
    """
    Get a specific routing rule by ID.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Response:**
    - Full rule object with all details
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rule = await service.get_rule(rule_id)
            
            if not rule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "data": {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "conditions": rule.conditions,
                    "actions": rule.actions,
                    "priority": rule.priority,
                    "weight": rule.weight,
                    "is_active": rule.is_active,
                    "is_experiment": rule.is_experiment,
                    "parent_rule_id": rule.parent_rule_id,
                    "total_matches": rule.total_matches,
                    "successful_matches": rule.successful_matches,
                    "last_matched_at": rule.last_matched_at.isoformat() if rule.last_matched_at else None,
                    "created_at": rule.created_at.isoformat(),
                    "updated_at": rule.updated_at.isoformat(),
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get routing rule: {str(e)}"
        )


@app.put("/routing/rules/{rule_id}", tags=["Routing"])
async def update_routing_rule(rule_id: str, request: Request):
    """
    Update a routing rule.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Request Body:**
    - `name` (optional): New rule name
    - `description` (optional): New description
    - `conditions` (optional): New conditions
    - `actions` (optional): New actions
    - `priority` (optional): New priority
    - `weight` (optional): New weight
    - `is_active` (optional): New active status
    
    **Response:**
    - Updated rule object
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        data = await request.json()
        
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rule = await service.update_rule(
                rule_id=rule_id,
                name=data.get("name"),
                description=data.get("description"),
                conditions=data.get("conditions"),
                actions=data.get("actions"),
                priority=data.get("priority"),
                weight=data.get("weight"),
                is_active=data.get("is_active"),
            )
            
            if not rule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "data": {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "conditions": rule.conditions,
                    "actions": rule.actions,
                    "priority": rule.priority,
                    "weight": rule.weight,
                    "is_active": rule.is_active,
                    "updated_at": rule.updated_at.isoformat(),
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update routing rule: {str(e)}"
        )


@app.delete("/routing/rules/{rule_id}", tags=["Routing"])
async def delete_routing_rule(rule_id: str):
    """
    Delete a routing rule.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Response:**
    - `status`: "success"
    - `message`: Confirmation message
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            success = await service.delete_rule(rule_id)
            
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "message": "Routing rule deleted successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete routing rule: {str(e)}"
        )


@app.post("/routing/rules/{rule_id}/activate", tags=["Routing"])
async def activate_routing_rule(rule_id: str):
    """
    Activate a routing rule.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Response:**
    - Updated rule object
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rule = await service.activate_rule(rule_id)
            
            if not rule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "data": {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "is_active": rule.is_active,
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to activate routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate routing rule: {str(e)}"
        )


@app.post("/routing/rules/{rule_id}/deactivate", tags=["Routing"])
async def deactivate_routing_rule(rule_id: str):
    """
    Deactivate a routing rule.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Response:**
    - Updated rule object
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            rule = await service.deactivate_rule(rule_id)
            
            if not rule:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "data": {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "is_active": rule.is_active,
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to deactivate routing rule", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate routing rule: {str(e)}"
        )


@app.get("/routing/rules/{rule_id}/stats", tags=["Routing"])
async def get_routing_rule_stats(rule_id: str):
    """
    Get statistics for a routing rule.
    
    **Parameters:**
    - `rule_id`: Rule ID (path parameter)
    
    **Response:**
    - `rule_id`: Rule ID
    - `name`: Rule name
    - `total_matches`: Total number of times rule matched
    - `successful_matches`: Number of successful matches
    - `success_rate`: Success rate (0.0 to 1.0)
    - `last_matched_at`: Last match timestamp
    - `is_active`: Active status
    
    **Error Responses:**
    - `404`: Rule not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingRuleService(session)
            stats = await service.get_rule_stats(rule_id)
            
            if not stats:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing rule not found"
                )
            
            return {
                "status": "success",
                "data": stats
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get routing rule stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get routing rule stats: {str(e)}"
        )


# Routing Destination Management Endpoints
@app.post("/routing/destinations", tags=["Routing"])
async def create_routing_destination(request: Request):
    """
    Create a new routing destination.
    
    **Request Body:**
    - `name` (required): Unique destination identifier
    - `display_name` (required): Human-readable name
    - `destination_type` (required): Type (ai, human, webhook, api)
    - `description` (optional): Description
    - `config` (optional): Destination-specific configuration
    - `is_active` (optional): Active status (default: true)
    - `priority` (optional): Priority (default: 100)
    
    **Response:**
    - Created destination object
    
    **Error Responses:**
    - `400`: Invalid request
    - `500`: Server error
    """
    try:
        data = await request.json()
        
        async with get_db_context() as session:
            service = RoutingDestinationService(session)
            destination = await service.create_destination(
                name=data.get("name"),
                display_name=data.get("display_name"),
                destination_type=data.get("destination_type"),
                description=data.get("description"),
                config=data.get("config"),
                is_active=data.get("is_active", True),
                priority=data.get("priority", 100),
            )
            
            return {
                "status": "success",
                "data": {
                    "destination_id": destination.id,
                    "name": destination.name,
                    "display_name": destination.display_name,
                    "description": destination.description,
                    "destination_type": destination.destination_type,
                    "config": destination.config,
                    "is_active": destination.is_active,
                    "priority": destination.priority,
                    "created_at": destination.created_at.isoformat(),
                }
            }
    except Exception as e:
        logger.error("Failed to create routing destination", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create routing destination: {str(e)}"
        )


@app.get("/routing/destinations", tags=["Routing"])
async def list_routing_destinations(
    is_active: Optional[bool] = None,
    destination_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List routing destinations with optional filters.
    
    **Query Parameters:**
    - `is_active`: Filter by active status
    - `destination_type`: Filter by destination type
    - `limit`: Maximum number of results (default: 100)
    - `offset`: Result offset for pagination (default: 0)
    
    **Response:**
    - `destinations`: Array of destination objects
    - `total`: Total number of destinations
    
    **Error Responses:**
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingDestinationService(session)
            destinations = await service.list_destinations(
                is_active=is_active,
                destination_type=destination_type,
                limit=limit,
                offset=offset,
            )
            
            return {
                "status": "success",
                "data": {
                    "destinations": [
                        {
                            "destination_id": dest.id,
                            "name": dest.name,
                            "display_name": dest.display_name,
                            "description": dest.description,
                            "destination_type": dest.destination_type,
                            "config": dest.config,
                            "is_active": dest.is_active,
                            "priority": dest.priority,
                            "created_at": dest.created_at.isoformat(),
                            "updated_at": dest.updated_at.isoformat(),
                        }
                        for dest in destinations
                    ],
                    "total": len(destinations)
                }
            }
    except Exception as e:
        logger.error("Failed to list routing destinations", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list routing destinations: {str(e)}"
        )


@app.put("/routing/destinations/{destination_id}", tags=["Routing"])
async def update_routing_destination(destination_id: str, request: Request):
    """
    Update a routing destination.
    
    **Parameters:**
    - `destination_id`: Destination ID (path parameter)
    
    **Request Body:**
    - `display_name` (optional): New display name
    - `description` (optional): New description
    - `config` (optional): New configuration
    - `is_active` (optional): New active status
    - `priority` (optional): New priority
    
    **Response:**
    - Updated destination object
    
    **Error Responses:**
    - `404`: Destination not found
    - `500`: Server error
    """
    try:
        data = await request.json()
        
        async with get_db_context() as session:
            service = RoutingDestinationService(session)
            destination = await service.update_destination(
                destination_id=destination_id,
                display_name=data.get("display_name"),
                description=data.get("description"),
                config=data.get("config"),
                is_active=data.get("is_active"),
                priority=data.get("priority"),
            )
            
            if not destination:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing destination not found"
                )
            
            return {
                "status": "success",
                "data": {
                    "destination_id": destination.id,
                    "name": destination.name,
                    "display_name": destination.display_name,
                    "description": destination.description,
                    "destination_type": destination.destination_type,
                    "config": destination.config,
                    "is_active": destination.is_active,
                    "priority": destination.priority,
                    "updated_at": destination.updated_at.isoformat(),
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update routing destination", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update routing destination: {str(e)}"
        )


@app.delete("/routing/destinations/{destination_id}", tags=["Routing"])
async def delete_routing_destination(destination_id: str):
    """
    Delete a routing destination.
    
    **Parameters:**
    - `destination_id`: Destination ID (path parameter)
    
    **Response:**
    - `status`: "success"
    - `message`: Confirmation message
    
    **Error Responses:**
    - `404`: Destination not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingDestinationService(session)
            success = await service.delete_destination(destination_id)
            
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Routing destination not found"
                )
            
            return {
                "status": "success",
                "message": "Routing destination deleted successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete routing destination", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete routing destination: {str(e)}"
        )


# Routing Metrics and Feedback Endpoints
@app.get("/routing/metrics/performance", tags=["Routing"])
async def get_routing_performance(
    destination: Optional[str] = None,
    rule_id: Optional[str] = None,
    days: int = 30,
):
    """
    Get routing performance statistics.
    
    **Query Parameters:**
    - `destination`: Filter by destination
    - `rule_id`: Filter by rule ID
    - `days`: Number of days to analyze (default: 30)
    
    **Response:**
    - `total_routings`: Total number of routings
    - `avg_confidence`: Average confidence score
    - `avg_resolution_time`: Average resolution time in seconds
    - `escalation_rate`: Rate of escalations (0.0 to 1.0)
    - `avg_customer_satisfaction`: Average customer satisfaction (1-5)
    
    **Error Responses:**
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            service = RoutingMetricsService(session)
            performance = await service.get_routing_performance(
                destination=destination,
                rule_id=rule_id,
                days=days,
            )
            
            return {
                "status": "success",
                "data": performance
            }
    except Exception as e:
        logger.error("Failed to get routing performance", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get routing performance: {str(e)}"
        )


@app.post("/routing/feedback", tags=["Routing"])
async def add_routing_feedback(request: Request):
    """
    Add feedback for a routing decision.
    
    **Request Body:**
    - `metric_id` (required): Routing metric ID
    - `feedback_source` (required): Source (customer, staff, system)
    - `feedback_type` (required): Type (correct, incorrect, partial)
    - `correct_destination` (optional): What the correct destination should have been
    - `comment` (optional): Additional comments
    - `rating` (optional): Rating (1-5 scale)
    
    **Response:**
    - `feedback_id`: Created feedback ID
    - `metric_id`: Associated metric ID
    - `feedback_type`: Feedback type
    - `created_at`: Creation timestamp
    
    **Error Responses:**
    - `400`: Invalid request
    - `404`: Metric not found
    - `500`: Server error
    """
    try:
        data = await request.json()
        
        async with get_db_context() as session:
            service = RoutingMetricsService(session)
            feedback = await service.add_feedback(
                metric_id=data.get("metric_id"),
                feedback_source=data.get("feedback_source"),
                feedback_type=data.get("feedback_type"),
                correct_destination=data.get("correct_destination"),
                comment=data.get("comment"),
                rating=data.get("rating"),
            )
            
            return {
                "status": "success",
                "data": {
                    "feedback_id": feedback.id,
                    "metric_id": feedback.metric_id,
                    "feedback_source": feedback.feedback_source,
                    "feedback_type": feedback.feedback_type,
                    "correct_destination": feedback.correct_destination,
                    "comment": feedback.comment,
                    "rating": feedback.rating,
                    "created_at": feedback.created_at.isoformat(),
                }
            }
    except Exception as e:
        logger.error("Failed to add routing feedback", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add routing feedback: {str(e)}"
        )


@app.post("/routing/stream", tags=["Routing"])
async def stream_routing_decision(request: Request):
    """
    Streaming endpoint for real-time routing decision analysis.
    
    This endpoint streams the routing decision process step-by-step, providing
    real-time insight into how the routing engine processes each message.
    
    **Request Body:**
    - `message` (required): Customer's message to route
    - `customer_id` (optional): Customer identifier
    - `customer_data` (optional): Customer information
    - `attachments` (optional): List of attachment filenames
    - `conversation_history` (optional): Previous conversation messages
    
    **Response:** Server-Sent Events (SSE) stream with JSON chunks:
    - Each chunk contains step-by-step routing analysis
    - Final chunk contains the complete routing decision
    
    **Example Request:**
    ```json
    {
      "message": "I'm getting a 500 error when accessing the dashboard",
      "customer_id": "cust_123",
      "customer_data": {
        "application": "shiva_analytics",
        "plan": "enterprise"
      },
      "attachments": ["error.log"]
    }
    ```
    
    **Stream Events:**
    - `{"step": "initialization", "message": "Starting routing analysis..."}`
    - `{"step": "loading_rules", "message": "Loading 15 active rules..."}`
    - `{"step": "evaluating_rules", "rule": "HTTP Error Detection", "matched": true}`
    - `{"step": "calculating_confidence", "score": 0.85}`
    - `{"step": "final_decision", "destination": "code_ai", "confidence": 0.85}`
    """
    try:
        from app.ai_router.dynamic_router import DynamicRouter, RoutingContext
        
        data = await request.json()
        message = data.get("message", "")
        customer_id = data.get("customer_id")
        customer_data = data.get("customer_data")
        attachments = data.get("attachments", [])
        conversation_history = data.get("conversation_history", [])
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="message is required"
            )
        
        async def generate_routing_stream():
            """Generate streaming routing analysis."""
            try:
                # Step 1: Initialization
                yield json.dumps({
                    "step": "initialization",
                    "message": "Starting routing analysis...",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }) + "\n\n"
                await asyncio.sleep(0.1)
                
                # Step 2: Load routing context
                yield json.dumps({
                    "step": "context_setup",
                    "message": "Setting up routing context",
                    "message_length": len(message),
                    "has_attachments": len(attachments) > 0,
                    "customer_id": customer_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }) + "\n\n"
                await asyncio.sleep(0.1)
                
                # Step 3: Database session
                async with get_db_context() as session:
                    yield json.dumps({
                        "step": "database_connected",
                        "message": "Connected to routing database",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 4: Initialize dynamic router
                    from app.clients.qdrant_client import QdrantClient
                    try:
                        qdrant_client = QdrantClient()
                        yield json.dumps({
                            "step": "services_initialized",
                            "message": "Qdrant client initialized",
                            "qdrant_available": True,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }) + "\n\n"
                    except Exception as e:
                        qdrant_client = None
                        yield json.dumps({
                            "step": "services_initialized",
                            "message": "Qdrant client not available, proceeding without KB",
                            "qdrant_available": False,
                            "error": str(e),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 5: Create routing context
                    context = RoutingContext(
                        message=message,
                        customer_id=customer_id,
                        customer_data=customer_data,
                        attachments=attachments,
                        conversation_history=conversation_history,
                    )
                    
                    # Get KB similarity if Qdrant is available
                    if qdrant_client:
                        try:
                            query_vector = await qdrant_client.embed_text(message)
                            results = await qdrant_client.search(
                                query_vector=query_vector,
                                limit=1,
                                score_threshold=0.75,
                            )
                            if results:
                                context.kb_similarity_score = results[0].score
                                yield json.dumps({
                                    "step": "kb_analysis",
                                    "message": "Knowledge base analysis complete",
                                    "similarity_score": context.kb_similarity_score,
                                    "has_kb_match": context.kb_similarity_score > 0.75,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                }) + "\n\n"
                        except Exception as e:
                            yield json.dumps({
                                "step": "kb_analysis",
                                "message": "KB analysis failed, proceeding without it",
                                "error": str(e),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 6: Initialize router
                    router = DynamicRouter(qdrant_client=qdrant_client)
                    yield json.dumps({
                        "step": "router_ready",
                        "message": "Dynamic router initialized",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 7: Load rules
                    rules = await router._get_active_rules(session)
                    yield json.dumps({
                        "step": "rules_loaded",
                        "message": f"Loaded {len(rules)} active routing rules",
                        "rule_count": len(rules),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 8: Evaluate rules (stream each evaluation)
                    matched_rules = []
                    for i, rule in enumerate(rules):
                        is_match = await router._evaluate_rule(rule, context)
                        if is_match:
                            matched_rules.append(rule)
                            yield json.dumps({
                                "step": "rule_matched",
                                "message": f"Rule matched: {rule.name}",
                                "rule_id": rule.id,
                                "rule_name": rule.name,
                                "rule_priority": rule.priority,
                                "rule_weight": rule.weight,
                                "match_number": len(matched_rules),
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }) + "\n\n"
                        await asyncio.sleep(0.05)  # Small delay for streaming effect
                    
                    # Step 9: Select best rule
                    if matched_rules:
                        best_rule = max(matched_rules, key=lambda r: (r.priority, r.weight))
                        yield json.dumps({
                            "step": "best_rule_selected",
                            "message": f"Selected best rule: {best_rule.name}",
                            "rule_id": best_rule.id,
                            "rule_name": best_rule.name,
                            "total_matched": len(matched_rules),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }) + "\n\n"
                    else:
                        yield json.dumps({
                            "step": "no_rules_matched",
                            "message": "No rules matched, using fallback",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 10: Make final routing decision
                    decision = await router.route(context, session)
                    
                    # Step 11: Calculate and stream final details
                    yield json.dumps({
                        "step": "calculating_confidence",
                        "message": "Calculating routing confidence",
                        "confidence": decision.confidence,
                        "matched_rules_count": len(decision.matched_rules),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }) + "\n\n"
                    await asyncio.sleep(0.1)
                    
                    # Step 12: Final decision
                    yield json.dumps({
                        "step": "final_decision",
                        "message": "Routing decision complete",
                        "destination": decision.destination,
                        "confidence": decision.confidence,
                        "matched_rules": decision.matched_rules,
                        "actions": decision.actions,
                        "reasoning": decision.reasoning,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "done": True
                    }) + "\n\n"
                    
            except asyncio.CancelledError:
                logger.info("Routing stream cancelled by client")
                yield json.dumps({
                    "step": "cancelled",
                    "message": "Stream cancelled by client",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }) + "\n\n"
            except Exception as e:
                logger.error("Routing stream error", error=str(e))
                yield json.dumps({
                    "step": "error",
                    "message": f"Error in routing stream: {str(e)}",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "done": True
                }) + "\n\n"
        
        return StreamingResponse(
            generate_routing_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Streaming routing failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Streaming routing failed: {str(e)}"
        )


@app.get("/healthz", tags=["Health"])
async def health_check():
    """
    Health check endpoint for liveness probes.
    
    Returns 200 if the service is running and healthy.
    This endpoint is typically used by load balancers and orchestration systems.
    
    **Response:**
    - `status`: "healthy" if the service is operational
    - `service`: Service identifier
    - `version`: Current version of the service
    """
    return {
        "status": "healthy",
        "service": "shiva-backend",
        "version": "1.0.0",
    }


@app.get("/admin/ai-resolution-analytics", tags=["Admin"])
async def get_ai_resolution_analytics(days: int = 30):
    """
    Get AI resolution analytics for quality improvement.
    
    Provides insights into AI resolution performance including:
    - NOT_HELPFUL rate by agent type (Technical, Billing, etc.)
    - NOT_HELPFUL rate by KB article
    - Overall feedback breakdown
    
    **Query Parameters:**
    - `days`: Number of days to analyze (default: 30)
    
    **Response:**
    - `total_ai_resolutions`: Total number of AI-resolved tickets
    - `feedback_breakdown`: Count by feedback type
    - `not_helpful_rate`: Overall NOT_HELPFUL rate
    - `agent_type_breakdown`: Count by agent type
    - `agent_type_not_helpful_rates`: NOT_HELPFUL rate by agent type
    - `kb_article_not_helpful_rates`: NOT_HELPFUL rate by KB article
    """
    try:
        async with get_db_context() as session:
            from app.ticket_center.service import TicketCenterService
            service = TicketCenterService(session)
            analytics = await service.get_ai_resolution_analytics(days=days)
            return {
                "status": "success",
                "data": analytics
            }
    except Exception as e:
        logger.error("Failed to get AI resolution analytics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics: {str(e)}"
        )


@app.get("/admin/routing-feedback-analytics", tags=["Admin"])
async def get_routing_feedback_analytics(days: int = 30):
    """
    Get routing feedback analytics for quality improvement.
    
    Provides insights into routing decision quality including:
    - Incorrect routing rate by destination
    - Incorrect routing rate by rule
    - Overall feedback breakdown
    
    **Query Parameters:**
    - `days`: Number of days to analyze (default: 30)
    
    **Response:**
    - `total_routings`: Total number of routing decisions
    - `total_with_feedback`: Number with feedback
    - `feedback_breakdown`: Count by feedback type
    - `incorrect_routing_rate`: Overall incorrect rate
    - `destination_incorrect_rates`: Incorrect rate by destination
    - `rule_incorrect_rates`: Incorrect rate by rule
    """
    try:
        async with get_db_context() as session:
            from app.ai_router.routing_service import RoutingMetricsService
            service = RoutingMetricsService(session)
            analytics = await service.get_routing_feedback_analytics(days=days)
            return {
                "status": "success",
                "data": analytics
            }
    except Exception as e:
        logger.error("Failed to get routing feedback analytics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics: {str(e)}"
        )


@app.post("/upload", tags=["Uploads"])
@limiter.limit(f"{settings.rate_limit_per_customer}/{settings.rate_limit_window_seconds}seconds")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Upload attachment endpoint.
    
    Accepts binary file uploads and returns an attachment ID that can be referenced in support tickets.
    
    **Rate Limiting:** 100 requests per 60 seconds per customer
    
    **Request:**
    - `file`: Binary file to upload (multipart/form-data)
    
    **Response:**
    - `attachment_id`: Unique identifier for the uploaded file
    - `filename`: Original filename
    - `size_bytes`: File size in bytes
    - `content_type`: MIME type of the file
    
    **Error Responses:**
    - `413`: File size exceeds maximum (10MB default)
    - `500`: Upload failed due to server error
    
    **Note:** This is a REST endpoint (not GraphQL) because GraphQL isn't well-suited for multipart file uploads.
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


@app.get("/attachments/{attachment_id}", tags=["Uploads"])
async def get_attachment(attachment_id: str):
    """
    Get attachment metadata by ID.
    
    Retrieves information about a previously uploaded attachment without downloading the file itself.
    
    **Parameters:**
    - `attachment_id`: Unique identifier of the attachment (path parameter)
    
    **Response:**
    - `attachment_id`: Attachment identifier
    - `filename`: Stored filename
    - `size_bytes`: File size in bytes
    - `exists`: Whether the file exists
    
    **Error Responses:**
    - `404`: Attachment not found
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


# API Key Management Endpoints
@app.post("/api-keys", tags=["API Keys"])
async def create_api_key(request: Request):
    """
    Create a new API key for frontend/system access.
    
    This endpoint generates a secure API key that can be used to authenticate
    frontend applications or external systems.
    
    **Request Body:**
    - `name` (required): Human-readable name for the key (e.g., "Frontend App", "Mobile App")
    - `scope` (optional): Access scope - "frontend" (default), "internal", or "admin"
    - `expires_in_days` (optional): Expiration time in days (null = never expires)
    
    **Response:**
    - `api_key`: The generated API key (shown only once!)
    - `id`: Key identifier
    - `name`: Key name
    - `scope`: Access scope
    - `is_active`: Whether the key is active
    - `created_at`: Creation timestamp
    - `expires_at`: Expiration timestamp (if applicable)
    
    **Important:** The `api_key` is only shown once during creation. Save it securely!
    
    **Error Responses:**
    - `400`: Invalid parameters
    - `500`: Server error during key creation
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


@app.get("/api-keys", tags=["API Keys"])
async def list_api_keys():
    """
    List all API keys (without the actual keys).
    
    Returns metadata about all API keys but not the keys themselves for security reasons.
    
    **Response:**
    - `api_keys`: Array of API key metadata objects
    - `total`: Total number of API keys
    
    **Each API Key Object Contains:**
    - `id`: Key identifier
    - `name`: Key name
    - `scope`: Access scope
    - `is_active`: Whether the key is active
    - `created_at`: Creation timestamp
    - `expires_at`: Expiration timestamp (if applicable)
    - `last_used_at`: Last usage timestamp
    - `created_by`: Who created the key
    
    **Security Note:** The actual API keys are never returned in list operations.
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


@app.delete("/api-keys/{key_id}", tags=["API Keys"])
async def delete_api_key(key_id: str):
    """
    Delete an API key permanently.
    
    **Parameters:**
    - `key_id`: The ID of the API key to delete (path parameter)
    
    **Response:**
    - `status`: "success"
    - `message`: Confirmation message
    
    **Error Responses:**
    - `404`: API key not found
    - `500`: Server error during deletion
    
    **Warning:** This action is irreversible. Consider deactivating instead if you might need the key later.
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


@app.post("/api-keys/{key_id}/deactivate", tags=["API Keys"])
async def deactivate_api_key(key_id: str):
    """
    Deactivate an API key without deleting it.
    
    **Parameters:**
    - `key_id`: The ID of the API key to deactivate (path parameter)
    
    **Response:**
    - `status`: "success"
    - `message`: Confirmation message
    
    **Error Responses:**
    - `404`: API key not found
    - `500`: Server error during deactivation
    
    **Note:** Deactivated keys can be reactivated later. Use this instead of delete if you might need the key again.
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


@app.post("/test-groq-analysis", tags=["Support"])
async def test_groq_analysis(request: Request):
    """
    Real Groq AI analysis endpoint using knowledge base.
    
    This endpoint uses actual Groq LLM with Qdrant knowledge base for intelligent customer support responses.
    
    **Request Body:**
    - `message` (required): Customer's message or question
    - `customer_id` (optional): Customer identifier (default: "gui_customer")
    - `customer_data` (optional): Customer information provided by frontend including:
      - `application` (recommended): The Shiva application the customer is using (e.g., "shiva_analytics", "shiva_crm", "shiva_erp", "shiva_payments", etc.)
      - `name`: Customer name
      - `email`: Customer email
      - `plan`: Subscription plan
      - Other customer-specific information
    - `conversation_history` (optional): Array of previous conversation messages
    - `stream` (optional): Enable streaming response (default: false)
    
    **Response:**
    - `response`: AI-generated response
    - `action`: Action taken (auto_resolve, queue, escalate, etc.)
    - `confidence`: AI confidence score (0.0 to 1.0)
    - `should_queue`: Whether a ticket should be created
    - `kb_context_used`: Whether knowledge base was used
    - `complexity_analysis`: Analysis of message complexity
    - `conversation_title`: AI-generated conversation title (3-8 words)

    **Streaming Response (when stream=true):**
    - Each chunk: `data: {"delta":"word"}`
    - Final chunk: `data: [DONE]`
    
    **Error Responses:**
    - `500`: AI processing failed
    
    **Use Cases:**
    - Customer support chat interface
    - Automated ticket triage
    - Knowledge base queries
    - Issue classification and routing
    
    **Example Request:**
    ```json
    {
      "message": "I need help with my dashboard",
      "customer_id": "cust_123",
      "customer_data": {
        "application": "shiva_analytics",
        "name": "John Doe",
        "email": "john@example.com",
        "plan": "enterprise"
      },
      "conversation_history": []
    }
    ```
    """
    try:
        from app.support_ai.service import SupportAIService
        from app.clients.qdrant_client import QdrantClient
        from app.clients.groq_client import GroqClient

        data = await request.json()
        message = data.get("message", "")
        conversation_history = data.get("conversation_history", [])
        customer_id = data.get("customer_id", "gui_customer")
        customer_data = data.get("customer_data", None)  # Customer data provided by frontend
        stream = data.get("stream", False)  # Streaming support

        # Check if streaming is requested
        if stream:
            # Return streaming response using inline function
            try:
                from app.support_ai.service import SupportAIService
                from app.clients.qdrant_client import QdrantClient
                from app.clients.groq_client import GroqClient
                from app.clients.gemini_client import GeminiClient
                from app.config import settings

                # Initialize the AI services
                qdrant_client = QdrantClient()
                groq_client = GroqClient()
                
                complex_task_client = None
                if settings.gemini_api_key:
                    try:
                        complex_task_client = GeminiClient()
                    except Exception as e:
                        logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))

                support_ai = SupportAIService(
                    qdrant_client=qdrant_client,
                    groq_client=groq_client,
                    complex_task_client=complex_task_client,
                )
                
                # Process the message with real AI
                result = await support_ai.handle_customer_message(
                    ticket_id="gui_session",
                    customer_id=customer_id,
                    message=message,
                    ticket_service=None,
                    is_agent_request=False,
                    conversation_history=conversation_history,
                    customer_data=customer_data,
                    product_context=data.get("product_context"),
                )
                
                # Extract the response details
                action = result.get("action", "auto_resolve")
                response_text = result.get("response")
                
                # Handle None response - convert to empty string with error message
                if response_text is None:
                    if result.get("error"):
                        response_text = f"I apologize, but I encountered an error: {result.get('error')}"
                    else:
                        response_text = "I apologize, but I encountered an error processing your request."
                elif not isinstance(response_text, str):
                    response_text = str(response_text)
                stream_text = response_text or ""
                
                confidence = result.get("confidence", 0.0)
                should_queue = result.get("should_queue", False)
                kb_context_used = result.get("kb_context_used", False)
                complexity_analysis = result.get("complexity_analysis")
                analysis = result.get("analysis", {"needs_ticket": should_queue})

                # Generate streaming response
                async def generate_stream():
                    # Stream the response text while preserving whitespace (including newlines)
                    # This ensures numbered steps and formatting are preserved
                    import re
                    
                    tokens = re.findall(r'\S+|\s+', stream_text)

                    for token in tokens:
                        chunk_data = {
                            "delta": token
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                        # Only delay on real words, not whitespace, to keep pacing natural
                        if token.strip():
                            await asyncio.sleep(0.02)

                    # Include the same structured metadata as the non-streaming response.
                    yield f"data: {json.dumps({'analysis': analysis, 'done': True})}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    generate_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )
                
            except Exception as e:
                logger.error("Streaming Groq analysis failed", error=str(e))
                # Return error as SSE
                async def error_stream():
                    error_data = {
                        "delta": f"Error: {str(e)}"
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    error_stream(),
                    media_type="text/event-stream",
                    status_code=500
                )

        # Initialize the AI services with real implementations
        qdrant_client = QdrantClient()
        groq_client = GroqClient()
        
        from app.clients.gemini_client import GeminiClient
        from app.config import settings
        
        complex_task_client = None
        if settings.gemini_api_key:
            try:
                complex_task_client = GeminiClient()
            except Exception as e:
                logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))

        support_ai = SupportAIService(
            qdrant_client=qdrant_client,
            groq_client=groq_client,
            complex_task_client=complex_task_client,
        )
        
        # Process the message with real AI
        result = await support_ai.handle_customer_message(
            ticket_id="gui_session",  # Use temporary ID for GUI session
            customer_id=customer_id,
            message=message,
            ticket_service=None,  # No ticket service for GUI chat
            is_agent_request=False,
            conversation_history=conversation_history,
            customer_data=customer_data,  # Customer data from frontend
            product_context=data.get("product_context"),
        )
        
        # Extract the response details
        action = result.get("action", "auto_resolve")
        response_text = result.get("response") or ""  # Ensure it's never None
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

        # Check for staff info requests - provide helpful info without creating tickets
        if action == "provide_staff_info":
            message_type = "staff_info"
            needs_ticket = False
            should_queue = False  # Ensure we don't create tickets for staff info requests
            logger.info("Staff info request detected - providing helpful information", message=message)

        # Check for ticket inquiry requests - gather issue info instead of creating tickets
        if action == "gather_issue_info":
            message_type = "ticket_inquiry"
            needs_ticket = False
            should_queue = False  # Ensure we don't create tickets for initial ticket inquiries
            logger.info("Ticket inquiry detected - gathering issue information first", message=message)

        # Check for details gathering requests - ask for more information instead of creating tickets
        if action == "gather_details":
            message_type = "details_inquiry"
            needs_ticket = False
            should_queue = False  # Ensure we don't create tickets when gathering details
            logger.info("Vague issue detected - gathering more details first", message=message)

        # Additional check: don't create tickets for simple greetings even if AI suggests queueing
        simple_greetings = {
            "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
            "thanks", "thank you", "bye", "goodbye",
        }
        is_simple_greeting = message.strip().lower() in simple_greetings

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
                    # Generate AI title for the ticket
                    try:
                        from app.clients.groq_client import GroqClient
                        groq_client = GroqClient()
                        ticket_title = await groq_client.generate_ticket_title(
                            message=message,
                            customer_data=customer_data,
                        )
                    except Exception as e:
                        logger.error("Failed to generate ticket title", error=str(e))
                        ticket_title = None

                    ticket = await ticket_service.create_ticket(
                        customer_id=customer_id,
                        initial_message=message,
                        path=TicketPath.SUPPORT,
                        title=ticket_title,
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
        
        # Use the appropriate response based on action
        if action == "provide_staff_info":
            final_response = result.get("response", response_text)
        elif action == "gather_issue_info":
            final_response = result.get("response", response_text)
        elif action == "gather_details":
            final_response = result.get("response", response_text)
        elif action == "out_of_scope":
            final_response = result.get("response", response_text)
        else:
            final_response = response_text

        # Return the persisted ticket ID in the customer-facing escalation response.
        if ticket_details and needs_ticket:
            ticket_id_text = str(ticket_details["id"])
            if ticket_id_text not in final_response:
                final_response = f"{final_response}\n\nTicket ID: `{ticket_id_text}`"

        return {
            "status": "success",
            "analysis": {
                "message_type": message_type,
                "response": final_response,
                "confidence": confidence,
                "needs_product_selection": result.get("needs_product_selection", False),
                "needs_ticket": needs_ticket,
                "escalation_reason": escalation_reason,
                "kb_context_used": kb_context_used,
                "action": action,
                "ticket": ticket_details,
                **result.get("analysis", {"needs_ticket": needs_ticket}),
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


@app.post("/suggest-ticket-title", tags=["Support"])
async def suggest_ticket_title(request: Request):
    """
    Generate AI-powered title suggestions for support tickets.

    This endpoint uses Groq AI to generate concise, descriptive titles
    based on the customer's message or issue description.

    **Request Body:**
    - `message` (required): Customer's message or issue description
    - `customer_data` (optional): Customer information for context

    **Response:**
    - `title`: Suggested ticket title (3-8 words)
    - `confidence`: AI confidence in the title (0.0 to 1.0)

    **Use Cases:**
    - Pre-fill ticket titles in the UI
    - Help customers summarize their issues
    - Improve ticket organization and searchability

    **Example Request:**
    ```json
    {
      "message": "I can't login to my account, it says invalid credentials",
      "customer_data": {
        "application": "shiva_crm",
        "name": "John Doe"
      }
    }
    ```

    **Example Response:**
    ```json
    {
      "title": "Account login credentials issue",
      "confidence": 0.9
    }
    ```
    """
    try:
        from app.clients.groq_client import GroqClient

        data = await request.json()
        message = data.get("message", "")
        customer_data = data.get("customer_data", None)

        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message is required"
            )

        # Generate title using Groq
        groq_client = GroqClient()
        title = await groq_client.generate_ticket_title(
            message=message,
            customer_data=customer_data,
        )

        return {
            "status": "success",
            "title": title,
            "confidence": 0.9,  # High confidence for title generation
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate ticket title suggestion", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate title: {str(e)}"
        )


@app.post("/chat-stream", tags=["Support"])
async def chat_stream(request: Request):
    """
    Streaming chat endpoint for real-time AI responses with real ticket creation.

    This endpoint streams AI responses token-by-token for a better user experience
    while properly creating and managing tickets through the full escalation pipeline.

    **Request Body:**
    - `message` (required): Customer's message or question
    - `customer_id` (required): Customer identifier
    - `customer_data` (optional): Customer information provided by frontend
    - `conversation_history` (optional): Array of previous conversation messages
    - `skip_ticket` (optional): If true, skip ticket creation (for preview/testing only)

    **Response:** Server-Sent Events (SSE) stream with JSON chunks:
    - Each chunk contains: `{"content": "token", "done": false}`
    - Final chunk: `{"content": "", "done": true, "action": "...", "confidence": 0.9, ...}`

    **Use Cases:**
    - Real-time chat interface
    - Typing effect for AI responses
    - Better perceived performance

    **Example Request:**
    ```json
    {
      "message": "I need help with my dashboard",
      "customer_id": "cust_123",
      "customer_data": {
        "application": "shiva_analytics",
        "name": "John Doe",
        "email": "john@example.com"
      },
      "conversation_history": []
    }
    ```
    """
    try:
        from app.support_ai.service import SupportAIService
        from app.clients.qdrant_client import QdrantClient
        from app.clients.groq_client import GroqClient
        from app.ticket_center.service import TicketCenterService
        from app.db.session import get_async_session

        data = await request.json()
        message = data.get("message", "")
        conversation_history = data.get("conversation_history", [])
        customer_id = data.get("customer_id", "gui_customer")
        customer_data = data.get("customer_data", None)
        skip_ticket = data.get("skip_ticket", False)
        product_context = data.get("product_context", None)

        # BUG FIX 1: Route through AIRouter before processing
        from app.ai_router.classifier import AIRouter
        from app.clients.qdrant_client import QdrantClient
        
        qdrant_client = QdrantClient()
        router = AIRouter(qdrant_client=qdrant_client)
        
        # Classify the message to determine which AI should handle it
        route_decision = await router.classify(
            message,
            [],
            conversation_history=conversation_history,
            customer_id=customer_id,
            customer_data=customer_data,
        )
        
        logger.info(
            "Chat stream routing decision",
            customer_id=customer_id,
            route=route_decision,
            message=message[:100],
        )

        # Initialize the appropriate AI service based on routing
        from app.clients.groq_client import GroqClient
        from app.ticket_center.service import TicketCenterService
        from app.db.session import get_async_session

        groq_client = GroqClient()
        
        # Route to appropriate AI based on classification
        if route_decision == "code":
            from app.code_ai.service import CodeAIService
            from app.clients.codex_client import CodexClient
            from app.code_ai.readers import FileLogReader, GitCodeReader
            
            code_ai = CodeAIService(
                groq_client=groq_client,
                codex_client=CodexClient(),
                file_reader=FileLogReader(),
                git_reader=GitCodeReader(),
            )
            
            # Code AI doesn't use tickets, so we stream directly
            async def generate_stream():
                try:
                    async for chunk in code_ai.analyze_with_stream(
                        query=message,
                        customer_data=customer_data,
                    ):
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                    # Final chunk with metadata
                    yield f"data: {json.dumps({'content': '', 'done': True, 'action': 'code_analysis', 'confidence': 0.9, 'needs_product_selection': False, 'needs_ticket': False})}\n\n"
                except Exception as e:
                    logger.error("Code AI streaming failed", error=str(e))
                    error_chunk = {
                        "content": "",
                        "done": True,
                        "error": str(e)
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
        
        # For "support" or "staff" routes, use Support AI with ticket handling
        from app.clients.gemini_client import GeminiClient
        from app.config import settings
        
        complex_task_client = None
        if settings.gemini_api_key:
            try:
                complex_task_client = GeminiClient()
            except Exception as e:
                logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))
        
        support_ai = SupportAIService(
            qdrant_client=qdrant_client,
            groq_client=groq_client,
            complex_task_client=complex_task_client,
        )

        # Determine ticket service
        ticket_service = None
        ticket_id = None

        if not skip_ticket:
            # Create real ticket service and ticket
            async for session in get_async_session():
                ticket_service = TicketCenterService(session)

                # Create or get existing ticket
                existing_ticket = await ticket_service.get_customer_ticket(customer_id)
                if existing_ticket:
                    ticket_id = existing_ticket.id
                else:
                    ticket = await ticket_service.create_ticket(
                        customer_id=customer_id,
                        initial_message=message,
                        path="support",
                    )
                    ticket_id = ticket.id

                # Process the message with real streaming
                async def generate_stream():
                    try:
                        async for chunk in support_ai.handle_customer_message_stream(
                            ticket_id=ticket_id,
                            customer_id=customer_id,
                            message=message,
                            ticket_service=ticket_service,
                            is_agent_request=False,
                            conversation_history=conversation_history,
                            customer_data=customer_data,
                            product_context=product_context,
                        ):
                            if chunk.get("done") and chunk.get("should_queue"):
                                from app.db.models import MessageSender, TicketStatus

                                ticket = await ticket_service.get_ticket(ticket_id)
                                if ticket and ticket.status != TicketStatus.PENDING_STAFF:
                                    ticket_messages = await ticket_service.get_ticket_messages(ticket_id)
                                    if not ticket_messages or ticket_messages[-1].content != message:
                                        await ticket_service.append_message(
                                            ticket_id,
                                            sender=MessageSender.CUSTOMER,
                                            content=message,
                                        )
                                        ticket_messages = await ticket_service.get_ticket_messages(ticket_id)

                                    reason = chunk.get("escalation_reason") or "Issue requires staff investigation"
                                    chat_summary = await support_ai.generate_chat_summary(
                                        ticket_id=ticket_id,
                                        conversation_history=ticket_messages,
                                        escalation_reason=reason,
                                    )
                                    await ticket_service.queue_for_staff(ticket_id, reason, chat_summary)
                                    await ticket_service.auto_assign_staff(ticket_id)
                                    await session.refresh(ticket)

                                chunk["ticket_id"] = ticket_id
                            yield f"data: {json.dumps(chunk)}\n\n"
                    except Exception as e:
                        logger.error("Streaming generation failed", error=str(e))
                        error_chunk = {
                            "content": "",
                            "done": True,
                            "error": str(e)
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"

                return StreamingResponse(
                    generate_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",  # Disable nginx buffering
                    }
                )
        else:
            # Skip ticket mode (for preview/testing)
            ticket_id = "preview_session"

            async def generate_stream():
                try:
                    async for chunk in support_ai.handle_customer_message_stream(
                        ticket_id=ticket_id,
                        customer_id=customer_id,
                        message=message,
                        ticket_service=None,  # No ticket service in preview mode
                        is_agent_request=False,
                        conversation_history=conversation_history,
                        customer_data=customer_data,
                        product_context=product_context,
                    ):
                        yield f"data: {json.dumps(chunk)}\n\n"
                except Exception as e:
                    logger.error("Streaming generation failed (preview mode)", error=str(e))
                    error_chunk = {
                        "content": "",
                        "done": True,
                        "error": str(e)
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

    except Exception as e:
        logger.error("Streaming chat failed", error=str(e))
        # Return error as SSE
        async def error_stream():
            error_data = {
                "content": "",
                "done": True,
                "error": str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            status_code=500
        )


# REST API endpoints for React frontend compatibility
@app.get("/api/v1/health", tags=["Conversations"])
async def api_v1_health():
    """Simple health check for React frontend API v1."""
    return {
        "status": "ok",
        "message": "API v1 is working",
        "timestamp": "2024-01-01T00:00:00Z"
    }

@app.post("/api/v1/conversations/{conversation_id}/ai/chat", tags=["Conversations"])
async def conversation_ai_chat(conversation_id: str, request: Request):
    """
    AI chat endpoint for conversations (React frontend compatibility).
    
    This endpoint provides REST API compatibility for the React frontend's
    conversation AI chat functionality. It uses Groq directly for responses
    and formats responses exactly like ChatGPT's API.
    
    **Parameters:**
    - `conversation_id`: The conversation/chat session ID (path parameter)
    
    **Request Body:**
    - `message` (required): The user's message
    - `customer_id` (optional): Customer identifier (default: "gui_customer")
    - `customer_data` (optional): Customer information provided by frontend
    - `attachments` (optional): Array of attachment IDs
    - `conversation_history` (optional): Array of previous messages for context
    
    **Response:**
    - ChatGPT-style response format with id, object, created, model, choices, usage
    
    **Error Responses:**
    - `400`: Invalid request
    - `500`: AI processing failed
    """
    try:
        from app.clients.groq_client import GroqClient, ChatMessage
        
        data = await request.json()
        message = data.get("message", "")
        customer_id = data.get("customer_id", "gui_customer")
        conversation_history = data.get("conversation_history", [])
        customer_data = data.get("customer_data", None)  # Customer data from frontend
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="message is required"
            )
        
        # Initialize Groq client
        groq_client = GroqClient()
        
        # Build message history for Groq
        messages = []
        
        # Add system message
        messages.append(ChatMessage(
            role="system",
            content="You are a helpful, conversational AI assistant for Shiva Softwares. Provide friendly, natural responses to customer inquiries. Be direct and solution-focused, avoid overly formal language, and communicate like a helpful human support agent. Get to the point quickly but be thorough when needed. Always think of alternative solutions and provide step-by-step guidance when possible. If you need more information to help, ask naturally for details like error messages, screenshots, or steps to reproduce the issue." + LANGUAGE_POLICY
        ))
        
        # Add conversation history if provided (ChatGPT format)
        if conversation_history:
            for hist_msg in conversation_history:
                # Handle both ChatGPT format and simple format
                if isinstance(hist_msg, dict):
                    # ChatGPT format: {"role": "user", "content": "..."}
                    role = hist_msg.get("role", "user")
                    content = hist_msg.get("content", "")
                else:
                    # Simple format: string or object with content
                    role = "user"
                    content = str(hist_msg) if not isinstance(hist_msg, dict) else hist_msg.get("content", "")
                
                # Skip empty messages
                if content and content.strip():
                    messages.append(ChatMessage(role=role, content=content))
        
        # Add current user message
        messages.append(ChatMessage(role="user", content=message))
        
        # Get response from Groq
        import time
        start_time = time.time()

        response = await groq_client.chat_completion(
            messages=messages,
            model=settings.groq_model,
            temperature=0.8,  # Higher temperature for more natural, conversational responses
        )
        
        # Enforce language policy
        response.content = enforce_language_policy(response.content, message)
        
        end_time = time.time()
        
        # Calculate token usage (estimated)
        prompt_tokens = len(message.split())
        completion_tokens = len(response.content.split())
        total_tokens = prompt_tokens + completion_tokens
        
        # Format response exactly like ChatGPT
        chat_response = {
            "id": f"chatcmpl-{conversation_id}",
            "object": "chat.completion",
            "created": int(start_time),
            "model": settings.groq_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response.content
                    },
                    "finish_reason": "stop",
                    "logprobs": None
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens
            },
            "system_fingerprint": "fp_" + str(int(start_time))[-8:]
        }
        
        # Add conversation history to response for context
        if conversation_history:
            chat_response["conversation_history"] = conversation_history
        
        return chat_response
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Conversation AI chat failed", error=str(e), conversation_id=conversation_id, exc_info=True)
        # ChatGPT-style error response
        import time
        return {
            "error": {
                "message": f"An error occurred: {str(e)}",
                "type": "invalid_request_error",
                "param": None,
                "code": "internal_error"
            }
        }


@app.get("/api/v1/conversations/{conversation_id}", tags=["Conversations"])
async def get_conversation(conversation_id: str):
    """
    Get conversation details (React frontend compatibility).
    
    **Parameters:**
    - `conversation_id`: The conversation/chat session ID (path parameter)
    
    **Response:**
    - `id`: Conversation ID
    - `customer_id`: Customer ID
    - `status`: Conversation status
    - `messages`: Array of messages
    - `created_at`: Creation timestamp
    - `updated_at`: Last update timestamp
    
    **Error Responses:**
    - `404`: Conversation not found
    - `500`: Server error
    """
    try:
        async with get_db_context() as session:
            chat_service = ChatCenterService(session)
            chat_session = await chat_service.get_chat_session(conversation_id)
            
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found"
                )
            
            messages = await chat_service.get_chat_messages(conversation_id)
            
            return {
                "id": chat_session.id,
                "customer_id": chat_session.customer_id,
                "status": chat_session.status.value,
                "ticket_id": chat_session.ticket_id,
                "ai_attempts": chat_session.ai_attempts,
                "created_at": chat_session.created_at.isoformat(),
                "updated_at": chat_session.updated_at.isoformat(),
                "messages": [
                    {
                        "id": msg.id,
                        "sender": msg.sender.value,
                        "content": msg.content,
                        "attachments": msg.attachments,
                        "created_at": msg.created_at.isoformat(),
                    }
                    for msg in messages
                ]
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get conversation", error=str(e), conversation_id=conversation_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation: {str(e)}"
        )


@app.get("/api/v1/notifications/me/stream", tags=["Notifications"])
async def stream_notifications(request: Request):
    """
    Stream notifications for the current user (React frontend compatibility).
    
    This endpoint provides Server-Sent Events (SSE) streaming for real-time notifications.
    
    **Response:**
    - SSE stream with notification events
    
    **Error Responses:**
    - `500`: Streaming failed
    """
    import asyncio
    import json
    
    async def event_generator():
        """Generate notification events."""
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                # In a real implementation, you would:
                # 1. Check database for new notifications
                # 2. Send them as SSE events
                # 3. Use proper notification system
                
                # For now, send keepalive to keep connection open
                yield ": keepalive\n\n"
                
                # Wait before next check
                await asyncio.sleep(15)
                
        except asyncio.CancelledError:
            logger.info("Notification stream cancelled by client")
        except Exception as e:
            logger.error("Notification stream error", error=str(e))
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


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
