$ErrorActionPreference = "Continue"
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$env:BORUIX_NO_SOUND = "1"
Remove-Item Env:BORUIX_INIT_RUN -ErrorAction SilentlyContinue
$log = "F:\boruix-project\.tmp-fw.log"
$proc = Start-Process -FilePath "python" -ArgumentList "tools\main.py","br","--serial","--redisk","--mem","1024M","--no-smp" -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
$q = $null
for ($i = 0; $i -lt 180 -and -not $q; $i++) { Start-Sleep -Seconds 1; $q = Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (-not $q) { "NO QEMU"; return }
$t0 = $q.TotalProcessorTime; $w0 = Get-Date
Start-Sleep -Seconds 20
$q.Refresh(); $t1 = $q.TotalProcessorTime; $w1 = Get-Date
"EARLY (firmware+early boot, 20s): cores={0:N2} cpu_s={1:N1}" -f ((($t1 - $t0).TotalSeconds) / (($w1 - $w0).TotalSeconds)), ($t1 - $t0).TotalSeconds
Start-Sleep -Seconds 60
$q.Refresh(); $t2 = $q.TotalProcessorTime; $w2 = Get-Date
Start-Sleep -Seconds 60
$q.Refresh(); $t3 = $q.TotalProcessorTime; $w3 = Get-Date
"IDLE (after boot, 60s): cores={0:N2} cpu_s={1:N1}" -f ((($t3 - $t2).TotalSeconds) / (($w3 - $w2).TotalSeconds)), ($t3 - $t2).TotalSeconds
"log lines=" + (Get-Content $log).Count
Stop-Process -Force -Id $q.Id -ErrorAction SilentlyContinue
Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
"FW DONE"