# API Key Authentication Setup Guide

## Overview

The Shiva AI Support Platform now supports API key authentication for frontend applications and external systems. This allows your frontend to securely authenticate with the backend without requiring user login sessions.

## API Key Management Endpoints

### 1. Create API Key

**Endpoint:** `POST /api-keys`

**Request Body:**
```json
{
  "name": "Frontend Application",
  "scope": "frontend",
  "expires_in_days": 365
}
```

**Parameters:**
- `name` (required): Human-readable name for the key (e.g., "Frontend App", "Mobile App")
- `scope` (optional): Access scope - "frontend" (default), "internal", or "admin"
- `expires_in_days` (optional): Expiration time in days (null = never expires)

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "api-key-id",
    "api_key": "shiva_YourSecretKeyHere",
    "name": "Frontend Application",
    "scope": "frontend",
    "is_active": true,
    "created_at": "2026-09-08T11:28:25.670655",
    "expires_at": "2027-09-08T11:28:25.670655",
    "created_by": "system"
  },
  "warning": "Save this API key securely. It will not be shown again."
}
```

**Important:** The `api_key` is only shown once during creation. Save it securely!

### 2. List API Keys

**Endpoint:** `GET /api-keys`

**Response:**
```json
{
  "status": "success",
  "data": {
    "api_keys": [
      {
        "id": "api-key-id",
        "name": "Frontend Application",
        "scope": "frontend",
        "is_active": true,
        "created_at": "2026-09-08T11:28:25.670655",
        "expires_at": "2027-09-08T11:28:25.670655",
        "last_used_at": "2026-09-08T11:30:00.000000",
        "created_by": "system"
      }
    ],
    "total": 1
  }
}
```

**Note:** The actual API keys are never returned in list operations for security.

### 3. Deactivate API Key

**Endpoint:** `POST /api-keys/{key_id}/deactivate`

**Response:**
```json
{
  "status": "success",
  "message": "API key deactivated successfully"
}
```

### 4. Delete API Key

**Endpoint:** `DELETE /api-keys/{key_id}`

**Response:**
```json
{
  "status": "success",
  "message": "API key deleted successfully"
}
```

## Using API Keys in Your Frontend

### Authentication Header

To use an API key for authentication, include it in the `Authorization` header with the `Bearer` prefix:

```
Authorization: Bearer shiva_YourSecretKeyHere
```

### Example Requests

#### Send Message with API Key

```javascript
const response = await fetch('http://localhost:8000/test-groq-analysis', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer shiva_YourSecretKeyHere',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    message: "I'm having trouble logging in",
    customer_id: "customer_123",
    conversation_history: []
  })
});

const data = await response.json();
console.log(data);
```

#### GraphQL Query with API Key

```javascript
const response = await fetch('http://localhost:8000/graphql', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer shiva_YourSecretKeyHere',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    query: `
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
    `
  })
});

const data = await response.json();
console.log(data);
```

## API Key Scopes

### Frontend Scope
- **Purpose:** For frontend applications and public-facing integrations
- **Access:** Customer-facing operations, ticket creation, message sending
- **Use Case:** Web apps, mobile apps, customer portals

### Internal Scope
- **Purpose:** For internal services and microservices
- **Access:** Extended operations, internal tools, dashboards
- **Use Case:** Admin panels, internal monitoring, service-to-service communication

### Admin Scope
- **Purpose:** For administrative operations
- **Access:** Full system access including user management, configuration
- **Use Case:** System administration, emergency access, full API access

## Security Best Practices

1. **Store API Keys Securely**
   - Never commit API keys to version control
   - Use environment variables or secure secret management
   - Rotate keys periodically

2. **Use Appropriate Scopes**
   - Use the most restrictive scope necessary
   - Separate keys for different environments (dev, staging, production)

3. **Monitor Usage**
   - Check `last_used_at` timestamps to identify inactive keys
   - Set expiration dates for temporary access
   - Deactivate unused keys

4. **Key Rotation**
   - Create new keys before deactivating old ones
   - Update your frontend application with new keys
   - Verify new keys work before deactivating old ones

## Current API Keys

The system currently has API keys available for frontend integration. To get your API key:

1. **Create a new key:**
   ```bash
   curl -X POST http://localhost:8000/api-keys \
     -H "Content-Type: application/json" \
     -d '{"name": "My Frontend App", "scope": "frontend", "expires_in_days": 365}'
   ```

2. **Save the returned `api_key` securely**

3. **Use it in your frontend requests**

## Example Implementation

### React/Frontend Example

```javascript
// api-config.js
const API_CONFIG = {
  baseUrl: 'http://localhost:8000',
  apiKey: process.env.REACT_APP_API_KEY || 'your-api-key-here'
};

// api-client.js
class ApiClient {
  async sendMessage(message, customerId, conversationHistory = []) {
    const response = await fetch(`${API_CONFIG.baseUrl}/test-groq-analysis`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${API_CONFIG.apiKey}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message,
        customer_id: customerId,
        conversation_history: conversationHistory
      })
    });
    
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`);
    }
    
    return response.json();
  }
}

export default new ApiClient();
```

### Environment Variable Setup

```bash
# .env file
REACT_APP_API_KEY=shiva_YourSecretKeyHere
REACT_APP_API_URL=http://localhost:8000
```

## Troubleshooting

### Authentication Fails
- Verify the API key is correct
- Check that the key is active (`is_active: true`)
- Ensure the key hasn't expired
- Confirm the Authorization header format: `Bearer shiva_...`

### Key Not Working
- List keys to check status: `GET /api-keys`
- Verify scope permissions for the requested operation
- Check server logs for specific error messages

### Development Mode
- In development, invalid keys fall back to mock user authentication
- Production mode will reject invalid API keys
- Ensure you're using the correct environment configuration

## Support

For issues with API key authentication:
1. Check the server logs for error messages
2. Verify your API key status using the list endpoint
3. Ensure your frontend is sending the correct Authorization header
4. Contact the development team if issues persist