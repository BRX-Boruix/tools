$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64,rustc,cargo,clang -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
python tools\main.py install --prefix $s *> F:\boruix-project\.tmp-dc-install.log
"INSTALL_RC=$LASTEXITCODE"
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-dc-install.log
"STAGE_RC=$LASTEXITCODE"
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA && mkdir bigdir && cd 3p && tcc dircount.c -o dircount && tcc mkfiles.c -o mkfiles && echo BUILT && ./dircount /volumes/BORUIX_DATA/bigdir && echo E1 && ./mkfiles /volumes/BORUIX_DATA/bigdir 120 && echo MADE && ./dircount /volumes/BORUIX_DATA/bigdir 120 ; echo ALL_DONE"
$log = "F:\boruix-project\.tmp-dc4.log"
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
Get-Content $log -Encoding UTF8 | Select-String -Pattern "dircount|BUILT|^E1|MADE|mkfiles|ALL_DONE|run exited|tcc:" | ForEach-Object { $_.Line }
"DC4 DONE"
