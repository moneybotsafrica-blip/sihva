# Swagger API Documentation Setup

## Overview

The Shiva AI Support Platform now includes comprehensive Swagger/OpenAPI documentation for all API endpoints.

## Access Documentation

### Swagger UI (Interactive)
- **URL:** `http://localhost:8000/docs`
- **Features:** Interactive API testing, request/response examples, authentication

### ReDoc (Alternative Documentation)
- **URL:** `http://localhost:8000/redoc`
- **Features:** Clean, readable documentation layout

### OpenAPI Schema
- **URL:** `http://localhost:8000/openapi.json`
- **Features:** Raw OpenAPI specification for code generation

## Start Server with Documentation

### Option 1: Using the start script
```bash
py start_server.py
```

### Option 2: Direct uvicorn command
```bash
cd shiva_backend
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Documentation Features

### Enhanced API Information
- **Title:** Shiva AI Support Platform API
- **Version:** 1.0.0
- **Description:** Comprehensive AI-powered customer support system documentation
- **Contact:** support@shiva.com
- **License:** MIT

### Security Schemes
Two authentication methods are documented:

1. **API Key Authentication**
   - Type: API Key
   - Location: Header
   - Format: `Authorization: Bearer YOUR_API_KEY`

2. **JWT Authentication**
   - Type: HTTP Bearer
   - Format: `Authorization: Bearer YOUR_JWT_TOKEN`

### API Tags
Endpoints are organized by category:
- **Health:** System health and status endpoints
- **Support:** AI-powered support endpoints
- **GraphQL:** GraphQL API endpoints
- **API Keys:** API key management
- **Uploads:** File upload and attachment management
- **Mock Data:** Database seeding and testing

### Server Configurations
Multiple server environments are documented:
- Development: `http://localhost:8000`
- Local Network: `http://10.61.20.203:8000`
- Production: `https://api.shiva.com`

## Documented Endpoints

### Health Endpoints
- `GET /healthz` - Health check endpoint

### Support Endpoints
- `POST /test-groq-analysis` - AI-powered support analysis

### GraphQL Endpoints
- `POST /graphql` - GraphQL API endpoint

### API Key Management
- `POST /api-keys` - Create new API key
- `GET /api-keys` - List all API keys
- `DELETE /api-keys/{key_id}` - Delete API key
- `POST /api-keys/{key_id}/deactivate` - Deactivate API key

### Upload Endpoints
- `POST /upload` - Upload file attachments
- `GET /attachments/{attachment_id}` - Get attachment metadata

### Mock Data Endpoints
- `POST /mock/seed-database` - Seed database with test data
- `POST /mock/clear-database` - Clear all test data
- `GET /mock/data-info` - Get mock data information

## Using Swagger UI

### 1. Authentication
Click the "Authorize" button at the top right:
- Enter your API key: `shiva_pT_URqGwppCSxrlkKoM84yDphiN0YEUmwL3LgWsbc2U`
- Click "Authorize"

### 2. Test Endpoints
- Click on any endpoint to expand details
- Click "Try it out"
- Fill in required parameters
- Click "Execute" to test

### 3. View Schemas
- Request/response schemas are automatically generated
- Click on schema links to see data models
- Examples are provided for complex objects

## Authentication in Swagger

To test authenticated endpoints in Swagger UI:

1. Click the "Authorize" button (🔒)
2. Enter: `Bearer shiva_pT_URqGwppCSxrlkKoM84yDphiN0YEUmwL3LgWsbc2U`
3. Click "Authorize"
4. All subsequent requests will include the authentication header

## Example API Call in Swagger

### Create API Key
1. Navigate to `POST /api-keys`
2. Click "Try it out"
3. Enter request body:
```json
{
  "name": "Test App",
  "scope": "frontend",
  "expires_in_days": 365
}
```
4. Click "Execute"
5. View the response with your new API key

### Send Support Message
1. Navigate to `POST /test-groq-analysis`
2. Click "Try it out"
3. Enter request body:
```json
{
  "message": "I need help with my account",
  "customer_id": "customer_123",
  "conversation_history": []
}
```
4. Click "Execute"
5. View the AI response

## Code Generation

The OpenAPI schema can be used to generate client SDKs:

### Using OpenAPI Generator
```bash
# Generate JavaScript client
openapi-generator-cli generate -i http://localhost:8000/openapi.json -g javascript -o ./client-js

# Generate Python client
openapi-generator-cli generate -i http://localhost:8000/openapi.json -g python -o ./client-python

# Generate React components
openapi-generator-cli generate -i http://localhost:8000/openapi.json -g typescript-axios -o ./client-react
```

## Customization

The Swagger documentation can be customized in `app/main.py`:

```python
# Modify the custom_openapi() function to:
# - Add more server configurations
# - Update contact information
# - Add custom tags
# - Modify security schemes
# - Add additional metadata
```

## Benefits

1. **Interactive Testing:** Test all endpoints directly from the browser
2. **Auto-Generated:** Documentation stays in sync with code
3. **Standard Format:** OpenAPI 3.0 specification
4. **Client Generation:** Generate SDKs for any language
5. **Team Collaboration:** Share API documentation with frontend developers
6. **Authentication Testing:** Easily test authenticated endpoints

## Troubleshooting

### Swagger UI not loading
- Ensure the server is running on port 8000
- Check firewall settings
- Verify CORS configuration

### Authentication not working
- Ensure API key is correct
- Check Authorization header format: `Bearer YOUR_KEY`
- Verify API key is active in database

### Schemas not showing
- Restart the server after code changes
- Check that Pydantic models are properly defined
- Verify imports are correct

## Next Steps

1. Start the server: `py start_server.py`
2. Open browser to: `http://localhost:8000/docs`
3. Authorize with your API key
4. Test the endpoints
5. Share the documentation URL with your team

The Swagger documentation provides a complete, interactive API reference that will help your frontend team integrate with the Shiva backend efficiently.