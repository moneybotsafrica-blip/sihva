# Qdrant Local Setup Script for Windows
# This script downloads and sets up Qdrant for local development

Write-Host "Setting up Qdrant locally for vector search..." -ForegroundColor Green

# Create Qdrant directory
$qdrantDir = "C:\qdrant"
if (-not (Test-Path $qdrantDir)) {
    New-Item -ItemType Directory -Path $qdrantDir -Force
    Write-Host "Created Qdrant directory: $qdrantDir" -ForegroundColor Yellow
}

# Download Qdrant binary for Windows (latest version as zip)
$qdrantVersion = "v1.18.3"
$qdrantUrl = "https://github.com/qdrant/qdrant/releases/download/$qdrantVersion/qdrant-x86_64-pc-windows-msvc.zip"
$qdrantZip = Join-Path $qdrantDir "qdrant.zip"

Write-Host "Downloading Qdrant $qdrantVersion for Windows..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri $qdrantUrl -OutFile $qdrantZip -UseBasicParsing
    Write-Host "Qdrant downloaded successfully!" -ForegroundColor Green

    # Extract the zip file
    Write-Host "Extracting Qdrant..." -ForegroundColor Yellow
    Expand-Archive -Path $qdrantZip -DestinationPath $qdrantDir -Force

    # Find the extracted qdrant.exe
    $extractedExe = Get-ChildItem -Path $qdrantDir -Filter "qdrant.exe" -Recurse | Select-Object -First 1
    if ($extractedExe) {
        # Move to root of qdrant directory
        Move-Item -Path $extractedExe.FullName -Destination (Join-Path $qdrantDir "qdrant.exe") -Force
        Write-Host "Qdrant binary extracted and ready!" -ForegroundColor Green
    } else {
        Write-Host "Could not find qdrant.exe in extracted files" -ForegroundColor Red
        exit 1
    }

    # Clean up zip file
    Remove-Item $qdrantZip -Force
} catch {
    Write-Host "Failed to download/extract Qdrant. Error: $_" -ForegroundColor Red
    Write-Host "Please download manually from: $qdrantUrl" -ForegroundColor Red
    Write-Host "Extract and place qdrant.exe in: $qdrantDir" -ForegroundColor Red
    exit 1
}

# Create storage directory
$storageDir = Join-Path $qdrantDir "storage"
if (-not (Test-Path $storageDir)) {
    New-Item -ItemType Directory -Path $storageDir -Force
    Write-Host "Created storage directory: $storageDir" -ForegroundColor Yellow
}

# Create startup script
$startupScript = @"
@echo off
cd /d C:\qdrant
qdrant.exe --storage-path ./storage --log-level INFO
PAUSE
"@

$startupScriptPath = Join-Path $qdrantDir "start_qdrant.bat"
$startupScript | Out-File -FilePath $startupScriptPath -Encoding ASCII
Write-Host "Created startup script: $startupScriptPath" -ForegroundColor Yellow

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Qdrant setup complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start Qdrant:" -ForegroundColor Yellow
Write-Host "1. Run: $startupScriptPath" -ForegroundColor White
Write-Host "2. Or manually: cd C:\qdrant && qdrant.exe --storage-path ./storage" -ForegroundColor White
Write-Host ""
Write-Host "Qdrant will run on: http://localhost:6333" -ForegroundColor Cyan
Write-Host "Dashboard available at: http://localhost:6333/dashboard" -ForegroundColor Cyan
Write-Host ""
Write-Host "Your application is already configured to use localhost:6333" -ForegroundColor Green
Write-Host ""
