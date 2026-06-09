# stop_bot.ps1
$ErrorActionPreference = 'SilentlyContinue'

$AppName = 'azuris-bot'

Write-Host "===============================================" -ForegroundColor Yellow
Write-Host "  Azuris Discord Bot - Stopping Bot Processes" -ForegroundColor Yellow
Write-Host "===============================================" -ForegroundColor Yellow

# Lấy đường dẫn root của project
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRootNorm = $ProjectRoot.Replace('\', '/').ToLower()

# 1. Dừng ứng dụng trong PM2 nếu có sử dụng PM2
$pm2Cmd = Get-Command pm2 -ErrorAction SilentlyContinue
if ($null -ne $pm2Cmd) {
    Write-Host "[INFO] PM2 detected. Checking PM2 status for '$AppName'..."
    # Kiểm tra xem app có tồn tại trong pm2 list không
    $pm2Status = & pm2 jlist 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
    $hasApp = $false
    if ($pm2Status) {
        foreach ($app in $pm2Status) {
            if ($app.name -eq $AppName) {
                $hasApp = $true
                break
            }
        }
    }
    
    if ($hasApp) {
        Write-Host "[INFO] Stopping and deleting '$AppName' from PM2..." -ForegroundColor Yellow
        & pm2 stop $AppName 2>$null | Out-Null
        & pm2 delete $AppName 2>$null | Out-Null
        Write-Host "[OK] Stopped and deleted '$AppName' from PM2." -ForegroundColor Green
    } else {
        Write-Host "[INFO] No active PM2 application named '$AppName' found."
    }
}

# 2. Tìm và diệt tất cả tiến trình Python liên quan đến dự án
Write-Host "[INFO] Finding running bot Python processes..."
$processes = Get-CimInstance Win32_Process -Filter "name = 'python.exe' or name = 'pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $cmd = $_.CommandLine
    $path = $_.ExecutablePath
    
    $cmdNorm = if ($cmd) { $cmd.Replace('\', '/').ToLower() } else { "" }
    $pathNorm = if ($path) { $path.Replace('\', '/').ToLower() } else { "" }
    
    # Chỉ lọc các tiến trình thuộc thư mục dự án này
    $cmdNorm.Contains($ProjectRootNorm) -or $pathNorm.Contains($ProjectRootNorm)
}

if ($processes) {
    Write-Host "[INFO] Found running BOT processes. Showing details for 3 seconds..." -ForegroundColor Cyan
    $processes | Select-Object ProcessId, CommandLine | Format-Table -AutoSize
    Start-Sleep -Seconds 3
    
    $procList = @($processes)
    Write-Host "[INFO] Stopping $($procList.Count) BOT process(es)..."
    foreach ($p in $procList) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "[OK] Stopped BOT process ID: $($p.ProcessId)" -ForegroundColor Green
        }
        catch {
            Write-Host "[WARN] Failed to stop process ID: $($p.ProcessId)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[OK] No running bot processes found in project directory." -ForegroundColor Green
}

Write-Host "===============================================" -ForegroundColor Yellow
Write-Host "  Cleanup complete." -ForegroundColor Yellow
Write-Host "===============================================" -ForegroundColor Yellow
