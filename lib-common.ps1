# =====================================================================
#  pingdou-workstation 共用工具函数
#  被 install-new-pc.ps1 / start-all.ps1 dot-source 引用。
# =====================================================================

$script:PWS = $PSScriptRoot

function Get-ProjectRoot {
    return $PSScriptRoot
}

# ---- 端口 -------------------------------------------------------------
function Test-Port {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# 一次性拿到本机所有处于 LISTEN 的端口。
# 逐端口调 Get-NetTCPConnection 每次都要初始化 CIM，几十个端口扫下来
# 能白白耗掉十几秒；这里一次查询搞定，后面用哈希表 O(1) 判断。
function Get-ListeningPorts {
    $set = New-Object 'System.Collections.Generic.HashSet[int]'
    try {
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            [void]$set.Add([int]$_.LocalPort)
        }
    } catch { }
    return ,$set
}

function Wait-Port {
    param([int]$Port, [int]$TimeoutSec = 60, [string]$Label = '')
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# ---- HTTP 探测 --------------------------------------------------------
# Get-HttpResponse：直接用 HttpWebRequest 发请求。
#   - Proxy = $null：本机回环地址绝不能走系统代理（否则每个关闭端口都要
#     等满超时，一轮端口扫描能白白耗掉一两分钟）。
#   - 状态码 + 原始字节一起返回：4xx/5xx 也算“有东西在应答”，
#     字节由调用方按 UTF-8 自行解码（PS 5.1 的 Invoke-WebRequest 会按
#     系统 GBK 解码，中文标记会被解成乱码）。
function Get-HttpResponse {
    param([string]$Url, [int]$TimeoutSec = 3)
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Timeout = $TimeoutSec * 1000
        $req.ReadWriteTimeout = $TimeoutSec * 1000
        $req.Proxy = $null
        $req.AllowAutoRedirect = $true
        $req.UserAgent = 'yxz-3d-local/1.0'
        $resp = $req.GetResponse()
        $ms = New-Object System.IO.MemoryStream
        $resp.GetResponseStream().CopyTo($ms)
        $code = [int]$resp.StatusCode
        $bytes = $ms.ToArray()
        $resp.Close()
        return [pscustomobject]@{ StatusCode = $code; Bytes = $bytes }
    } catch [System.Net.WebException] {
        $ex = $_.Exception
        if ($ex.Response) {
            try {
                $ms = New-Object System.IO.MemoryStream
                $ex.Response.GetResponseStream().CopyTo($ms)
                $code = [int]$ex.Response.StatusCode
                $bytes = $ms.ToArray()
                $ex.Response.Close()
                return [pscustomobject]@{ StatusCode = $code; Bytes = $bytes }
            } catch { return $null }
        }
        return $null
    } catch { return $null }
}

# Test-HttpOk：只要对方是活的 HTTP 服务就算 True（4xx/5xx 也算）。
#              只用于「端口上有没有东西在应答」，**不能**用来判断
#              「这个服务是不是我们自己的」——别的程序也会应答 404。
function Test-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 3)
    $r = Get-HttpResponse -Url $Url -TimeoutSec $TimeoutSec
    if (-not $r) { return $false }
    return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
}

# Test-HttpMarker：要求 200 且响应体包含指定标记串。
#                  用来确认“这个端口上的服务确实是本项目的”。
# 注意：Windows PowerShell 5.1 的 Invoke-WebRequest 会用系统默认编码
#       （中文 Windows 上是 GBK）解码「没有 charset 的响应体」，
#       中文标记会被解成乱码导致匹配永远失败。所以这里取原始字节，
#       自己按 UTF-8 解码，PS 5.1 / PS 7 行为一致。
function Test-HttpMarker {
    param([string]$Url, [string]$Marker, [int]$TimeoutSec = 3)
    $r = Get-HttpResponse -Url $Url -TimeoutSec $TimeoutSec
    if (-not $r) { return $false }
    if ($r.StatusCode -ne 200) { return $false }
    if (-not $Marker) { return $true }
    $text = [Text.Encoding]::UTF8.GetString($r.Bytes)
    return ($text -match [regex]::Escape($Marker))
}

