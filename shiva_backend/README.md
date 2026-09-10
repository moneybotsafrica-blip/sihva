# Shiva AI Support Platform - Backend

Backend system for the Shiva AI Support Platform with AI-powered ticket routing, Support AI (RAG), and Code/Server AI capabilities.

## Architecture Overview

The backend implements a sophisticated AI-driven support system with the following components:

- **AI Router**: Classifies incoming messages to route to Support AI, Code/Server AI, or staff queue
- **Support AI**: Uses RAG (Retrieval-Augmented Generation) with Qdrant vector DB and Groq LLM for knowledge-based responses
- **Code/Server AI**: Analyzes technical issues using Codex for code reasoning and fix recommendations
- **Ticket Center**: Core state machine managing tickets, messages, and fix recommendations
- **GraphQL API**: Single `/graphql` endpoint for all API operations
- **API Gateway**: Authentication, rate limiting, and request routing

## Technology Stack

- **Framework**: FastAPI (ASGI) with Strawberry GraphQL
- **Database**: PostgreSQL with SQLAlchemy (async) and Alembic migrations
- **Vector DB**: Qdrant for knowledge base embeddings
- **LLM**: Groq for Support AI responses
- **Code AI**: Codex (or equivalent) for code analysis
- **External APIs**: Customer API (abstracted via adapter pattern)
- **Testing**: pytest with async support
- **Configuration**: Pydantic Settings with environment variables

## Project Structure

```
shiva_backend/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Pydantic settings and configuration
│   ├── db/                     # Database models and sessions
│   │   ├── models.py           # SQLAlchemy models (Ticket, TicketMessage, FixRecommendation)
│   │   ├── session.py          # Async session management
│   │   └── migrations/         # Alembic database migrations
│   ├── ticket_center/          # Core ticket management service
│   │   └── service.py          # Ticket state machine and business logic
│   ├── ai_router/              # AI classification and routing
│   │   └── classifier.py       # Message classification logic
│   ├── support_ai/             # Support AI with RAG
│   │   └── service.py          # Qdrant + Groq integration
│   ├── code_ai/                # Code/Server AI for technical issues
│   │   ├── service.py          # Codex integration
│   │   └── readers.py          # Log and code reader interfaces
│   ├── graphql/                # GraphQL API layer
│   │   ├── schema.py           # Strawberry schema
│   │   ├── types.py            # GraphQL type definitions
│   │   ├── queries.py          # Query resolvers
│   │   ├── mutations.py        # Mutation resolvers
│   │   └── subscriptions.py    # Subscription resolvers
│   ├── gateway/                # API Gateway layer
│   │   ├── auth.py             # Authentication context and JWT handling
│   │   └── rate_limit.py       # Rate limiting middleware
│   └── clients/                # External API clients
│       ├── customer_api.py     # Customer API adapter
│       ├── qdrant_client.py    # Qdrant vector DB client
│       ├── groq_client.py      # Groq LLM client
│       └── codex_client.py     # Codex code reasoning client
├── tests/                      # Test suite
│   ├── conftest.py             # Pytest fixtures
│   ├── test_ai_router.py       # AI Router tests
│   ├── test_ticket_center.py   # Ticket Center tests
│   ├── test_graphql_mutations.py # GraphQL tests
│   └── test_integration.py     # Integration tests
├── pyproject.toml              # Project dependencies
├── alembic.ini                 # Alembic configuration
└── .env.example                # Environment variables template
```

## Setup Instructions

### Prerequisites

- Python 3.11+
- PostgreSQL 12+ (required - this system uses PostgreSQL as the primary database)
- Qdrant Vector Database (optional for development, can use mock)
- Groq API key (optional for development, can use mock)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd shiva_backend
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Set up PostgreSQL database**:

   **Option A: Automated setup (recommended)**
   ```bash
   python scripts/setup_postgres.py
   ```

   **Option B: Manual setup**
   ```bash
   # Create database
   createdb shiva_support

   # Run migrations
   alembic upgrade head
   ```

6. **Set up Qdrant (optional for production)**:
   ```bash
   # Using Docker
   docker run -p 6333:6333 qdrant/qdrant
   ```

### Environment Variables

Key environment variables (see `.env.example` for complete list):

