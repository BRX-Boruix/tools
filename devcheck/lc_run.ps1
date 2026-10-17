<#
.SYNOPSIS
    In-machine acceptance runner: one QEMU boot, run libccheck or kernel selftests,
    then harvest the verdict lines.

.DESCRIPTION
    Replaces the near-identical copies that used to live in a scratch directory
    (lc_run / lc_run256 / lc_run768 / lc512 / lc_test_run / nsdbg_run). Their only
    differences were memory size, --test and --redisk; those are parameters now.

    Logs always go to <this dir>/.out/ (gitignored). Nothing is written to the
    workspace root and no .tmp- files are produced.

    The workspace root is derived from this script's own location
    (<root>/tools/devcheck/), so the caller's cwd does not matter.

    KEEP THIS FILE PURE ASCII. Windows PowerShell 5.1 reads a UTF-8 file without a
    BOM as ANSI; non-ASCII bytes then eat quotes and break parsing silently.
    Chinese explanations belong in README.md or in the .py tools.

.PARAMETER label
    Log label; the log is named lc2_<label>.log or kt_<label>.log.

.PARAMETER mem
    QEMU memory, default 1024M. If the host cannot back 1024M, drop to 768M.

.PARAMETER test
    Pass --test to br: run kernel selftests instead of libccheck. Prefix becomes kt_.

.PARAMETER testdisk
    Pass --testdisk: also attach testdisk.img (fully independent of the data disk).

.PARAMETER noRedisk
    Do not pass --redisk: reuse the existing disk.img instead of rebuilding it.

.PARAMETER initRun
    Value of BORUIX_INIT_RUN, default libccheck. Empty string means do not set it.

.PARAMETER timeoutSec
    Hard timeout, default 1500 seconds.

.EXAMPLE
    .\lc_run.ps1 -label postmove
    .\lc_run.ps1 -label diskless -testdisk -noRedisk -mem 768M
    .\lc_run.ps1 -label kt -test
#>
param(
    [string]$label = "run",
    [string]$mem = "1024M",
    [switch]$test,
    [switch]$testdisk,
    [switch]$noRedisk,
    [string]$initRun = "libccheck",
    [int]$timeoutSec = 1500
)

$ErrorActionPreference = "Continue"

# Workspace root: this script lives at <root>/tools/devcheck/
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outDir = Join-Path $PSScriptRoot ".out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$prefix = "lc2"
if ($test) { $prefix = "kt" }
$log = Join-Path $outDir ("{0}_{1}.log" -f $prefix, $label)
$errLog = $log + ".err"

# A leftover QEMU from the previous run holds the serial port and the disk image.
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

if ($initRun) {
    $env:BORUIX_INIT_RUN = $initRun
} else {
    Remove-Item Env:\BORUIX_INIT_RUN -ErrorAction SilentlyContinue
}

Remove-Item $log -ErrorAction SilentlyContinue
Remove-Item $errLog -ErrorAction SilentlyContinue

$argv = @("tools/main.py", "br", "--serial", "--mem", $mem, "--ahci")
if (-not $noRedisk) { $argv += "--redisk" }
if ($test) { $argv += "--test" }
if ($testdisk) { $argv += "--testdisk" }

Write-Output ("[devcheck] br " + ($argv -join " "))
Write-Output ("[devcheck] log -> " + $log)

$proc = Start-Process -FilePath "python" -ArgumentList $argv -WorkingDirectory $root -RedirectStandardOutput $log -RedirectStandardError $errLog -PassThru -NoNewWindow

$deadline = (Get-Date).AddSeconds($timeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) { Write-Output "[devcheck] br exited"; break }
    if (Test-Path $log) {
        if (Get-Content $log -ErrorAction SilentlyContinue | Select-String -Pattern "run exited with code" -Quiet) {
            # let the serial tail drain before collecting
            Start-Sleep -Seconds 12
            break
        }
    }
}

if (-not $proc.HasExited) { Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue }
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue |
    Select-String -Pattern "passed=|failed=|run exited|FAIL|PANIC|CPU EXCEPTION" |
    Select-Object -Last 20 | ForEach-Object { $_.Line }

# QEMU stderr is ~650 KB of near-identical noise on every run. Keep it only when the
# run produced no verdict, so .out/ cannot silently grow by hundreds of MB.
$hasVerdict = Select-String -Path $log -Pattern "passed=" -Quiet -ErrorAction SilentlyContinue
if ($hasVerdict) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

Write-Output ("[devcheck] DONE " + $label)