# 本项目后端的身份标识（server.py 里 FastAPI(title=...)）
function Test-BackendIdentity {
    param([string]$BaseUrl, [int]$TimeoutSec = 3)
    return (Test-HttpMarker -Url "$BaseUrl/openapi.json" -Marker 'Cartoon Print Studio API' -TimeoutSec $TimeoutSec)
}

# 本项目前端的身份标识（index.html 里的 title）
function Test-FrontendIdentity {
    param([string]$BaseUrl, [int]$TimeoutSec = 3)
    # 双保险：中文标题 + 一个本项目 index.html 独有的 ASCII 标记，
    # 任一命中即认为是本项目的前端。
    return ((Test-HttpMarker -Url "$BaseUrl/" -Marker '宜小智' -TimeoutSec $TimeoutSec) -or
            (Test-HttpMarker -Url "$BaseUrl/" -Marker 'apple-mobile-web-app-capable' -TimeoutSec $TimeoutSec))
}

# ---- 终端输出 ---------------------------------------------------------
function Say  { param([string]$m, [string]$c = 'Gray')   Write-Host $m -ForegroundColor $c }
function Ok   { param([string]$m)  Write-Host "  [OK]   $m" -ForegroundColor Green }
function Warn { param([string]$m)  Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Fail { param([string]$m)  Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Step { param([string]$m)  Write-Host "  [..]   $m" -ForegroundColor Cyan }

# ---- 可靠的二进制下载（绕开 node/python 大文件卡死）--------------------
# .NET HttpWebRequest 在本机对大文件稳定；node fetch / pip 在部分网络下会停滞。
function Get-RemoteFile {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$TimeoutSec = 300
    )
    if (Test-Path -LiteralPath $OutFile) {
        $len = (Get-Item -LiteralPath $OutFile).Length
        if ($len -gt 1024) { return $true }
    }
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    try {
        $req = [Net.HttpWebRequest]::Create($Url)
        $req.UserAgent = 'Mozilla/5.0'
        $req.Timeout = 60000
        $req.ReadWriteTimeout = 120000
        $resp = $req.GetResponse()
        $src = $resp.GetResponseStream()
        $dst = [IO.File]::Open($OutFile, [IO.FileMode]::Create)
        try {
            $buf = New-Object byte[] 1048576
            while ($read = $src.Read($buf, 0, $buf.Length)) { $dst.Write($buf, 0, $read) }
        } finally { $dst.Close(); $src.Close(); $resp.Close() }
        return $true
    } catch {
        Warn "下载失败 $Url -> $($_.Exception.Message)"
        return $false
    }
}

# ---- 镜像配置 ---------------------------------------------------------
function Enable-PipMirror {
    param([string]$VenvDir, [string]$Index = 'https://pypi.tuna.tsinghua.edu.cn/simple')
    $ini = Join-Path $VenvDir 'pip.ini'
    $body = @(
        '[global]',
        "index-url = $Index",
        'extra-index-url = https://download.pytorch.org/whl/cu121',
        'timeout = 60',
        'retries = 5',
        '',
        '[install]',
        'trusted-host = pypi.tuna.tsinghua.edu.cn',
        '               download.pytorch.org'
    )
    Set-Content -LiteralPath $ini -Value $body -Encoding ASCII
}

function Enable-NpmMirror {
    param([string]$Registry = 'https://registry.npmmirror.com')
    $npmrc = Join-Path $env:USERPROFILE '.npmrc'
    $lines = @("registry=$Registry")
    if (Test-Path -LiteralPath $npmrc) {
        $cur = Get-Content -LiteralPath $npmrc -ErrorAction SilentlyContinue |
               Where-Object { $_ -notmatch '^\s*registry=' }
        $lines = @($cur + $lines)
    }
    Set-Content -LiteralPath $npmrc -Value $lines -Encoding ASCII
    $env:ELECTRON_MIRROR = 'https://registry.npmmirror.com/-/binary/electron/'
    $env:npm_config_electron_mirror = $env:ELECTRON_MIRROR
    $env:electron_mirror = $env:ELECTRON_MIRROR
}

# ---- 选择 Python ------------------------------------------------------
# backend-requirements.txt 里的 contourpy/numpy 等 pin 已要求 Python >= 3.11，
# 这里按 3.12 > 3.11 > 3.10 的优先级挑选可用的解释器。
function Select-Python {
    $cands = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in @('3.12', '3.11', '3.10')) {
            try {
                $p = & $py.Source "-$v" -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $p) { $cands += $p.Trim() }
            } catch {}
        }
    }
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath) {
        try {
            $ver = & $onPath.Source -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            if ($ver -match '^(3\.(1[12]))$') { $cands += $onPath.Source }
        } catch {}
    }
    foreach ($v in @('3.12', '3.11', '3.10')) {
        $hit = $cands | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Where-Object {
            try { (& $_ -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null) -eq $v } catch { $false }
        } | Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

# ---- 静态资源预置 -----------------------------------------------------
# 这些资源原本由 vite / pnpm 的 postinstall 在 node 里下载，
# 在部分网络下 node fetch 会长时间卡死。这里用 .NET 直接落到缓存目录。
function Seed-Assets {
    param([string]$Root)

    $airi = Join-Path $Root 'airi'
    $cache = Join-Path $airi '.cache'
    $assets = Join-Path $airi 'packages\stage-ui\src\assets'
    $vrmModels = Join-Path $airi 'packages\stage-ui-three\src\assets\vrm\models'

    $targets = @(
        # (缓存相对目录, 文件名, URL, 最终落地目录)
        @{ Rel = 'vrm\models\AvatarSample-A'; File = 'AvatarSample_A.vrm'; Url = 'https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-A/AvatarSample_A.vrm'; Dest = $null },
        @{ Rel = 'vrm\models\AvatarSample-B'; File = 'AvatarSample_B.vrm'; Url = 'https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-B/AvatarSample_B.vrm'; Dest = $null }
    )

    foreach ($t in $targets) {
        $out = Join-Path (Join-Path $cache $t.Rel) $t.File
        if ((Test-Path -LiteralPath $out) -and (Get-Item -LiteralPath $out).Length -gt 1MB) { continue }
        Step "预取 $($t.File) ..."
        if (Get-RemoteFile -Url $t.Url -OutFile $out) { Ok "$($t.File) 已缓存" }
    }

    # 宜小智主角模型（仓库被 .gitignore 排除，需从原 ZIP 拷入；
    # 缺失时用公开 VRM 样例占位，保证 3D 舞台能正常渲染）
    $yxz = Join-Path $vrmModels 'yxz.vrm'
    if (-not ((Test-Path -LiteralPath $yxz) -and (Get-Item -LiteralPath $yxz).Length -gt 1MB)) {
        Step '预取 yxz.vrm（宜小智主角模型占位）...'
        $src = Join-Path $cache 'vrm\models\AvatarSample-A\AvatarSample_A.vrm'
        if (Test-Path -LiteralPath $src) {
            New-Item -ItemType Directory -Force -Path $vrmModels | Out-Null
            Copy-Item -LiteralPath $src -Destination $yxz -Force
            Warn '未找到原版宜小智 yxz.vrm，已用公开 VRM 样例占位（3D 可渲染，形象非原版）'
        }
    }

    # MediaPipe 视觉模型（postinstall 用 node 下载，同样容易卡住）
    $mp = Join-Path $airi 'packages\model-driver-mediapipe\tasks\assets'
    $mpTargets = @(
        @{ File = 'pose_landmarker_lite.task'; Url = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task' },
        @{ File = 'hand_landmarker.task'; Url = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task' },
        @{ File = 'face_landmarker.task'; Url = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' }
    )
    foreach ($t in $mpTargets) {
        $out = Join-Path $mp $t.File
        if ((Test-Path -LiteralPath $out) -and (Get-Item -LiteralPath $out).Length -gt 100KB) { continue }
        Step "预取 $($t.File) ..."
        if (Get-RemoteFile -Url $t.Url -OutFile $out) { Ok "$($t.File) 已缓存" }
    }
}

# =====================================================================
#  uv 加速层
#
#  为什么换 uv：pip 的新版解析器在 backend-requirements.txt 这种
#  "全量 freeze 快照"上会做指数级回溯（实测卡在 aiohttp 上回溯
#  10 分钟仍未收敛）。uv 是 Rust 写的解析器，同一份文件 5 秒出结果，
#  下载并行、支持断点续传。
# =====================================================================

function Get-UvPath {
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    $cands = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\Scripts\uv.exe'),
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe')
    )
    foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { return $c } }
    return $null
}

# 统一封装 "往指定 venv 里装包"：
#   - 有 uv  -> uv pip install（快）
#   - 无 uv  -> 回退 pip（慢，但保证能用）
function Install-Packages {
    param(
        [Parameter(Mandatory = $true)][string]$VenvPy,
        [Parameter(Mandatory = $true)][string[]]$Requirement,
        [string[]]$ExtraArgs = @(),
        [string]$IndexUrl = '',
        [string]$ExtraIndexUrl = '',
        [switch]$NoDeps
    )
    $uv = Get-UvPath
    if ($uv) {
        $uvArgs = @('pip', 'install', '--python', $VenvPy)
        if ($NoDeps) { $uvArgs += '--no-deps' }
        if ($IndexUrl)      { $uvArgs += @('--index-url', $IndexUrl) }
        if ($ExtraIndexUrl) { $uvArgs += @('--extra-index-url', $ExtraIndexUrl) }
        $uvArgs += $ExtraArgs
        $uvArgs += $Requirement
        & $uv @uvArgs
        return $LASTEXITCODE
    }
    $pipArgs = @('-m', 'pip', 'install')
    if ($NoDeps) { $pipArgs += '--no-deps' }
    if ($IndexUrl)      { $pipArgs += @('--index-url', $IndexUrl) }
    if ($ExtraIndexUrl) { $pipArgs += @('--extra-index-url', $ExtraIndexUrl) }
    $pipArgs += $ExtraArgs
    $pipArgs += $Requirement
    & $VenvPy @pipArgs
    return $LASTEXITCODE
}

# ---- 缓存目录（跨版本复用，避免每次重下 2.4GB 的 torch）--------------
function Get-CacheRoot {
    if ($env:YXZ_CACHE_DIR) { return $env:YXZ_CACHE_DIR }
    return (Join-Path $env:LOCALAPPDATA 'yxz-3d-cache')
}

function Get-WheelCacheDir {
    $d = Join-Path (Get-CacheRoot) 'wheels'
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    return $d
}

# ---- 找一个空闲端口 ----------------------------------------------------
function Get-FreePort {
    param([int]$Preferred = 8000, [int]$MaxTry = 60)
    $listening = Get-ListeningPorts
    for ($i = 0; $i -lt $MaxTry; $i++) {
        $p = $Preferred + $i
        if (-not $listening.Contains($p)) {
            try {
                $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $p)
                $l.Start(); $l.Stop()
                return $p
            } catch { continue }
        }
    }
    return $null
}

# ---- 哈希（用于断点续装的变更检测）------------------------------------
function Get-FileSha256 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-TextSha256 {
    param([string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '')
    } finally { $sha.Dispose() }
}
# ---- 断点续传下载（.NET Range 请求）----------------------------------
# 大文件（模型权重 4GB+）用 pip / node fetch 在国内经常中途卡死，
# 这里用 HttpWebRequest + Range 头做真正的续传：失败只重试剩余部分。
function Get-RemoteFileResumable {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$MaxAttempts = 60,
        [int]$ChunkReportMB = 512
    )
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $part = "$OutFile.part"

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $have = 0L
        if (Test-Path -LiteralPath $part) { $have = (Get-Item -LiteralPath $part).Length }
        try {
            $req = [Net.HttpWebRequest]::Create($Url)
            $req.UserAgent = 'Mozilla/5.0'
            $req.Timeout = 60000
            $req.ReadWriteTimeout = 120000
            if ($have -gt 0) { $req.AddRange([long]$have) }
            $resp = $req.GetResponse()
            $total = -1L
            $cr = $resp.Headers['Content-Range']
            if ($cr -and $cr -match '/(\d+)$') { $total = [long]$Matches[1] }
            elseif ($resp.ContentLength -gt 0 -and $have -eq 0) { $total = $resp.ContentLength }

            $src = $resp.GetResponseStream()
            $mode = if ($have -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $dst = [IO.File]::Open($part, $mode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            try {
                $buf = New-Object byte[] (4 * 1024 * 1024)
                $got = 0L
                $lastReport = 0L
                while (($n = $src.Read($buf, 0, $buf.Length)) -gt 0) {
                    $dst.Write($buf, 0, $n); $got += $n
                    if (($got - $lastReport) -ge ($ChunkReportMB * 1MB)) {
                        $lastReport = $got
                        $pct = if ($total -gt 0) { " ($([math]::Round(100.0 * ($have + $got) / $total))%)" } else { '' }
                        Write-Host ("      ... {0} MB{1}" -f [math]::Round(($have + $got)/1MB,0), $pct) -ForegroundColor DarkGray
                    }
                }
            } finally { $dst.Close(); $src.Close(); $resp.Close() }

            $size = (Get-Item -LiteralPath $part).Length
            if ($total -gt 0 -and $size -lt $total) { throw "不完整：$size / $total" }
            Move-Item -LiteralPath $part -Destination $OutFile -Force
            return $true
        } catch {
            Warn "  第 $attempt 次下载中断（$($_.Exception.Message)），5 秒后续传..."
            Start-Sleep -Seconds 5
        }
    }
    return $false
}
# ---- 找出本项目已经在跑的实例（跨端口扫描）---------------------------
# 只看“首选端口”不够：用户多双击几次就会在 8001/8002/... 上留下
# 一堆僵尸后端。这里按端口区间扫描，用 openapi 里的项目标识认人。
function Find-ProjectBackend {
    param([int]$From = 8000, [int]$To = 8030)
    $listening = Get-ListeningPorts
    for ($p = $From; $p -le $To; $p++) {
        if (-not $listening.Contains($p)) { continue }
        if (Test-BackendIdentity "http://127.0.0.1:$p") { return $p }
    }
    return $null
}

function Find-ProjectFrontend {
    param([int]$From = 5199, [int]$To = 5230)
    $listening = Get-ListeningPorts
    for ($p = $From; $p -le $To; $p++) {
        if (-not $listening.Contains($p)) { continue }
        if (Test-FrontendIdentity "http://127.0.0.1:$p") { return $p }
    }
    return $null
}

# ---- AIRI server-runtime（WS 通道服务）--------------------------------
# 这个服务只在 /ws 上提供 WebSocket，普通 HTTP 请求会回 404，
# 所以没法用响应体当身份标识。改用「端口在监听 + 占用进程的命令行
# 指向 server-runtime 的 run.js」双重判定，避免误杀别的程序。
function Test-ServerRuntimeIdentity {
    param([int]$Port = 6121)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return $false }
    foreach ($c in $conns) {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd -and ($cmd -match 'server-runtime' -or $cmd -match 'src[\\/]bin[\\/]run\.(js|mjs)')) {
            return $true
        }
    }
    return $false
}

function Find-ProjectServerRuntime {
    param([int]$From = 6121, [int]$To = 6130)
    for ($p = $From; $p -le $To; $p++) {
        if (Test-ServerRuntimeIdentity -Port $p) { return $p }
    }
    return $null
}

function Get-YxzPowerShell {
    # 目标机器不一定装了 PowerShell 7（pwsh）。Windows 10/11 自带的是
    # Windows PowerShell 5.1，脚本本身没有用 7 独有的语法，所以 5.1 也能跑。
    # 这里做一层兜底：新电脑只有 5.1 时，调用子脚本不要再硬写 pwsh，
    # 否则"自动装依赖"这一步会直接 command not found，装不上也起不来。
    $ps7 = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($ps7) { return $ps7.Source }
    $ps5 = Get-Command powershell -ErrorAction SilentlyContinue
    if ($ps5) { return $ps5.Source }
    return $null
}
