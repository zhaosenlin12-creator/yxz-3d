@echo off
REM 🚀 VRM 模型优化脚本 (Windows 版本)
REM 将 yxz.vrm 从 11.7MB 压缩到 < 8MB

echo ========================================
echo 🚀 宜小智 VRM 模型优化工具
echo ========================================
echo.

set MODEL_DIR=C:\kaifa_senlin\pingdou\pingdou-workstation-final\airi\packages\stage-ui-three\src\assets\vrm\models
set ORIGINAL_MODEL=%MODEL_DIR%\yxz.vrm
set BACKUP_MODEL=%MODEL_DIR%\yxz-original-backup.vrm
set OPTIMIZED_MODEL=%MODEL_DIR%\yxz-optimized.vrm

REM 检查原始模型是否存在
if not exist "%ORIGINAL_MODEL%" (
  echo ❌ 错误: 找不到原始模型 %ORIGINAL_MODEL%
  exit /b 1
)

REM 获取原始文件大小
for %%I in ("%ORIGINAL_MODEL%") do set ORIGINAL_SIZE=%%~zI
set /a ORIGINAL_MB=%ORIGINAL_SIZE% / 1048576
echo 📊 原始模型大小: %ORIGINAL_MB% MB
echo.

REM 备份原始模型
if not exist "%BACKUP_MODEL%" (
  echo 💾 备份原始模型...
  copy "%ORIGINAL_MODEL%" "%BACKUP_MODEL%"
  echo ✅ 已备份到: %BACKUP_MODEL%
) else (
  echo ✅ 备份已存在: %BACKUP_MODEL%
)
echo.

REM 使用 npx gltf-transform 优化模型
echo 🔧 正在优化模型（Draco 压缩 + 纹理优化）...
echo ⏳ 这可能需要 1-2 分钟，请耐心等待...
echo.

npx @gltf-transform/cli optimize ^
  "%ORIGINAL_MODEL%" ^
  "%OPTIMIZED_MODEL%" ^
  --compress draco ^
  --texture-compress webp ^
  --quantize 16 ^
  --prune-unused

if %ERRORLEVEL% equ 0 (
  echo ✅ 优化完成！
  echo.

  REM 获取优化后文件大小
  for %%I in ("%OPTIMIZED_MODEL%") do set OPTIMIZED_SIZE=%%~zI
  set /a OPTIMIZED_MB=%OPTIMIZED_SIZE% / 1048576
  set /a REDUCTION_PCT=100 - (%OPTIMIZED_SIZE% * 100 / %ORIGINAL_SIZE%)

  echo 📊 优化结果:
  echo    原始: %ORIGINAL_MB% MB
  echo    优化后: %OPTIMIZED_MB% MB
  echo    减少: %REDUCTION_PCT%%%
  echo.

  REM 检查是否达到目标 (< 8MB)
  if %OPTIMIZED_MB% LSS 8 (
    echo 🎉 成功！优化后的模型 ^< 8MB，符合目标
    echo.
    echo ℹ️  保留两个版本:
    echo    原始: %ORIGINAL_MODEL%
    echo    优化: %OPTIMIZED_MODEL%
    echo.
    echo 💡 如果测试通过，可以手动替换:
    echo    del "%ORIGINAL_MODEL%"
    echo    rename "%OPTIMIZED_MODEL%" yxz.vrm
  ) else (
    echo ⚠️  警告: 优化后的模型仍然 ^> 8MB
    echo 建议: 使用 Blender 手动减少面数和纹理分辨率
  )
) else (
  echo ❌ 优化失败
  exit /b 1
)

echo.
echo ========================================
echo ✅ 优化完成！
echo ========================================
pause
