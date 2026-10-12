param([string]$label = "mu")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && tcc mode_umask_check.c -o mode_umask_check && ./mode_umask_check"
$log = "F:\boruix-project\.tmp-mu-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList @("tools/main.py","br","--serial","--redisk","--mem","1024M","--ahci") -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(700)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code|mode_umask_check: fails" -Quiet) { Start-Sleep -Seconds 8; break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "ok  |FAIL|mode_umask_check|run exited|PANIC|error:" | ForEach-Object { $_.Line }
"MU $label DONE"