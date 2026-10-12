param([string]$label = "lc")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "libccheck"
$log = "F:\boruix-project\.tmp-lc2-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList @("tools/main.py","br","--serial","--redisk","--mem","1024M","--ahci") -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(1300)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code" -Quiet) { Start-Sleep -Seconds 12; break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "grp:|zero-capacity|run exited|libccheck|PANIC|CPU EXCEPTION" | Select-Object -Last 30 | ForEach-Object { $_.Line }
"LC2 $label DONE"