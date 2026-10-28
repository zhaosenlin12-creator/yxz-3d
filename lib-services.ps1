# =====================================================================
#  pingdou-workstation 服务层
#
#  四个服务（后端 / 前端 / WS通道 / 本地语音包）的统一定义与启停。
#  start-all.ps1（手动启动）和 supervise-all.ps1（守护重启）都从这里
#  取启动逻辑，保证两条路径跑的是同一套命令 —— 之前守护脚本另写一套，
#  端口和环境变量对不上，重启后前端就找不到后端了。
#
#  被 start-all.ps1 / stop-all.ps1 / supervise-all.ps1 dot-source 引用。
# =====================================================================

$script:YXZRunDir        = Join-Path $PSScriptRoot '.run'
$script:YXZPidDir        = Join-Path $script:YXZRunDir 'pids'
$script:YXZBackendRoot   = Join-Path $PSScriptRoot 'cartoon-print-studio'
$script:YXZFrontendRoot  = Join-Path $PSScriptRoot 'airi\apps\stage-web'
$script:YXZRuntimeRoot   = Join-Path $PSScriptRoot 'airi\packages\server-runtime'

$script:YXZServiceNames  = @('backend', 'frontend', 'runtime', 'voicebox')

function Initialize-YxzRunDir {
    New-Item -ItemType Directory -Force -Path $script:YXZRunDir | Out-Null
    New-Item -ItemType Directory -Force -Path $script:YXZPidDir | Out-Null
}

# ---- PID 记录 --------------------------------------------------------
function Get-YxzPidFile {
    param([string]$Name)
    return (Join-Path $script:YXZPidDir "$Name.pid")
}

function Save-YxzPid {
    param([string]$Name, [int]$ProcId)
    Initialize-YxzRunDir
    [System.IO.File]::WriteAllText((Get-YxzPidFile $Name), [string]$ProcId)
}

function Get-YxzPid {
    param([string]$Name)
    $file = Get-YxzPidFile $Name
    if (-not (Test-Path -LiteralPath $file)) { return 0 }
    $raw = ([System.IO.File]::ReadAllText($file)).Trim()
    $id = 0
    if ([int]::TryParse($raw, [ref]$id)) { return $id }
    return 0
}

function Clear-YxzPid {
    param([string]$Name)
    Remove-Item -LiteralPath (Get-YxzPidFile $Name) -Force -ErrorAction SilentlyContinue
}

# ---- 日志分文件 ------------------------------------------------------
# Start-Process 每次都会把重定向目标重新打开（也就是截断），所以上一轮
# 崩溃的 stderr 现场会被下一次重启冲掉 —— 后端莫名 exit 1 时就再也查
# 不到原因了。改成每次启动一个带时间戳的文件，崩溃现场永远留在盘上。
function New-YxzServiceLog {
    param([string]$Name, [int]$Port)
    Initialize-YxzRunDir
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $out = Join-Path $script:YXZRunDir "$Name-$Port.$stamp.out.log"
    $err = Join-Path $script:YXZRunDir "$Name-$Port.$stamp.err.log"
    [System.IO.File]::WriteAllText(
        (Join-Path $script:YXZRunDir "$Name-$Port.latest.txt"),
        "$out`n$err")
    # 只保留最近 10 份，别让 .run 目录无限膨胀。
    Get-ChildItem -LiteralPath $script:YXZRunDir -Filter "$Name-$Port.*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 10 |
        Remove-Item -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Out = $out; Err = $err }
}

# 取某个服务最新一份日志的路径（Out / Err）。
function Get-YxzLatestLog {
    param([string]$Name, [int]$Port)
    $pointer = Join-Path $script:YXZRunDir "$Name-$Port.latest.txt"
    if (-not (Test-Path -LiteralPath $pointer)) { return $null }
    $lines = @([System.IO.File]::ReadAllText($pointer) -split "`r?`n")
    if ($lines.Count -lt 2) { return $null }
    return [pscustomobject]@{ Out = $lines[0]; Err = $lines[1] }
}

