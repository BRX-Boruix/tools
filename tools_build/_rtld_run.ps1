param([string]$label)
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$log = "F:\boruix-project\.tmp-rtld-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList "tools\main.py","br","--serial","--redisk","--mem","1024M" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(420)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 300
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log | Select-String -Pattern "R1|R2|noload:|dlclose:|rtld\]|run exited|error" | ForEach-Object { $_.Line }
"RTLD-RUN $label DONE"
