param([string]$label = "red")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && tcc dircount.c -o dircount && cd /volumes/BORUIX_DATA && mkdir t3 && cd t3 && mkdir d1 d2 d3 && echo MKDIR_OK ; /volumes/BORUIX_DATA/3p/dircount /volumes/BORUIX_DATA/t3 3 ; touch f1 f2 f3 && echo TOUCH_OK && rm f1 f2 f3 && echo RM_OK ; /volumes/BORUIX_DATA/3p/dircount /volumes/BORUIX_DATA/t3 3 ; echo AAA > c1 && echo BBB > c2 && cat c1 c2 ; echo CAT_DONE ; /volumes/BORUIX_DATA/3p/dircount /volumes/BORUIX_DATA/t3 5 ; echo ALL_DONE"
$log = "F:\boruix-project\.tmp-mrc-$label.log"
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
Get-Content $log -Encoding UTF8 | Select-String -Pattern "MKDIR_OK|TOUCH_OK|RM_OK|CAT_DONE|dircount|AAA|BBB|mkdir:|rm:|cat:|ALL_DONE|run exited" | ForEach-Object { $_.Line }
"MRC $label DONE"