# ---- 进程树停止 ------------------------------------------------------
# tsx.cmd / npm 这类启动器是 cmd.exe 包 node.exe，只杀父进程会把
# 真正的服务留在后台占着端口，于是「停完再启」就 bind 失败。
# taskkill /T 按进程树一起收掉。
function Stop-YxzProcessTree {
    param([int]$ProcId)
    if ($ProcId -le 0) { return $false }
    $proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    & taskkill.exe /PID $ProcId /T /F 2>&1 | Out-Null
    # 给系统一点时间回收端口
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Get-Process -Id $ProcId -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

# ---- 彻底脱离父进程树地启动进程 --------------------------------------
# Start-Process 起的子进程仍然挂在调用者的进程组里。调用者一旦被回收
# （关掉控制台窗口、任务管理器批量结束、或者别的工具按进程组清理），
# 四个服务会被「连坐」一起杀掉 —— 这正是之前「整套服务莫名全没了、
# 对话突然断掉」的真凶：守护进程和它管的四个服务一起没了。
#
# Win32_Process.Create 由 WMI 服务代为创建进程，新进程不属于调用者
# 的进程组，调用者被回收也带不走它。这样守护进程才能真正「一直在」。
function ConvertTo-YxzCommandLineArg {
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    # Windows 命令行转义规则：引号前的反斜杠成对，引号本身转义。
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Start-YxzDetachedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ''
    )
    $parts = @((ConvertTo-YxzCommandLineArg $FilePath))
    foreach ($arg in $Arguments) {
        if ($null -eq $arg) { continue }
        $parts += (ConvertTo-YxzCommandLineArg ([string]$arg))
    }
    $commandLine = $parts -join ' '

    try {
        $cimParams = @{ CommandLine = $commandLine }
        if ($WorkingDirectory) { $cimParams['CurrentDirectory'] = $WorkingDirectory }
        $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $cimParams
        if ($result -and $result.ReturnValue -eq 0 -and $result.ProcessId) {
            return [int]$result.ProcessId
        }
        Write-Host "  [WARN] 脱离式启动未成功（返回码 $($result.ReturnValue)），改用普通方式" -ForegroundColor Yellow
    }
    catch {
        Write-Host "  [WARN] 脱离式启动异常：$($_.Exception.Message)，改用普通方式" -ForegroundColor Yellow
    }

    # 退路：普通 Start-Process 至少还能把服务拉起来。
    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
        return [int]$proc.Id
    }
    catch {
        Write-Host "  [WARN] 启动失败：$($_.Exception.Message)" -ForegroundColor Yellow
        return 0
    }
}

# ---- 端口等待 --------------------------------------------------------
function Wait-YxzPortFree {
    param([int]$Port, [int]$TimeoutSec = 30)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        if (-not (Test-Port $Port)) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return (-not (Test-Port $Port))
}

function Wait-YxzPortOpen {
    param([int]$Port, [int]$TimeoutSec = 60)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return (Test-Port $Port)
}

# ---- 就绪判定 --------------------------------------------------------
function Test-YxzBackendReady {
    param([int]$Port = 8000)
    # /api/ping 是零 I/O 的探针。之前用 /api/software/detect，它冷缓存要
    # 扫注册表和开始菜单（约 10 秒），3 秒超时必然失败 —— 守护脚本会把
    # 完全健康的后端误判成卡死然后杀掉它。
    return (Test-HttpOk "http://127.0.0.1:$Port/api/ping")
}

function Test-YxzFrontendReady {
    param([int]$Port = 5199)
    return (Test-FrontendIdentity "http://127.0.0.1:$Port")
}

function Test-YxzRuntimeReady {
    param([int]$Port = 6121)
    return (Test-ServerRuntimeIdentity -Port $Port)
}

function Test-YxzVoiceboxReady {
    param([int]$Port = 17493)
    return (Test-HttpOk "http://127.0.0.1:$Port/health")
}

# 本地语音包没有项目标识，只能靠命令行认人：必须是 voicebox 目录下的
# backend.main，不然别的 Python 服务也会被误停。
function Test-YxzVoiceboxIdentity {
    param([int]$Port = 17493)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return $false }
    foreach ($c in $conns) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        $cmd = $info.CommandLine
        if ($cmd -and ($cmd -match 'backend\.main') -and ($cmd -match 'voicebox' -or $cmd -match '--port')) {
            return $true
        }
    }
    return $false
}

