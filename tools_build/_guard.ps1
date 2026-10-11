param([string]$label = "g1")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "echo GUARD_DONE"
$log = "F:\boruix-project\.tmp-guard-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList @("tools/main.py","br","--test","--serial","--redisk","--mem","1024M","--ahci") -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(700)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "SYSCALL STACK OVERFLOW|test-sguard\] FAIL|KERNEL STACK OVERFLOW|run exited with code" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "test-sguard|SYSCALL STACK OVERFLOW|KERNEL STACK OVERFLOW|slot = |guard pages armed|CPU EXCEPTION" | ForEach-Object { $_.Line }
"GUARD $label DONE"