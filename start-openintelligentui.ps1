$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$upstreamRoot = Join-Path $projectRoot 'work\research\openintelligentui-20261009'
$pythonRuntime = Join-Path $upstreamRoot 'apps\agent\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonRuntime)) { throw 'Run setup-openintelligentui.ps1 first.' }
# Only the internal ticket signing secret and nonsecret model selection go to
# the visual sidecars. Provider secrets stay in the Open Learn backend.
foreach ($line in [IO.File]::ReadAllLines((Join-Path $projectRoot 'backend\.env'))) {
    if ($line -match '^\s*(OPENLEARN_VISUAL_INTERNAL_SECRET|OPENLEARN_VISUAL_MODEL|OPENLEARN_VISUAL_JEV_MODEL|OPENROUTER_MODEL)\s*=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
}
if (-not $env:OPENLEARN_VISUAL_INTERNAL_SECRET) { throw 'Run setup-openintelligentui.ps1 to create local service authentication.' }
$env:OPENLEARN_OPENINTELLIGENTUI_ROOT = $upstreamRoot
$env:OPENLEARN_VISUAL_NODE_PACKAGE = Join-Path $projectRoot 'integrations\openintelligentui\package.json'
$env:LANGSMITH_TRACING = 'false'
$env:COPILOTKIT_TELEMETRY_DISABLED = 'true'
$logRoot = Join-Path $projectRoot 'work\local-runtime'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
foreach ($service in @(
    @{Name='visual-agent';Port=8123;File=$pythonRuntime;Args=@('integrations/openintelligentui/agent.py')},
    @{Name='visual-runtime';Port=8130;File=(Get-Command node.exe).Source;Args=@('integrations/openintelligentui/runtime.mjs')}
)) {
    try { $status = Invoke-RestMethod -Uri "http://127.0.0.1:$($service.Port)/health" -TimeoutSec 2 -Proxy $null } catch { $status = $null }
    if ($status -and $status.service -eq "openlearn-$($service.Name)") { Write-Host "$($service.Name) already running."; continue }
    if (Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $($service.Port) is already occupied by another service." }
    $process = Start-Process -FilePath $service.File -ArgumentList $service.Args -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$($service.Name).log") -RedirectStandardError (Join-Path $logRoot "$($service.Name)-error.log")
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($service.Port)/health" -TimeoutSec 1 -Proxy $null } catch { $health = $null }
        if ($health.service -eq "openlearn-$($service.Name)") { $ready = $true; break }
        if ($process.HasExited) { break }
    }
    if (-not $ready) { throw "$($service.Name) failed readiness. Inspect work/local-runtime/$($service.Name)-error.log." }
    Write-Host "$($service.Name) ready (PID $($process.Id))."
}
Write-Host 'Visual sidecars ready. JEV and generation use OPENROUTER_API_KEY in the backend. Enable OPENLEARN_VISUAL_ENGINE=openintelligentui and restart the local API for acceptance testing.'
