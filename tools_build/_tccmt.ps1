param([string]$label = "mt")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && ./tccmt.elf"
$log = "F:\boruix-project\.tmp-mt-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList @("tools/main.py","br","--serial","--redisk","--mem","1024M","--ahci") -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(900)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code|tccmt\] PASS|tccmt\] FAIL" -Quiet) { Start-Sleep -Seconds 10; break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "tccmt|run exited|PANIC" | Select-Object -Last 22 | ForEach-Object { $_.Line }
"MT $label DONE"