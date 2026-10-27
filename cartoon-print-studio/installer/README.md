# Cartoon Print Studio field installer

## Build

On the development PC:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

The build creates a new timestamped `release\<version>\` directory without touching this checkout's existing `dist`, `build`, or user data. It produces:

- `CartoonPrintStudio\` for local smoke testing.
- `CartoonPrintStudio-Portable.zip` for copying to other Windows PCs.

The archive contains the application, one offline demo model, and `install.ps1`. It never contains this PC's `keys.txt`, works, logs, or generated models.

## Install on each PC

1. Copy `CartoonPrintStudio-Portable.zip` to the PC and extract it. The archive contains `CartoonPrintStudio\` and `install.ps1` side by side.
2. Run `install.ps1` from the extracted folder. If script execution is restricted, use:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

3. Start **Cartoon Print Studio** from the desktop shortcut.
4. Add that PC's authorized provider keys to `%LOCALAPPDATA%\CartoonPrintStudio\keys.txt` if cloud preview, prompt polish, or Tripo is required.

Each PC has an independent install, API-key file, project library, software paths, and generated models. Upgrades replace application files but preserve `keys.txt`, `data\projects`, generated user sessions, logs, and other local files. The bundled demo is copied only when that PC does not already have it.

## Requirements and capability boundaries

- Windows 10/11 x64 and Microsoft Edge WebView2 Runtime for the native window.
- Network access and separately authorized API keys for cloud image generation and Tripo.
- Bambu Studio and xTool Studio are detected per PC. Model delivery opens STL in the slicer; laser delivery opens the current canvas composition as PNG. Confirm settings inside those applications; printing and cutting are never started automatically.
- The offline demo, workbench editing, project saving, model viewing, and local cartoon-relief generation do not consume cloud credits. Hunyuan3D and TripoSR require local model weights and a compatible GPU and are not guaranteed by the small field bundle.

## Remove

Uninstall the application by removing `%LOCALAPPDATA%\CartoonPrintStudio` and its desktop shortcut. Back up `data\projects` first if those local works are needed.
