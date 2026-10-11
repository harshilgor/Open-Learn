[CmdletBinding()]
param(
    [string]$SidecarPath,
    [switch]$KeepRuntimeData
)

$ErrorActionPreference = 'Stop'
if (-not $SidecarPath) { $SidecarPath = Join-Path $PSScriptRoot '..\..\backend\dist\forma-api\forma-api.exe' }
$resolvedSidecar = (Resolve-Path -LiteralPath $SidecarPath).Path
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("forma-runtime-smoke-" + [guid]::NewGuid().ToString('N'))
$dataRoot = Join-Path $runtimeRoot 'data'
$materialRoot = Join-Path $runtimeRoot 'materials'
$first = $null
$second = $null
New-Item -ItemType Directory -Force -Path $dataRoot, $materialRoot | Out-Null

function Get-FreeLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()
    return $port
}

function Start-Sidecar([int]$Port) {
    $env:FORMA_DB_PATH = Join-Path $dataRoot 'forma.db'
    $env:AI_TUTOR_MATERIAL_DIR = $materialRoot
    $env:AI_TUTOR_ENV = 'development'
    $env:FORMA_API_TOKEN = 'runtime-smoke-token'
    return Start-Process -FilePath $resolvedSidecar -ArgumentList @('--host', '127.0.0.1', '--port', "$Port") -WorkingDirectory $runtimeRoot -WindowStyle Hidden -PassThru
}

function Wait-ForHealth([int]$Port, [System.Diagnostics.Process]$Process) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri "http://127.0.0.1:$Port/health").StatusCode -eq 200) { return }
        } catch {}
        if ($Process.HasExited) { throw "The bundled API sidecar exited with code $($Process.ExitCode)." }
        Start-Sleep -Milliseconds 250
    }
    throw 'The bundled API sidecar did not become healthy.'
}

function Stop-Sidecar([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process -or $Process.HasExited) { return }
    # PyInstaller's Windows bootloader can spawn a child process for the bundled
    # Python runtime. Killing only the launcher leaves that child holding forma.db.
    try {
        $Process.Kill($true)
    } catch {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
    $Process.WaitForExit()
}

try {
    # Clean-launch test: the sidecar must initialize a fresh app-data database and migrations.
    $firstPort = Get-FreeLoopbackPort
    $first = Start-Sidecar $firstPort
    Wait-ForHealth $firstPort $first
    $headers = @{ 'X-Forma-Desktop-Token' = 'runtime-smoke-token'; 'Content-Type' = 'application/json' }
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$firstPort/v1/topic-scopes" -Headers $headers -Body '{"topic":"runtime smoke test","depth":"introductory"}' | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'forma.db'))) { throw 'The sidecar did not create its SQLite database in the application-data directory.' }
    Stop-Sidecar $first

    # Restart test: reopen against the same data directory and confirm the API is ready again.
    $secondPort = Get-FreeLoopbackPort
    $second = Start-Sidecar $secondPort
    Wait-ForHealth $secondPort $second
    Stop-Sidecar $second

    # Uninstall semantics: the application data directory is intentionally separate from the install directory.
    # A normal uninstaller must leave it intact so a reinstall can restore learner state.
    if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'forma.db'))) { throw 'Application data was not retained after the sidecar stopped.' }
    Write-Host "Bundled runtime smoke test passed. Temporary app data: $runtimeRoot"
}
finally {
    foreach ($process in @($first, $second)) {
        if ($null -ne $process -and -not $process.HasExited) { Stop-Sidecar $process }
    }
    if (-not $KeepRuntimeData -and (Test-Path -LiteralPath $runtimeRoot)) { Remove-Item -LiteralPath $runtimeRoot -Recurse -Force }
}
