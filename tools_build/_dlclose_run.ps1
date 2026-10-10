param([string]$label = "dlclose")
$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$env:BORUIX_INIT_RUN = "/volumes/BORUIX_DATA/3p/rtld.elf /volumes/BORUIX_DATA/3p/dlclose_prog.elf"
$log = "F:\boruix-project\.tmp-dlclose-" + $label + ".log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList "tools/main.py","br","--serial","--redisk","--mem","1024M" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(600)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 400
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "rtld\]|dlclose:|run exited|panic|fault" | ForEach-Object { $_.Line }
"dlclose DONE"