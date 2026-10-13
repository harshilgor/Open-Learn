# Start both halves of the local app. Reuse healthy services already running.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtime = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$logRoot = Join-Path $projectRoot 'work\local-runtime'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $runtime)) { throw 'Install the local dependencies with .\install-local.ps1 first. See docs\INSTALL.md for help.' }

# A development sandbox can inject an intentionally unreachable loopback
# proxy. Do not pass that proxy to the tutor process: provider requests would
# fail before reaching OpenRouter or OpenAI. Preserve real user proxies.
foreach ($proxyName in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')) {
    $proxyValue = [Environment]::GetEnvironmentVariable($proxyName, 'Process')
    if ($proxyValue -match '^https?://127\.0\.0\.1:9/?$') {
        [Environment]::SetEnvironmentVariable($proxyName, $null, 'Process')
    }
}

function Test-LocalService([string]$Address) {
    try {
        $request = [System.Net.WebRequest]::Create($Address)
        $request.Proxy = $null
        $request.Timeout = 15000
        $response = $request.GetResponse()
        try { return [int]$response.StatusCode -eq 200 }
        finally { $response.Close() }
    }
    catch { return $false }
}

function Get-LoopbackPortOwners([int]$Port) {
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

if (-not (Test-LocalService 'http://127.0.0.1:8000/health')) {
    $api = Start-Process -FilePath $runtime -ArgumentList @('backend/scripts/run_local_api.py') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'api.log') -RedirectStandardError (Join-Path $logRoot 'api-error.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-LocalService 'http://127.0.0.1:8000/health') { $ready = $true; break }
        if ($api.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Tutor service did not start. See $logRoot\api-error.log" }
    Write-Host "Tutor service started (PID $($api.Id))."
}
if (-not (Test-LocalService 'http://127.0.0.1:3000/')) {
    $vinextLock = Join-Path $projectRoot 'web\.vinext\dev\lock.json'
    if (Test-Path -LiteralPath $vinextLock) {
        try {
            $lock = Get-Content -LiteralPath $vinextLock -Raw | ConvertFrom-Json
            $lockedProcess = Get-Process -Id $lock.pid -ErrorAction SilentlyContinue
            # A Vinext process which cannot answer on the documented IPv4
            # endpoint is stalled. Stop only the process named by its lock.
            if ($lockedProcess) { Stop-Process -Id $lock.pid -Force }
            Remove-Item -LiteralPath $vinextLock -Force
            Write-Host 'Removed a stale Vinext development-server lock.'
        } catch { Remove-Item -LiteralPath $vinextLock -Force -ErrorAction SilentlyContinue }
    }
    $portOwners = Get-LoopbackPortOwners 3000
    if ($portOwners.Count -gt 0) {
        throw "Port 3000 is in use by process ID(s) $($portOwners -join ', ') but is not serving Forma at http://127.0.0.1:3000/. Stop that process and run this script again."
    }
    $npm = (Get-Command npm.cmd).Source
    $ui = Start-Process -FilePath $npm -ArgumentList @('run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000') -WorkingDirectory (Join-Path $projectRoot 'web') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'web.log') -RedirectStandardError (Join-Path $logRoot 'web-error.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-LocalService 'http://127.0.0.1:3000/') { $ready = $true; break }
        if ($ui.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Web interface did not start. See $logRoot\web-error.log" }
    Write-Host "Web interface started (PID $($ui.Id)). Logs: $logRoot"
}
Write-Host 'Local app: http://127.0.0.1:3000'
