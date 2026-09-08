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

3. **Fallback**: If neither step 1 nor step 2 fires → Route to **Staff Queue**

## Ticket State Machine

Ticket statuses and valid transitions:

- `OPEN` → `IN_PROGRESS`, `PENDING_STAFF`, `RESOLVED_AUTO`, `CLOSED`
- `IN_PROGRESS` → `PENDING_STAFF`, `PENDING_CUSTOMER`, `RESOLVED_AUTO`, `CLOSED`
- `PENDING_STAFF` → `IN_PROGRESS`, `CLOSED`
- `PENDING_CUSTOMER` → `IN_PROGRESS`, `RESOLVED_AUTO`, `CLOSED`
- `RESOLVED_AUTO` → `OPEN` (reopen), `CLOSED`
- `CLOSED` → `OPEN` (reopen)

**Important Rules**:
- Only staff or developers can close tickets
- One open ticket per customer (enforced at DB level)
- All status changes go through Ticket Center service methods

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

## License

[Your License Here]

## Support

For issues and questions, please contact the development team or create an issue in the repository.
