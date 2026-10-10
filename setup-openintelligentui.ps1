param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$upstreamRoot = Join-Path $projectRoot 'work\research\openintelligentui-20261009'
$pinnedCommit = 'f6e4388b26a64b9a0714943b08a1ce622b924eec'
if (-not (Test-Path -LiteralPath (Join-Path $upstreamRoot '.git'))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $upstreamRoot) -Force | Out-Null
    & git clone https://github.com/CopilotKit/OpenIntelligentUI.git $upstreamRoot
    if ($LASTEXITCODE) { throw 'Upstream clone failed.' }
    & git -C $upstreamRoot checkout --detach $pinnedCommit
    if ($LASTEXITCODE) { throw 'Pinned upstream checkout failed.' }
}
$actual = & git -C $upstreamRoot rev-parse HEAD
if ($actual -ne $pinnedCommit) { throw 'Upstream revision differs from the reviewed import. Review before updating.' }
if (-not $SkipInstall) {
    Push-Location (Join-Path $projectRoot 'integrations\openintelligentui')
    try { & npm.cmd ci --ignore-scripts --no-audit --no-fund; if ($LASTEXITCODE) { throw 'Visual runtime installation failed.' } }
    finally { Pop-Location }
    Push-Location $upstreamRoot
    try { & npx.cmd --yes pnpm@9.0.0 install --frozen-lockfile; if ($LASTEXITCODE) { throw 'Node dependency installation failed.' } }
    finally { Pop-Location }
    Push-Location (Join-Path $upstreamRoot 'apps\agent')
    try { & uv sync --frozen; if ($LASTEXITCODE) { throw 'Python dependency installation failed.' } }
    finally { Pop-Location }
}
$agentEnv = Join-Path $upstreamRoot 'apps\agent\.env'
if (-not (Test-Path -LiteralPath $agentEnv)) { [IO.File]::WriteAllText($agentEnv, "# Standalone upstream demo only. Open Learn loads backend/.env.`nOPENAI_API_KEY=`nTYPESAFE_API_KEY=`nLLM_MODEL=chat-latest`nJEV_MODEL=jev-latest`n", [Text.UTF8Encoding]::new($false)) }
$backendEnv = Join-Path $projectRoot 'backend\.env'
if (-not (Test-Path -LiteralPath $backendEnv)) { throw 'Configure backend/.env first.' }
$lines = [IO.File]::ReadAllLines($backendEnv)
if (-not ($lines | Where-Object { $_ -match '^OPENLEARN_VISUAL_INTERNAL_SECRET=' })) {
    $secretBytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($secretBytes) } finally { $random.Dispose() }
    [IO.File]::AppendAllText($backendEnv, "`nOPENLEARN_VISUAL_INTERNAL_SECRET=$([Convert]::ToBase64String($secretBytes))`n", [Text.UTF8Encoding]::new($false))
}
& (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe') (Join-Path $projectRoot 'integrations\openintelligentui\import-renderer.py')
if ($LASTEXITCODE) { throw 'Renderer import failed.' }
& node (Join-Path $projectRoot 'web\scripts\build-visual-assets.mjs')
if ($LASTEXITCODE) { throw 'Visual asset build failed.' }
Write-Host 'Pinned OpenIntelligentUI setup complete. JEV and generation reuse backend/.env OPENROUTER_API_KEY. Run start-openintelligentui.ps1.'
