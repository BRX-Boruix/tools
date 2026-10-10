$ErrorActionPreference = "Continue"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Copy-Item F:\boruix-project\tcc-on-boruix\_build\tcc.elf F:\boruix-project\tools\diskfiles\3p\tcc.elf -Force
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED_TCC=HAS_MARKER" } else { "STAGED_TCC=NO_MARKER" }
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo P1_COMPILE_ONLY && tcc -c src/cowsay/cowsay.c -o /volumes/BORUIX_DATA/3p/c.o && echo P1_DONE && echo P2_LINK && tcc src/cowsay/cowsay.c -o cowsay_t && echo P2_DONE && echo P3_LINK_OBJ && tcc /volumes/BORUIX_DATA/3p/c.o -o cowsay_t2 && echo P3_DONE"
$log = "F:\boruix-project\.tmp-profrun2.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList "tools\main.py","br","--serial","--redisk","--mem","1024M" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$dl = (Get-Date).AddSeconds(540)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 300
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    if ($c | Select-String -Pattern "run exited with code" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log | Select-String -Pattern "TCCPROF|P1_|P2_|P3_|run exited|tcc:|error" | ForEach-Object { $_.Line }
"PROF2 DONE"
