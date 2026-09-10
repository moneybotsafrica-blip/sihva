# Qdrant Local Setup Guide

This guide explains how to set up and run Qdrant locally for vector search on your knowledge base.

## Prerequisites

- Windows operating system
- PowerShell (included with Windows)
- Internet connection for initial download

## Setup Instructions

### 1. Run the Setup Script

Open PowerShell as Administrator and run:

```powershell
cd C:\Users\Bots\Documents\shivasupport\shiva_backend
.\setup_qdrant_local.ps1
```

This will:
- Create `C:\qdrant` directory
- Download Qdrant binary (v1.18.3)
- Extract and set up the executable
- Create startup script at `C:\qdrant\start_qdrant.bat`

### 2. Start Qdrant

Start Qdrant by running:

```cmd
C:\qdrant\start_qdrant.bat
```

Or manually:

```cmd
cd C:\qdrant
qdrant.exe --storage-path ./storage --log-level INFO
```

### 3. Verify Qdrant is Running

Once started, Qdrant will be available at:
- **API**: http://localhost:6333
- **Dashboard**: http://localhost:6333/dashboard

You should see logs indicating Qdrant is running successfully.

### 4. Install Embedding Model Dependencies

For vector search to work properly, install the sentence-transformers package:

```cmd
cd C:\Users\Bots\Documents\shivasupport\shiva_backend
pip install sentence-transformers
```

This provides the `all-MiniLM-L6-v2` model for generating text embeddings.

## Configuration

Your application is already configured to use local Qdrant:

- **URL**: `http://localhost:6333`
- **Collection**: `knowledge_base`
- **Vector Dimensions**: 384 (for all-MiniLM-L6-v2 model)

## Testing the Setup

1. Start your application:
```cmd
cd C:\Users\Bots\Documents\shivasupport\shiva_backend
py -B -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. Test the `/test-groq-analysis` endpoint with a message

3. Check the logs - you should see:
   - Successful Qdrant connection
   - Embedding generation (no placeholder warnings)
   - Knowledge base search results

## Troubleshooting

### Qdrant won't start
- Check if port 6333 is already in use
- Try running PowerShell as Administrator
- Check firewall settings

### Embedding warnings
- Ensure sentence-transformers is installed: `pip install sentence-transformers`
- First usage will download the model (~100MB) - this is normal

### Connection errors
- Verify Qdrant is running: `curl http://localhost:6333`
- Check the URL in your config matches: `http://localhost:6333`
- Review Qdrant logs for startup errors

## Knowledge Base Management

To add documents to your knowledge base, you can:

1. Use the Qdrant Dashboard at http://localhost:6333/dashboard
2. Use the API endpoints in your application
3. Create a script to bulk import your documentation

## Stopping Qdrant

To stop Qdrant, press `Ctrl+C` in the terminal where it's running, or close the command window.

## Next Steps

- Add your Shiva documentation to the knowledge base
- Test vector search with relevant queries
- Monitor performance and adjust similarity thresholds if needed
- Consider setting up multiple collections for different applications (shiva_analytics, shiva_crm, etc.)
