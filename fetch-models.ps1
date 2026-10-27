# =====================================================================
#  宜小智工作台 —— AI 模型权重下载
#
#  仓库里没有这些权重（被 .gitignore 排除，只随作者发布的 zip 提供）。
#  缺了它们：本地生图 / 本地 3D 生成都不可用，只能走云端 key。
#
#  走 hf-mirror.com 国内镜像 + .NET Range 断点续传：
#    - 直连 huggingface.co 在国内基本连不上
#    - 文件走 xet CDN，普通下载工具中途会卡死，这里用 Range 续传扛住
#
#  用法：
#    pwsh -NoProfile -ExecutionPolicy Bypass -File fetch-models.ps1
#    pwsh -NoProfile -ExecutionPolicy Bypass -File fetch-models.ps1 -Only sd
#    pwsh -NoProfile -ExecutionPolicy Bypass -File fetch-models.ps1 -Mirror https://huggingface.co
# =====================================================================
param(
    [string]$Mirror = 'https://hf-mirror.com',
    [ValidateSet('all','sd','hunyuan','triposr')][string]$Only = 'all',
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib-common.ps1')

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  AI 模型权重下载" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

function Want { param([string]$name) return ($Only -eq 'all' -or $Only -eq $name) }

function Fetch {
    param(
        [string]$Repo,          # hf 仓库名
        [string]$File,          # 仓库内路径
        [string]$OutFile,       # 本地落地路径
        [long]$MinSize = 0,     # 已存在且大于该大小就跳过
        [string]$Label = ''
    )
    if ((Test-Path -LiteralPath $OutFile) -and -not $Force) {
        $len = (Get-Item -LiteralPath $OutFile).Length
        if ($len -ge $MinSize -and $len -gt 0) {
            Ok "$Label 已存在（$([math]::Round($len/1MB,1)) MB），跳过"
            return $true
        }
    }
    $url = "$Mirror/$Repo/resolve/main/$File"
    $name = if ($Label) { $Label } else { $File }
    Step "下载 $name ..."
    $ok = Get-RemoteFileResumable -Url $url -OutFile $OutFile
    if ($ok) { Ok "$name 完成（$([math]::Round((Get-Item -LiteralPath $OutFile).Length/1MB,1)) MB）" }
    else { Fail "$name 下载失败：$url" }
    return $ok
}

# ---------- 1. Stable Diffusion 1.5（本地生图）-------------------------
if (Want 'sd') {
    $sdRoot = Join-Path $root 'cartoon-print-studio\ai\forge-webui\models\Stable-diffusion'
    $cfgRoot = Join-Path $root 'cartoon-print-studio\ai\forge-webui\backend\huggingface\runwayml\stable-diffusion-v1-5'
    Fetch -Repo 'stable-diffusion-v1-5/stable-diffusion-v1-5' `
          -File 'v1-5-pruned-emaonly.safetensors' `
          -OutFile (Join-Path $sdRoot 'v1-5-pruned-emaonly.safetensors') `
          -MinSize 4000000000 -Label 'SD 1.5 权重'

    # diffusers 结构配置（模型_index / unet / vae / text_encoder / tokenizer / scheduler）
    $cfgFiles = @(
        'model_index.json',
        'feature_extractor/preprocessor_config.json',
        'safety_checker/config.json',
        'scheduler/scheduler_config.json',
        'text_encoder/config.json',
        'tokenizer/merges.txt',
        'tokenizer/special_tokens_map.json',
        'tokenizer/tokenizer_config.json',
        'tokenizer/vocab.json',
        'unet/config.json',
        'vae/config.json'
    )
    foreach ($f in $cfgFiles) {
        $out = Join-Path $cfgRoot ($f -replace '/', '\')
        $url = "$Mirror/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/$f"
        if ((Test-Path -LiteralPath $out) -and -not $Force) { continue }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
        if (-not (Get-RemoteFile -Url $url -OutFile $out)) { Fail "下载失败：$f" }
    }
    Ok "SD 1.5 配置就绪"
}

# ---------- 2. Hunyuan3D-2 mini（本地 3D 生成）-------------------------
# 代码里写死找 ~/.cache/huggingface/hub/models--tencent--Hunyuan3D-2mini/snapshots/*/
if (Want 'hunyuan') {
    $snap = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--tencent--Hunyuan3D-2mini\snapshots\main'
    $dir  = Join-Path $snap 'hunyuan3d-dit-v2-mini'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Fetch -Repo 'tencent/Hunyuan3D-2mini' -File 'hunyuan3d-dit-v2-mini/model.fp16.safetensors' `
          -OutFile (Join-Path $dir 'model.fp16.safetensors') -MinSize 3600000000 -Label 'Hunyuan3D-2 mini 权重'
    Fetch -Repo 'tencent/Hunyuan3D-2mini' -File 'hunyuan3d-dit-v2-mini/config.yaml' `
          -OutFile (Join-Path $dir 'config.yaml') -MinSize 1000 -Label 'Hunyuan3D 配置'
}

# ---------- 3. TripoSR（3D 生成兜底 / 低显存）--------------------------
if (Want 'triposr') {
    $dir = Join-Path $root 'cartoon-print-studio\models\cache\models\AI-ModelScope--TripoSR\snapshots\master'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Fetch -Repo 'stabilityai/TripoSR' -File 'model.ckpt' `
          -OutFile (Join-Path $dir 'model.ckpt') -MinSize 1500000000 -Label 'TripoSR 权重'
    Fetch -Repo 'stabilityai/TripoSR' -File 'config.yaml' `
          -OutFile (Join-Path $dir 'config.yaml') -MinSize 100 -Label 'TripoSR 配置'
}

Write-Host ""
Ok "模型权重处理完毕。重启后端（stop-all.ps1 → start-all.ps1）即可生效。"