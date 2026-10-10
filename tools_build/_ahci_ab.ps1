$ErrorActionPreference = "Continue"
# AHCI vs PIO A/B：把盘挂到 ich9-ahci（DMA）跑同一条 readbench + tcc 链接命令。
# 必须**轮询到 run exited 就杀掉 QEMU**——否则 br 会一直等一个不会退出的客户机（本脚本第一版就挂住了）。
param([string]$label = "ahci")
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo A1 && tcc readbench.c -o readbench && echo A2 && ./readbench && echo B1 && now && tcc src/cowsay/cowsay.c -o cowsay_t && echo L_OK && now && ./cowsay_t -w 20 hi && echo ALL_DONE"
$log = "F:\boruix-project\.tmp-ahciab-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "python" -ArgumentList "tools\main.py","br","--serial","--redisk","--mem","1024M","--ahci" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
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
Get-Content $log -Encoding UTF8 | Select-String -Pattern "readbench|now:|L_OK|ALL_DONE|run exited|registered via AHCI|already claimed" | ForEach-Object { $_.Line }
"AHCIAB $label DONE"
