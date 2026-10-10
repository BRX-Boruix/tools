$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && tcc dircount.c -o dircount && cd /volumes/BORUIX_DATA && mkdir tdir2 && cd tdir2 && touch ok1 /volumes/BORUIX_DATA/nodir/bad ok2 && echo RC0 ; echo AFTER ; /volumes/BORUIX_DATA/3p/dircount /volumes/BORUIX_DATA/tdir2 2 ; echo ALL_DONE"
$log = "F:\boruix-project\.tmp-touch-partial2.log"
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
Get-Content $log -Encoding UTF8 | Select-String -Pattern "touch|RC0|AFTER|dircount|ALL_DONE|run exited" | ForEach-Object { $_.Line }
"TOUCH partial2 DONE"
