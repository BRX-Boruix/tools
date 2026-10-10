$ErrorActionPreference = "Continue"
function Measure-Arm([string]$label, [bool]$noSound, [string[]]$extra) {
  Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  if ($noSound) { $env:BORUIX_NO_SOUND = "1" } else { Remove-Item Env:BORUIX_NO_SOUND -ErrorAction SilentlyContinue }
  Remove-Item Env:BORUIX_INIT_RUN -ErrorAction SilentlyContinue
  $log = "F:\boruix-project\.tmp-idle2-$label.log"
  $args = @("tools\main.py","br","--serial","--redisk","--mem","1024M") + $extra
  $proc = Start-Process -FilePath "python" -ArgumentList $args -WorkingDirectory "F:\boruix-project" -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -NoNewWindow
  Start-Sleep -Seconds 100
  $q = Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $q) { "ARM $label : NO QEMU"; return }
  $t0 = $q.TotalProcessorTime; $w0 = Get-Date
  Start-Sleep -Seconds 60
  $q.Refresh(); $t1 = $q.TotalProcessorTime; $w1 = Get-Date
  $cpu = ($t1 - $t0).TotalSeconds; $wall = ($w1 - $w0).TotalSeconds
  "ARM $label : cores={0:N2} cpu_s={1:N1} wall_s={2:N1}" -f ($cpu / $wall), $cpu, $wall
  Stop-Process -Force -Id $q.Id -ErrorAction SilentlyContinue
  Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
}
Measure-Arm "no-hda" $true @()
Measure-Arm "no-hda-nosmp" $true @("--no-smp")
"IDLE2 DONE"