```bash
# Database (PostgreSQL required)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/shiva_support

# PostgreSQL Connection Pool Settings
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE=3600

# Customer API
CUSTOMER_API_KEY=your_api_key
CUSTOMER_API_BASE_URL=https://api.customer.example.com

# Qdrant (Vector DB)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=knowledge_base
QDRANT_SIMILARITY_THRESHOLD=0.75

# Groq (LLM)
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama2-70b-4096

# Codex (Code AI)
CODEX_API_KEY=your_codex_api_key
CODEX_MODEL=gpt-4-codex

# Authentication
JWT_SECRET_KEY=your_jwt_secret
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60

# Rate Limiting
RATE_LIMIT_PER_CUSTOMER=100
RATE_LIMIT_PER_IP=50
RATE_LIMIT_WINDOW_SECONDS=60

# AI Configuration
SUPPORT_AI_CONFIDENCE_THRESHOLD=0.8
CODE_AI_ENABLED=true
```

## Running the Application

### Development Mode

```bash
# Run with auto-reload
python -m app.main
```

The server will start on `http://localhost:8000`

### Production Mode

```bash
# Using uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Available Endpoints

- **GraphQL API**: `POST /graphql`
- **Health Check**: `GET /healthz`
- **File Upload**: `POST /upload`
- **Attachment Info**: `GET /attachments/{attachment_id}`

## API Usage

### GraphQL API

The main API endpoint is a single GraphQL schema with role-based access control.

#### Customer Operations

**Send Message**:
```graphql
mutation SendMessage($input: SendMessageInput!) {
  sendMessage(input: $input) {
    id
    status
    messages {
      content
      sender
    }
  }
}
```

**Get My Ticket**:
```graphql
query {
  myTicket {
    id
    status
    messages {
      content
      sender
      createdAt
    }
  }
}
```

#### Staff Operations

**List Tickets**:
```graphql
query {
  tickets(status: PENDING_STAFF, assignedTo: "staff_123") {
    id
    customerId
    status
    messages {
      content
      sender
    }
  }
}
```

**Assign Ticket**:
```graphql
mutation AssignTicket($input: AssignTicketInput!) {
  assignTicket(input: $input) {
    id
    assignedStaffId
  }
}
```

**Reply to Ticket**:
```graphql
mutation ReplyToTicket($input: ReplyToTicketInput!) {
  replyToTicket(input: $input) {
    id
    content
    sender
  }
}
```

**Review Fix**:
```graphql
mutation ApproveFix($input: ReviewFixInput!) {
  approveFix(input: $input) {
    id
    status
    reviewedBy
  }
}
```

**Close Ticket**:
```graphql
mutation CloseTicket($input: CloseTicketInput!) {
  closeTicket(input: $input) {
    id
    status
  }
}
```

### File Upload

Upload attachments via REST endpoint (GraphQL doesn't handle multipart uploads well):

```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@error.log" \
  -H "Authorization: Bearer <token>"
```

Returns:
```json
{
  "attachment_id": "uuid",
  "filename": "error.log",
  "size_bytes": 1024,
  "content_type": "text/plain"
}
```

Use the `attachment_id` in GraphQL mutations.

## Testing

### Run All Tests

```bash
# Default: Uses SQLite in-memory database (fast)
pytest

# PostgreSQL testing: Uses actual PostgreSQL database
TEST_USE_POSTGRES=true pytest
```

### Set up PostgreSQL Test Database

```bash
# Create test database for PostgreSQL testing
python scripts/create_test_db.py

