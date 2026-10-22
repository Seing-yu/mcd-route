#Requires -Version 5.1
<#
.SYNOPSIS
    Configure the local WorkBuddy custom MCP entry for McDonald's China MCP.

.DESCRIPTION
    Reads the MCP Token from the local credential file and writes it into
    WorkBuddy's custom MCP config file, so that the token never has to be
    pasted into an AI chat window.

    Credential file  : $env:USERPROFILE\.workbuddy\.mcd_token
    Config written  : $env:USERPROFILE\.workbuddy\mcp.json
    Backup kept at  : $env:USERPROFILE\.workbuddy\mcp.json.bak

.NOTES
    Two encoding traps this script deliberately avoids:

    1) Windows PowerShell 5.1 `Set-Content -Encoding UTF8` writes a UTF-8 BOM.
       WorkBuddy parses mcp.json with a strict JSON reader and fails with
       "Unexpected UTF-8 BOM". This script writes with an explicit
       UTF8Encoding($false) so the file is BOM-free.

    2) This script file itself contains Chinese comments, so it MUST be saved
       as UTF-8 *with* BOM - otherwise PowerShell 5.1 decodes it as ANSI and
       the comments are garbled.

    Usage:
        powershell -ExecutionPolicy Bypass -File .\setup_mcp.ps1
        powershell -ExecutionPolicy Bypass -File .\setup_mcp.ps1 -TokenFile D:\path\token.txt
#>

[CmdletBinding()]
param(
    [string]$TokenFile,
    [string]$ConfigPath,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [!]  $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "    [X]  $Message" -ForegroundColor Red
}

$home_ = $env:USERPROFILE
if (-not $home_) { $home_ = $HOME }

if (-not $TokenFile) {
    $TokenFile = Join-Path $home_ '.workbuddy\.mcd_token'
}
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $home_ '.workbuddy\mcp.json'
}

Write-Host ""
Write-Host "McDonald's China MCP - WorkBuddy custom connector setup" -ForegroundColor White
Write-Host "----------------------------------------------------------------------"

# ---------------------------------------------------------------- 1. token
Write-Step "Locating credential file"
if (-not (Test-Path -LiteralPath $TokenFile)) {
    Write-Err "Credential file not found: $TokenFile"
    Write-Host ""
    Write-Host "Create it first, either by hand:" -ForegroundColor Yellow
    Write-Host "  1. Apply for a token at https://open.mcd.cn/mcp"
    Write-Host "     (mobile login -> top-right Console -> Activate -> copy token)"
    Write-Host "  2. Write it into that file, one single line, no quotes."
    Write-Host ""
    Write-Host "Or run the Python helper instead:"
    Write-Host "  python setup_token.py"
    exit 1
}
Write-Ok "Found: $TokenFile"

$token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
if (-not $token) {
    Write-Err "Credential file is empty."
    exit 1
}
if ($token -match '\s') {
    Write-Warn "Token contains whitespace; inner spaces are kept as-is."
}
Write-Ok "Token length: $($token.Length) characters (value not displayed)"

# ---------------------------------------------------------------- 2. backup
if (Test-Path -LiteralPath $ConfigPath) {
    Write-Step "Backing up existing config"
    $backup = "$ConfigPath.bak"
    Copy-Item -LiteralPath $ConfigPath -Destination $backup -Force
    Write-Ok "Backup: $backup"
}

# ---------------------------------------------------------------- 3. build
Write-Step "Building MCP config"
$config = [ordered]@{
    mcpServers = [ordered]@{
        'mcd-mcp' = [ordered]@{
            type    = 'http'
            url     = 'https://mcp.mcd.cn'
            headers = [ordered]@{
                Authorization = "Bearer $token"
            }
        }
    }
}

$json = ($config | ConvertTo-Json -Depth 10) + "`n"

# BOM-free UTF-8: this is the whole point of using .NET APIs here.
# Set-Content -Encoding UTF8 on PowerShell 5.1 would emit a BOM and break
# WorkBuddy's JSON parser.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$configDir = Split-Path -Parent $ConfigPath
if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    Write-Ok "Created directory: $configDir"
}
[System.IO.File]::WriteAllText($ConfigPath, $json, $utf8NoBom)
Write-Ok "Written: $ConfigPath"

# ---------------------------------------------------------------- 4. verify
Write-Step "Verifying result"
$raw = [System.IO.File]::ReadAllBytes($ConfigPath)
if ($raw.Length -ge 3 -and $raw[0] -eq 0xEF -and $raw[1] -eq 0xBB -and $raw[2] -eq 0xBF) {
    Write-Err "Unexpected UTF-8 BOM detected. This should not happen."
    exit 1
}
Write-Ok "Encoding: UTF-8 without BOM"

try {
    $parsed = [System.IO.File]::ReadAllText($ConfigPath, $utf8NoBom) | ConvertFrom-Json
    $entry = $parsed.mcpServers.'mcd-mcp'
    if ($entry.type -ne 'http') { throw "type is '$($entry.type)', expected 'http'" }
    if ($entry.url -ne 'https://mcp.mcd.cn') { throw "url is '$($entry.url)'" }
    Write-Ok "JSON valid: key=mcd-mcp, type=http, url=$($entry.url)"
} catch {
    Write-Err "Verification failed: $($_.Exception.Message)"
    exit 1
}

# ---------------------------------------------------------------- 5. next
Write-Host ""
Write-Host "----------------------------------------------------------------------"
Write-Host "Done. Remaining steps:" -ForegroundColor White
Write-Host "  1. Fully quit and relaunch WorkBuddy (closing the window is not enough)."
Write-Host "  2. Sidebar -> Experts, Skills & Connectors -> Connectors"
Write-Host "  3. Find 'mcd-mcp' -> click [Trust] -> switch it on."
Write-Host ""
Write-Warn "The token is stored in PLAIN TEXT in mcp.json (that file is outside any"
Write-Warn "git repository, but do not screenshot or share it)."
Write-Warn "To revoke: delete the config, and re-apply for a token at open.mcd.cn."
Write-Host ""
