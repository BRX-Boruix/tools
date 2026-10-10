param([string]$label = "ahci", [switch]$ahci)
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "echo GRAN_DONE"
$log = "F:\boruix-project\.tmp-gran-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$cargs = @("tools/main.py","br","--test","--serial","--redisk","--mem","1024M")
if ($ahci) { $cargs += "--ahci" }
$proc = Start-Process -FilePath "python" -ArgumentList $cargs -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(900)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 400
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "test-ahci7] (PASS|FAIL)|panicked at|assertion .+ failed" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "test-ahci7|panicked at|assertion .+ failed|left:|right:" | ForEach-Object { $_.Line }
"GRAN $label DONE"