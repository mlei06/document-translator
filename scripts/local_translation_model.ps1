param(
    [ValidateSet('hy-mt2-q4', 'hy-mt2-q8', 'translategemma-q4', 'hy-mt2-1.25bit', 'hy-mt2-2bit')]
    [string]$Model = 'hy-mt2-q8',
    [ValidateSet('cpu', 'gpu')]
    [string]$Device = 'cpu',
    [ValidateSet('vendor', 'greedy')]
    [string]$Preset = 'vendor',
    [ValidateRange(1, 256)]
    [int]$Threads = 8,
    [switch]$NoPromptCache,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$runtimeName = if ($Model -eq 'translategemma-q4') { 'llama-b11236-cuda' } else { 'llama-b11146' }
if ($Model -eq 'hy-mt2-1.25bit') { $runtimeName = 'llama-stq-7ef6976' }
if ($Model -eq 'hy-mt2-2bit') { $runtimeName = 'llama-int2-2af64dd' }
$runtime = Join-Path $repo "data/runtime/$runtimeName/llama-server.exe"
$stateDir = Join-Path $repo 'data/local-models'
New-Item -ItemType Directory -Force $stateDir | Out-Null
$statePath = Join-Path $stateDir "$Model.process.json"

if ($Stop) {
    if (-not (Test-Path -LiteralPath $statePath)) { Write-Output "$Model is not recorded as running."; return }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $running = Get-Process -Id $state.id -ErrorAction SilentlyContinue
    if ($running) {
        if ($running.Path -ne $runtime -or $running.StartTime.ToUniversalTime().Ticks -ne $state.startedTicks) {
            throw 'Process identity changed; refusing to stop a different process.'
        }
        Stop-Process -Id $running.Id
    }
    Remove-Item -LiteralPath $statePath
    Write-Output "Stopped $Model."
    return
}

$catalog = @{
    'hy-mt2-1.25bit' = @('hy-mt2-angelslim/Hy-MT2-1.8B-1.25Bit.gguf', 'cc497fe8f033b52b3b8b00a7669e9661435432f9d4cd43f7ed24400c01507a93', 'hy-mt2', 8094)
    'hy-mt2-2bit' = @('hy-mt2-angelslim/Hy-MT2-1.8B-2Bit.gguf', 'dcc33bbae9b28d923c8c76a64f6157840841d26f8774f3dfd770d5fabeeb1cd7', 'hy-mt2', 8095)
    'hy-mt2-q4' = @('hy-mt2/Hy-MT2-1.8B-Q4_K_M.gguf', 'dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699', 'hy-mt2', 8091)
    'hy-mt2-q8' = @('hy-mt2/Hy-MT2-1.8B-Q8_0.gguf', '5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4', 'hy-mt2', 8092)
    'translategemma-q4' = @('translategemma/translategemma-4b-it.Q4_K_M.gguf', '81200d03e843d2ec1ece6eeafe7d13cb6e5211e1fcd336ade55790b683a08330', 'translategemma', 8093)
}
if ($Model -eq 'hy-mt2-1.25bit') { Write-Warning 'Experimental: this model loaded but failed the translation smoke test. Do not use for production documents.' }
$entry = $catalog[$Model]
$modelPath = Join-Path $repo (Join-Path 'data/models' $entry[0])
$port = $entry[3]
if (-not (Test-Path -LiteralPath $runtime)) { throw "Missing runtime: $runtime. See docs/experiments/translation-profiles/README.md." }
if (-not (Test-Path -LiteralPath $modelPath)) { throw "Missing model: $modelPath. See docs/experiments/translation-profiles/README.md." }
if ((Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash -ne $entry[1]) { throw 'Model SHA-256 does not match the pinned artifact.' }

$probe = [Net.Sockets.TcpClient]::new()
try { $probe.Connect('127.0.0.1', $port); $occupied = $true } catch { $occupied = $false } finally { $probe.Dispose() }
if ($occupied) { throw "Port $port is already in use; no existing process was changed." }

$keyPath = Join-Path $stateDir 'server.key'
if (-not (Test-Path -LiteralPath $keyPath)) {
    [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)) | Set-Content -LiteralPath $keyPath
}
$localKey = (Get-Content -LiteralPath $keyPath -Raw).Trim()
$envPath = Join-Path $stateDir "$Model.env"
$isGemma = $Model -eq 'translategemma-q4'
$isCpu = $Device -eq 'cpu' -or $isGemma -or $Model -like '*bit'
$flashAttention = if ($isCpu) { 'off' } else { 'on' }
$gpuLayers = if ($isCpu) { 0 } else { 99 }
$slots = if ($isCpu) { 1 } else { 8 }
$deviceArgs = if ($isCpu) { ' --device none --no-kv-offload' } else { '' }
$cacheRevision = if ($Model -eq 'translategemma-q4') { ';swa-full;no-cache-prompt;no-jinja' } else { ';native-chat;cache-prompt' }
if ($NoPromptCache -and -not $isGemma) { $cacheRevision = ';native-chat;no-cache-prompt' }
$vendor = $Preset -eq 'vendor' -and -not $isGemma
$temperature = if ($vendor) { 0.7 } else { 0 }
$topP = if ($vendor) { 0.6 } else { 1 }
$topK = if ($vendor) { 20 } else { 0 }
$penalty = if ($vendor) { 1.05 } else { 1 }
$outputTokens = if ($vendor) { 4096 } else { 2048 }
$contextTotal = 8192 * $slots
@"
DOCTRANSLATOR_MODE=llm
DOCTRANSLATOR_LLM_BASE_URL=http://127.0.0.1:$port/v1
DOCTRANSLATOR_LLM_API_KEY=$localKey
DOCTRANSLATOR_LLM_MODEL=$Model
DOCTRANSLATOR_LLM_TRANSLATION_PROFILE=$($entry[2])
DOCTRANSLATOR_LLM_SERVER_BACKEND=llamacpp
DOCTRANSLATOR_LLM_DEPLOYMENT_REVISION=sha256:$($entry[1]);$runtimeName;gpu$gpuLayers;fa-$flashAttention;slots$slots;ctx8192;threads$Threads;no-context-shift$cacheRevision
DOCTRANSLATOR_LLM_MAX_CONCURRENCY=$slots
DOCTRANSLATOR_LLM_MAX_OUTPUT_TOKENS=$outputTokens
DOCTRANSLATOR_LLM_TEMPERATURE=$temperature
DOCTRANSLATOR_LLM_TOP_P=$topP
DOCTRANSLATOR_LLM_TOP_K=$topK
DOCTRANSLATOR_LLM_REPETITION_PENALTY=$penalty
DOCTRANSLATOR_LLM_SEED=0
"@ | Set-Content -LiteralPath $envPath

$arguments = "-m `"$modelPath`" --alias $Model --host 127.0.0.1 --port $port -ngl $gpuLayers -fa $flashAttention -np $slots -c $contextTotal -t $Threads -tb $Threads --no-context-shift --no-webui --api-key-file `"$keyPath`""
if ($Model -eq 'translategemma-q4') { $arguments += ' --no-jinja --chat-template gemma --swa-full --no-cache-prompt' }
if (-not $isGemma) { $arguments += ' --jinja' }
if ($NoPromptCache -and -not $isGemma) { $arguments += ' --no-cache-prompt' }
$arguments += $deviceArgs
$started = Start-Process -FilePath $runtime -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $stateDir "$Model.stdout.log") -RedirectStandardError (Join-Path $stateDir "$Model.stderr.log")
@{ id = $started.Id; startedTicks = $started.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath $statePath
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($started.HasExited) { break }
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$port/health" -Headers @{Authorization = "Bearer $localKey"} -TimeoutSec 1
        if ($health.status -eq 'ok') { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    if (-not $started.HasExited) { Stop-Process -Id $started.Id }
    Remove-Item -LiteralPath $statePath
    throw "Server did not become ready. Inspect $stateDir/$Model.stderr.log."
}
Write-Output "$Model ready on loopback port $port."
Write-Output "Use: uv run doctranslator translate INPUT --to en --config `"$envPath`""
