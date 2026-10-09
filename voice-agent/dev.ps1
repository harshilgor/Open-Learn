param(
    [string]$BackendEnvPath = "$(Split-Path -Parent $PSScriptRoot)\backend\.env"
)

$ErrorActionPreference = 'Stop'
$agentName = 'openlearn-voice-local'
$required = @(
    'LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET',
    'DEEPGRAM_API_KEY', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID'
)
$optional = @('ELEVENLABS_MODEL')
$values = @{}

if (-not (Test-Path -LiteralPath $BackendEnvPath)) {
    throw "Local backend config was not found. Add the voice provider settings to backend/.env first."
}

foreach ($line in [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $BackendEnvPath))) {
    if ($line -match '^\s*([^#\s][^=]*)=(.*)$') {
        $key = $Matches[1].Trim()
        if (($required + $optional) -contains $key) { $values[$key] = $Matches[2] }
    }
}

$missing = @($required | Where-Object { [string]::IsNullOrWhiteSpace($values[$_]) })
if ($missing.Count) { throw "Missing local voice settings in backend/.env: $($missing -join ', ')" }

foreach ($key in $required) {
    [Environment]::SetEnvironmentVariable($key, $values[$key], 'Process')
}
[Environment]::SetEnvironmentVariable('OPENLEARN_API_URL', 'http://127.0.0.1:8000', 'Process')
[Environment]::SetEnvironmentVariable('OPENLEARN_VOICE_LOCAL_DEV', 'true', 'Process')
[Environment]::SetEnvironmentVariable('OPENLEARN_VOICE_AGENT_NAME', $agentName, 'Process')
if ($values.ContainsKey('ELEVENLABS_MODEL')) {
    [Environment]::SetEnvironmentVariable('ELEVENLABS_MODEL', $values['ELEVENLABS_MODEL'], 'Process')
}

Push-Location $PSScriptRoot
try {
    $agentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $agentPython)) {
        throw 'Install voice-agent/requirements.txt into voice-agent/.venv before starting the worker.'
    }
    & $agentPython agent.py dev
} finally {
    Pop-Location
}