# Then run tests with PostgreSQL
TEST_USE_POSTGRES=true pytest
```

### Run Specific Test Files

```bash
pytest tests/test_ai_router.py
pytest tests/test_ticket_center.py
pytest tests/test_integration.py
```

### Run with Coverage

```bash
pytest --cov=app --cov-report=html
```

### Test Structure

- **Unit Tests**: Individual component testing (AI Router, Ticket Center)
- **Integration Tests**: End-to-end flow testing
- **Mock Clients**: All external APIs have mock implementations for testing
- **Database Options**: SQLite (fast) or PostgreSQL (realistic) for testing

## Database Migrations

### Create New Migration

```bash
alembic revision --autogenerate -m "description"
```

### Apply Migrations

```bash
alembic upgrade head
```

### Rollback Migration

```bash
alembic downgrade -1
```

## AI Router Decision Flow

The AI Router follows this exact decision order:

1. **Technical Signal Check**: Does the message contain HTTP error codes, stack traces, technical trigger phrases, or technical attachments?
   - If yes → Route to **Code/Server AI**

2. **Knowledge Base Check**: Run Qdrant vector search against the knowledge base
   - If confident match (similarity ≥ threshold) → Route to **Support AI**

3. **Escalation Decision**: Support AI uses structured LLM decisions to determine if escalation is needed
   - **Explicit agent request**: Always escalates immediately (bypasses all gating)
   - **Structured escalation decision**: Groq LLM returns `{escalate: bool, reason: str, confidence: float}`
   - **AI attempts cap**: After 5 AI attempts, forces escalation regardless of confidence
   - **Critical issues**: Security, legal, unauthorized charges always escalate
   - **Failed solutions**: Customer reports previous AI fix didn't work → escalate
   - **Novel issues**: Calm but undocumented complex issues still escalate

4. **Fallback**: If neither step 1 nor step 2 fires → Route to **Staff Queue**

### Escalation Reliability

The escalation system is designed to ensure customers never get dropped:

- **Structured decisions**: Escalation uses structured LLM output, not phrase-matching in natural language
- **Explicit human requests**: `is_agent_request=True` bypasses all gating and escalates directly
- **AI attempts cap**: Maximum 5 AI-only turns per ticket before forced escalation
- **Reason propagation**: Actual escalation reasons are carried through to staff queueing and chat summaries
- **No silent drops**: All escalation paths log the specific rule/reason that fired
- **Golden regression set**: Five critical scenarios tested continuously:
  1. Explicit human-agent request on first turn
  2. Kiswahili escalation
  3. Security/legal keyword issue
  4. Customer says previous AI fix did not work
  5. Calm, novel, undocumented issue with no frustration language

## Customer/Staff Content Separation

The system implements strict separation between customer-facing and staff-facing content to ensure appropriate information exposure:

### Escalation Path: Status Message vs. AI Solution

When a ticket is escalated to staff, customers and staff see different content:

- **Customer view**: Receives a simple status message indicating the ticket has been escalated to a specialist
  - Example: "I've escalated your issue to our support specialists who can help investigate this further."
  - No technical details, no AI's attempted solutions

- **Staff view**: Sees the full AI suggested resolution with technical details
  - AI's complete diagnosis and solution attempt
  - Confidence score and escalation reason
  - Metadata on KB matches and agent type used
  - Enables staff to understand what AI tried before taking over

### AI Suggested Resolution

The `AISuggestedResolution` model stores AI-generated solutions as staff-only artifacts:

- **Fields**:
  - `suggested_solution`: The full AI-generated technical solution
  - `confidence`: AI's confidence score in the solution
  - `escalation_reason`: Specific reason for escalation
  - `status`: PENDING, REVIEWED, USED, DISMISSED, NEEDS_INFO
  - `reviewed_by`, `reviewed_at`, `notes`: Staff review metadata

- **Creation timing**: Created automatically when:
  - Structured escalation decision returns `escalate=True`
  - AI attempts cap is reached
  - Conservative fallback rules trigger escalation

- **Storage**: Stored in database as a separate entity linked to the ticket
- **Access**: Only exposed via GraphQL to staff and developer roles

### Auto-Resolve Path: Unaffected

When tickets are auto-resolved (AI can confidently solve the issue):
- **Customer view**: Receives the full AI response with actual solution
- **Staff view**: No AI suggested resolution is created (only for escalation)
- **Behavior**: Same as before - customers get real answers to solvable issues

### Role-Based Access Control

GraphQL schema enforces role-based field exposure:

- **Customer role**: Cannot see `ai_suggested_resolution`, `chat_summary`, `staff_notes`, or AI metadata fields
- **Staff role**: Can see all internal fields including AI suggested resolution
- **Developer role**: Same access as staff role

Field filtering is implemented in `ticket_to_graphql()` converter based on `user_role` parameter.

### Testing Coverage

Comprehensive tests ensure separation works correctly:

- `test_escalation_customer_sees_status_message`: Customer gets status, not technical solution
- `test_auto_resolve_customer_gets_real_answer`: Auto-resolve path unaffected
- `test_customer_cannot_see_ai_suggested_resolution`: GraphQL role filtering for customers
- `test_staff_can_see_ai_suggested_resolution`: Staff can access AI solutions
- `test_developer_can_see_ai_suggested_resolution`: Developer access to AI solutions

## Ticket State Machine

Ticket statuses and valid transitions:

- `OPEN` → `IN_PROGRESS`, `PENDING_STAFF`, `RESOLVED_AUTO`, `CLOSED`
- `IN_PROGRESS` → `PENDING_STAFF`, `PENDING_CUSTOMER`, `RESOLVED_AUTO`, `CLOSED`
- `PENDING_STAFF` → `IN_PROGRESS`, `CLOSED`
- `PENDING_CUSTOMER` → `IN_PROGRESS`, `RESOLVED_AUTO`, `CLOSED`
- `RESOLVED_AUTO` → `OPEN` (reopen), `CLOSED`
- `CLOSED` → `OPEN` (reopen)

**Important Rules**:
- **Customer self-close policy**: Customers can only close tickets that are `RESOLVED_AUTO` (confirming an AI fix worked). They cannot close `OPEN`, `PENDING_STAFF`, or `IN_PROGRESS` tickets.
- **Staff/developer close**: Staff and developers can close any ticket
- **One open ticket per customer**: Enforced at DB level
- **All status changes**: Go through Ticket Center service methods
- **AI attempts cap**: Maximum 5 AI-only turns per ticket before forced escalation to staff

## Deployment

### Docker Deployment

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install -e ".[dev]"

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t shiva-backend .
docker run -p 8000:8000 --env-file .env shiva-backend
```

