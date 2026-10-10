$ErrorActionPreference = "Continue"
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item Env:BORUIX_NO_SOUND -ErrorAction SilentlyContinue
Remove-Item Env:BORUIX_INIT_RUN -ErrorAction SilentlyContinue
$log = "F:\boruix-project\.tmp-stats.log"
$proc = Start-Process -FilePath "python" -ArgumentList "tools\main.py","br","--serial","--redisk","--mem","1024M" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
Start-Sleep -Seconds 110
$q = Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $q) { "NO QEMU"; return }
$t0 = $q.TotalProcessorTime; $w0 = Get-Date
Start-Sleep -Seconds 95
$q.Refresh(); $t1 = $q.TotalProcessorTime; $w1 = Get-Date
"STATS-ARM cores={0:N2} wall_s={1:N1}" -f ((($t1 - $t0).TotalSeconds) / (($w1 - $w0).TotalSeconds)), ($w1 - $w0).TotalSeconds
Stop-Process -Force -Id $q.Id -ErrorAction SilentlyContinue
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
"STATS DONE"