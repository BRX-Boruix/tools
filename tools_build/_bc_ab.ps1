param([string]$label = "ahci", [switch]$ahci, [switch]$nosmp)
$ErrorActionPreference = "Continue"
# Block-cache group-prefetch A/B: same readbench, reads a 5 MB file twice, reports cyc/byte.
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo B1 && tcc readbench.c -o readbench && echo B2 && ./readbench && echo BC_DONE"
$log = "F:\boruix-project\.tmp-bc-$label.log"
Remove-Item $log -ErrorAction SilentlyContinue
$cargs = @("tools/main.py","br","--serial","--redisk","--mem","1024M")
if ($ahci) { $cargs += "--ahci" }
# -nosmp：绕开既有的内核并发异常（该异常需要两个核同时出错；单核下不再出现）。
# 前后两侧必须用同一开关，否则对比无效。
if ($nosmp) { $cargs += "--no-smp" }
$proc = Start-Process -FilePath "python" -ArgumentList $cargs -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
# 上限 330s：成功一次约 2.5 分钟；失败（既有内核异常会让工作负载静默死掉、串口
# 不再有 'run exited'）时不必白等 10 分钟。
$dl = (Get-Date).AddSeconds(330)
while ((Get-Date) -lt $dl) {
  Start-Sleep -Milliseconds 400
  if (Test-Path $log) {
    $c = Get-Content $log -ErrorAction SilentlyContinue
    # 断点必须用**命令输出**里的字符串，不能用命令本身里出现的字符串：INIT_RUN 的
    # 回显行（[init] running non-interactive command: ... echo BC_DONE）会被原样打进
    # 串口，用 "BC_DONE" 作断点会在命令真正执行前就退出（实测：QEMU 被杀、readbench
    # 一行输出都没有）。
    if ($c | Select-String -Pattern "readbench pass2|run exited with code" -Quiet) { break }
  }
}
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Content $log -Encoding UTF8 | Select-String -Pattern "readbench pass|registered via AHCI|already claimed|run exited" | ForEach-Object { $_.Line }
"BC $label DONE"