### Production Considerations

1. **Database**: Use managed PostgreSQL service (RDS, Cloud SQL, etc.)
2. **Qdrant**: Use managed Qdrant Cloud or self-hosted with persistence
3. **Rate Limiting**: Replace in-memory storage with Redis
4. **Secrets**: Use proper secret management (AWS Secrets Manager, HashiCorp Vault)
5. **Monitoring**: Add structured logging and metrics (Prometheus, Grafana)
6. **SSL/TLS**: Use reverse proxy (nginx, Traefik) for HTTPS

## Troubleshooting

### Database Connection Issues

- Verify PostgreSQL is running: `pg_isready`
- Check connection string in `.env`
- Ensure database exists: `createdb shiva_support`

### Qdrant Connection Issues

- Verify Qdrant is running: `curl http://localhost:6333/`
- Check Qdrant URL in `.env`
- For development, you can use mock clients

### Import Errors

- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -e ".[dev]"`
- Check Python version: `python --version` (should be 3.11+)

## Development Guidelines

### Code Style

- Line length: 100 characters
- Use `black` for formatting: `black app/ tests/`
- Use `ruff` for linting: `ruff check app/ tests/`
- Type hints required for all functions

### Testing Guidelines

- Write unit tests for all business logic
- Use mock clients for external API calls
- Test all three AI Router decision branches
- Test ticket state machine transitions
- Test role-based access control

### Adding New Features

1. Update database models if needed
2. Create migration: `alembic revision --autogenerate`
3. Implement business logic in appropriate service
4. Add GraphQL types and resolvers
5. Write comprehensive tests
6. Update documentation

## AI Behavior Guidelines

### Honesty and Calibration

All AI agents (Support AI, Staff AI) follow strict honesty and calibration rules:

- **No false claims**: Never claim to have completed an action unless confirmed by actual tool/system call
- **No overpromising**: Never promise specific staff members, response times, or guaranteed outcomes
- **Clear distinctions**: Distinguish between what AI CAN do (provide information, give instructions) vs what it CANNOT do (modify accounts, process refunds)
- **Probabilistic language**: Use "should help" or "try this" instead of "will fix it" when uncertain
- **Admit uncertainty**: If unsure, admit it and suggest escalation rather than guessing

### Verification and Clarification

- **Ask before assuming**: For ambiguous issues, ask ONE targeted clarification question before providing solutions
- **Verify resolution**: After providing a solution, always ask the customer to confirm it worked
- **Targeted questions**: Ask for specific details when needed (error messages, current step, account-specific info)
- **No guessing**: Don't provide solutions based on assumptions about the customer's situation

### Staff Handoff Quality

When escalating to staff, the system provides comprehensive context:

- **What was tried**: AI attempts and solutions attempted
- **What failed**: Customer feedback on why solutions didn't work
- **Escalation reason**: Specific reason for escalation (not generic)
- **Customer urgency/sentiment**: Detected frustration or calm tone
- **Full context**: Enough information for staff to avoid rereading the entire thread

## License

[Your License Here]

## Support

For issues and questions, please contact the development team or create an issue in the repository.
