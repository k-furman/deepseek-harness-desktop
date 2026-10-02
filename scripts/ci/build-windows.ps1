param(
    # Installation changes the disposable CI machine. Local packaging skips it.
    [switch]$VerifyInstallers
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'Windows x64 with the Rust MSVC toolchain is required.'
}
New-Item -ItemType Directory -Force artifacts/ci | Out-Null
$cargoInfo = & node scripts/with-rust.mjs cargo -vV
if ($LASTEXITCODE -ne 0 -or $cargoInfo -notcontains 'host: x86_64-pc-windows-msvc') {
    throw 'Use the x86_64-pc-windows-msvc Rust host toolchain.'
}

& npm.cmd run desktop:build -- --ci --config src-tauri/tauri.windows.conf.json --bundles 'nsis,msi' -- --locked
if ($LASTEXITCODE -ne 0) { throw "Windows build failed: $LASTEXITCODE" }

function Invoke-Installer([string]$File, [string]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru
    try {
        if (-not $process.WaitForExit(300000)) {
            $process.Kill()
            throw "Installer timed out: $File"
        }
        if ($process.ExitCode -notin @(0, 3010)) { throw "Installer failed ($File): $($process.ExitCode)" }
    } finally { $process.Dispose() }
}

function Test-Window([string]$Binary) {
    if (-not (Test-Path $Binary)) { throw "Installed application is missing: $Binary" }
    $process = Start-Process -FilePath $Binary -PassThru
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 200
            $process.Refresh()
            if ($process.HasExited) { throw 'Application exited before creating a window.' }
        } while ($process.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $deadline)
        if ($process.MainWindowHandle -eq 0 -or $process.MainWindowTitle -ne 'DeepSeek Harness Desktop') {
            throw 'The installed application did not create its main window.'
        }
        # A native window alone cannot prove that the connection form rendered.
        Write-Host "Native startup passed: $Binary"
        if (-not $process.CloseMainWindow() -or -not $process.WaitForExit(10000)) {
            throw 'Closing the main window did not exit the Windows application.'
        }
        if ($process.ExitCode -ne 0) { throw "Application exited with $($process.ExitCode)." }
    } finally {
        if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
        $process.Dispose()
    }
}

if ($VerifyInstallers) {
    # Run this only on a disposable Windows runner/VM, never on a user's workstation.
    $msi = @(Get-ChildItem src-tauri/target/release/bundle/msi/*.msi)
    $nsis = @(Get-ChildItem src-tauri/target/release/bundle/nsis/*-setup.exe)
    if ($msi.Count -ne 1 -or $nsis.Count -ne 1) { throw 'Expected one MSI and one NSIS installer.' }
    $sandbox = Join-Path $root 'artifacts/ci/installer test'
    $msiDirectory = Join-Path $sandbox 'MSI'
    $nsisDirectory = Join-Path $sandbox 'NSIS'
    $installLog = Join-Path $root 'artifacts/ci/msi-install.log'
    $uninstallLog = Join-Path $root 'artifacts/ci/msi-uninstall.log'
    New-Item -ItemType Directory -Force $sandbox | Out-Null
    $msiInstalled = $false
    try {
        Invoke-Installer 'msiexec.exe' "/i `"$($msi[0].FullName)`" /qn /norestart INSTALLDIR=`"$msiDirectory`" /L*v `"$installLog`""
        $msiInstalled = $true
        Test-Window (Join-Path $msiDirectory 'deepseek-harness-desktop.exe')
    } finally {
        if ($msiInstalled) {
            Invoke-Installer 'msiexec.exe' "/x `"$($msi[0].FullName)`" /qn /norestart /L*v `"$uninstallLog`""
        }
    }
    if (Test-Path (Join-Path $msiDirectory 'deepseek-harness-desktop.exe')) { throw 'MSI uninstall left the application binary.' }
    try {
        # NSIS requires /D to be last, with no inner quotes, even for paths with spaces.
        Invoke-Installer $nsis[0].FullName "/S /D=$nsisDirectory"
        Test-Window (Join-Path $nsisDirectory 'deepseek-harness-desktop.exe')
    } finally {
        $uninstaller = Join-Path $nsisDirectory 'uninstall.exe'
        if (Test-Path $uninstaller) {
            Invoke-Installer $uninstaller "/S _?=$nsisDirectory"
        }
    }
    if (Test-Path (Join-Path $nsisDirectory 'deepseek-harness-desktop.exe')) { throw 'NSIS uninstall left the application binary.' }
    $env:DSH_WINDOWS_INSTALLER_VERIFIED = '1'
} else {
    $env:DSH_WINDOWS_INSTALLER_VERIFIED = '0'
}

& python scripts/ci/release.py collect --platform windows
if ($LASTEXITCODE -ne 0) { throw "Windows package validation failed: $LASTEXITCODE" }