# ---- 启动函数 --------------------------------------------------------
function Start-YxzBackend {
    param([int]$Port = 8000)
    $venvPy = Join-Path $script:YXZBackendRoot 'ai\forge-webui\venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Write-Host "  [WARN] 后端 venv 不存在，跳过" -ForegroundColor Yellow
        return $null
    }
    Initialize-YxzRunDir
    $log = New-YxzServiceLog -Name 'backend' -Port $Port
    $out = $log.Out
    $err = $log.Err
    $proc = Start-Process -FilePath $venvPy `
        -ArgumentList @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', "$Port", '--app-dir', 'backend') `
        -WorkingDirectory $script:YXZBackendRoot -RedirectStandardOutput $out -RedirectStandardError $err `
        -WindowStyle Hidden -PassThru
    Save-YxzPid 'backend' $proc.Id
    return $proc
}

function Start-YxzFrontend {
    param([int]$Port = 5199, [int]$BackendPort = 8000)
    $vite = Join-Path $script:YXZFrontendRoot 'node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $vite)) {
        Write-Host "  [WARN] 未找到 vite，跳过前端" -ForegroundColor Yellow
        return $null
    }
    Initialize-YxzRunDir
    # 前端的 LLM / TTS 凭据靠 .env.local 注入，而 .env.local 是由
    # cartoon-print-studio\keys.txt 生成的（不入库）。每次启动都重新生成，
    # 这样换机器、换 key 之后不需要再手动去设置页填一遍。
    $genBootstrap = Join-Path $PSScriptRoot 'gen-provider-bootstrap.ps1'
    if (Test-Path -LiteralPath $genBootstrap) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $genBootstrap | Out-Null
    }
    $log = New-YxzServiceLog -Name 'frontend' -Port $Port
    $out = $log.Out
    $err = $log.Err
    $env:VITE_CARTOON_PRINT_API = "http://127.0.0.1:$BackendPort"
    try {
        $proc = Start-Process -FilePath (Get-Command node.exe -ErrorAction Stop).Source `
            -ArgumentList @($vite, '--host', '--port', "$Port") `
            -WorkingDirectory $script:YXZFrontendRoot -RedirectStandardOutput $out -RedirectStandardError $err `
            -WindowStyle Hidden -PassThru
    }
    finally {
        Remove-Item Env:VITE_CARTOON_PRINT_API -ErrorAction SilentlyContinue
    }
    Save-YxzPid 'frontend' $proc.Id
    return $proc
}

function Start-YxzRuntime {
    param([int]$Port = 6121)
    $tsx = Join-Path $PSScriptRoot 'airi\node_modules\.bin\tsx.cmd'
    if (-not (Test-Path -LiteralPath $tsx)) {
        Write-Host "  [WARN] 未找到 tsx，跳过 WS 通道" -ForegroundColor Yellow
        return $null
    }
    Initialize-YxzRunDir
    $log = New-YxzServiceLog -Name 'runtime' -Port $Port
    $out = $log.Out
    $err = $log.Err
    $prevPort = $env:PORT
    $prevHost = $env:HOST
    $env:PORT = "$Port"
    # The channel has to be reachable from the other computers on the
    # network, otherwise they can open the workbench but never talk to it.
    $env:HOST = '0.0.0.0'
    try {
        $proc = Start-Process -FilePath $tsx `
            -ArgumentList @('./src/bin/run.js') `
            -WorkingDirectory $script:YXZRuntimeRoot -RedirectStandardOutput $out -RedirectStandardError $err `
            -WindowStyle Hidden -PassThru
    }
    finally {
        if ($null -eq $prevPort) { Remove-Item Env:PORT -ErrorAction SilentlyContinue }
        else { $env:PORT = $prevPort }
        if ($null -eq $prevHost) { Remove-Item Env:HOST -ErrorAction SilentlyContinue }
        else { $env:HOST = $prevHost }
    }
    Save-YxzPid 'runtime' $proc.Id
    return $proc
}

function Get-YxzVoiceboxRoot {
    $candidates = @(
        $env:YXZ_VOICEBOX_ROOT,
        (Join-Path (Split-Path -Parent $PSScriptRoot) 'voicebox'),
        'C:\kaifa_boot\voicebox',
        (Join-Path $env:USERPROFILE 'kaifa_boot\voicebox')
    ) | Where-Object { $_ }
    return ($candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ '.venv\Scripts\python.exe') } | Select-Object -First 1)
}

function Start-YxzVoicebox {
    param([int]$Port = 17493, [int]$FrontendPort = 5199)
    $vbRoot = Get-YxzVoiceboxRoot
    if (-not $vbRoot) {
        Write-Host "  [WARN] 没找到本地语音包 Voicebox，跳过（宜小智会退回 Edge 免费语音）" -ForegroundColor Yellow
        return $null
    }
    Initialize-YxzRunDir
    $vbPy = Join-Path $vbRoot '.venv\Scripts\python.exe'
    $log = New-YxzServiceLog -Name 'voicebox' -Port $Port
    $out = $log.Out
    $err = $log.Err
    $prevCors = $env:VOICEBOX_CORS_ORIGINS
    $prevHfEndpoint = $env:HF_ENDPOINT
    $prevHfOffline = $env:HF_HUB_OFFLINE
    $prevTransformersOffline = $env:TRANSFORMERS_OFFLINE
    # 本地语音包用的 Qwen3-TTS 模型已经完整缓存在本机（4GB+）。但
    # transformers 每次加载仍会向 huggingface.co 发一个 HEAD 去确认
    # 版本 —— 这台机器连不上 huggingface，于是每次调用都要重试 5 次、
    # 白等 40 秒才失败，本地语音这条兜底等于废掉。
    #
    # 模型在缓存里就直接离线跑（一个网络请求都不发）；没缓存就指向
    # 国内镜像，好让缺的那几个文件能真的下下来。
    $modelCache = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice'
    if (Test-Path -LiteralPath $modelCache) {
        $env:HF_HUB_OFFLINE = '1'
        $env:TRANSFORMERS_OFFLINE = '1'
    }
    else {
        $env:HF_ENDPOINT = 'https://hf-mirror.com'
    }
    # The frontend proxies /voicebox-api to this port, so the browser
    # never talks to it cross-origin; the allowed origins are only for
    # somebody opening Voicebox's own playground page.
    $env:VOICEBOX_CORS_ORIGINS = "http://127.0.0.1:$FrontendPort,http://localhost:$FrontendPort"
    try {
        $proc = Start-Process -FilePath $vbPy `
            -ArgumentList @('-m', 'backend.main', '--host', '127.0.0.1', '--port', "$Port") `
            -WorkingDirectory $vbRoot -RedirectStandardOutput $out -RedirectStandardError $err `
            -WindowStyle Hidden -PassThru
    }
    catch {
        Write-Host "  [WARN] Voicebox 启动失败：$($_.Exception.Message)" -ForegroundColor Yellow
        return $null
    }
    finally {
        if ($null -eq $prevCors) { Remove-Item Env:VOICEBOX_CORS_ORIGINS -ErrorAction SilentlyContinue }
        else { $env:VOICEBOX_CORS_ORIGINS = $prevCors }
        if ($null -eq $prevHfEndpoint) { Remove-Item Env:HF_ENDPOINT -ErrorAction SilentlyContinue }
        else { $env:HF_ENDPOINT = $prevHfEndpoint }
        if ($null -eq $prevHfOffline) { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue }
        else { $env:HF_HUB_OFFLINE = $prevHfOffline }
        if ($null -eq $prevTransformersOffline) { Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue }
        else { $env:TRANSFORMERS_OFFLINE = $prevTransformersOffline }
    }
    Save-YxzPid 'voicebox' $proc.Id
    return $proc
}

# ---- 停止 ------------------------------------------------------------
function Stop-YxzServiceByPid {
    param([string]$Name, [string]$Label = '')
    $id = Get-YxzPid $Name
    Clear-YxzPid $Name
    if ($id -le 0) { return $false }
    if (Stop-YxzProcessTree -ProcId $id) {
        $text = if ($Label) { $Label } else { $Name }
        Write-Host "  [OK]   $text 已停止  PID=$id" -ForegroundColor Green
        return $true
    }
    return $false
}

# ---- 只清某个端口上的监听进程 ----------------------------------------
# 守护进程重启某个服务时用它腾位置。这里必须直接按端口收掉，不能去
# 调 stop-all.ps1 —— 那个脚本会把守护进程自己也停掉。
function Clear-YxzPort {
    param([int]$Port, [int]$TimeoutSec = 15)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        Stop-YxzProcessTree -ProcId ([int]$c.OwningProcess) | Out-Null
    }
    Wait-YxzPortFree -Port $Port -TimeoutSec $TimeoutSec | Out-Null
    return (-not (Test-Port $Port))
}

