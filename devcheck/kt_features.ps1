<#
.SYNOPSIS
    Run every kernel halt-acceptance feature once and summarise the outcome.

.DESCRIPTION
    Each of these features compiles a DIFFERENT kernel that runs ONE destructive
    test and then stops the machine. They cannot share a boot, so this loops them:
    build + boot + run + stop, one feature at a time.

    Why this exists (A1 of the 2026-10-26 cleanup): chk.py test-features proves the
    halt-test code COMPILES; nothing proved it RUNS. That gap is what let
    kernel-test-m43/m44 rot for months without anyone noticing.

    Since a halt test stops the machine, there is no verdict line to wait for.
    So the stop rule is: output appeared, then the log stopped growing for $idleSec
    seconds (or the per-feature cap $perTestSec is hit). Verdicts are printed as a
    table with the last non-empty lines for human reading - this script does NOT
    invent PASS. Judgement stays with the reader (and lands in docs).

    KEEP THIS FILE PURE ASCII (Windows PowerShell 5.1 reads UTF-8-no-BOM as ANSI).

.PARAMETER mem
    QEMU memory, default 768M.

.PARAMETER only
    Run a single config by name (see the table printed at start).

.EXAMPLE
    .\tools\devcheck\kt_features.ps1
    .\tools\devcheck\kt_features.ps1 -only m43
#>
param(
    [string]$mem = "768M",
    [int]$perTestSec = 900,
    # 90 s, not 25: test_ahci6b switches to interrupt-driven I/O and can go quiet for
    # tens of seconds before printing again; a 25 s window cut every run right there
    # (observed on m44/m5/waitpid with --redisk, 2026-10-26).
    [int]$idleSec = 90,
    [string]$only = "",
    # Default TRUE: a REUSED disk.img changes AHCI state and makes
    # test_ahci6b fail ("ports with completion IRQ enabled: 0 / 6" instead of 1/6).
    # Measured 2026-10-26: same kernel, same flags, only --redisk differs.
    [bool]$redisk = $true
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outDir = Join-Path $PSScriptRoot ".out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# NOTE: the CLI spells them with dots (--test-m4.3), not the Cargo feature
# names (kernel-test-m43). Keep this table in sync with `python tools/main.py br --help`.
$configs = @(
    @{ Name = "m33";            Args = @("--test-m3.3") },
    @{ Name = "pre2";           Args = @("--test-pre2") },
    @{ Name = "m41";            Args = @("--test-m4.1") },
    @{ Name = "m42";            Args = @("--test-m4.2") },
    @{ Name = "m43";            Args = @("--test-m4.3") },
    @{ Name = "m44";            Args = @("--test-m4.4") },
    @{ Name = "m5";             Args = @("--test-m5") },
    @{ Name = "waitpid";        Args = @("--test-waitpid") },
    @{ Name = "sstack";         Args = @("--test-sstack") },
    @{ Name = "signal-handler"; Args = @("--test-signal", "--signal-halt", "handler") },
    @{ Name = "signal-fault";   Args = @("--test-signal", "--signal-halt", "fault") },
    @{ Name = "signal-nested";  Args = @("--test-signal", "--signal-halt", "nested") }
)

if ($only) { $configs = $configs | Where-Object { $_.Name -eq $only } }
if (-not $configs) { Write-Output ("[ktf] unknown config: " + $only); exit 2 }

# The halt tests run before init: make sure no runtime command is injected.
Remove-Item Env:\BORUIX_INIT_RUN -ErrorAction SilentlyContinue

$rows = @()
foreach ($c in $configs) {
    $name = $c.Name
    $log = Join-Path $outDir ("ktf_" + $name + ".log")
    Write-Output ("[ktf] === " + $name + " ===  " + ($c.Args -join " "))
    Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Item $log -ErrorAction SilentlyContinue
    $argv = @("tools/main.py", "br", "--serial", "--mem", $mem, "--ahci")
    if ($redisk) { $argv += "--redisk" }
    $argv = $argv + $c.Args
    $proc = Start-Process -FilePath "python" -ArgumentList $argv -WorkingDirectory $root -RedirectStandardOutput $log -RedirectStandardError ($log + ".err") -PassThru -NoNewWindow
    # Wait loop: stop when the log has content AND stopped growing for $idleSec.
    # IMPORTANT: silence during `cargo build` is normal and can last minutes, so the
    # idle-stop rule only arms AFTER QEMU has been launched (br prints a line with
    # "QEMU" right before boot). Without this the runner kills the build at 25 s of
    # silence and reports "0 lines" (observed on the first smoke attempt).
    $deadline = (Get-Date).AddSeconds($perTestSec)
    $lastSize = -1
    $stableSince = $null
    $armed = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if ($proc.HasExited) { break }
        $size = 0
        if (Test-Path $log) { $size = (Get-Item $log).Length }
        if ($size -ne $lastSize) {
            $stableSince = $null
            if (-not $armed -and $size -gt 0) {
                if (Select-String -Path $log -Pattern "QEMU" -Quiet -ErrorAction SilentlyContinue) { $armed = $true }
            }
        } elseif ($armed) {
            if ($null -eq $stableSince) { $stableSince = Get-Date }
            elseif (((Get-Date) - $stableSince).TotalSeconds -ge $idleSec) { break }
        }
        $lastSize = $size
    }
    if (-not $proc.HasExited) { Stop-Process -Force -Id $proc.Id -ErrorAction SilentlyContinue }
    Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    $lines = @()
    if (Test-Path $log) { $lines = Get-Content $log -Encoding UTF8 }
    $fail = @($lines | Select-String -Pattern ": FAIL$").Count
    # Case-sensitive: "no panic" appears in several test messages and would false-positive.
    $panic = @($lines | Select-String -Pattern "PANIC|panicked at|CPU EXCEPTION" -CaseSensitive).Count
    $marks = @($lines | Select-String -Pattern "^\[kt\] >>").Count
    $tail = @($lines | Where-Object { $_ -ne "" } | Select-Object -Last 2)
    $rows += [pscustomobject]@{
        Name = $name
        Lines = $lines.Count
        Fail = $fail
        Panic = $panic
        KtMarks = $marks
        LastLine = ($tail -join " | ")
    }
    Write-Output ("[ktf] " + $name + ": lines=" + $lines.Count + " fail=" + $fail + " panic=" + $panic + " kt=" + $marks)
}

Write-Output ""
Write-Output "=== summary ==="
$rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
# Trim tails so the table stays readable in a log.
foreach ($r in $rows) {
    $s = $r.LastLine
    if ($s.Length -gt 110) { $s = $s.Substring(0, 110) }
    Write-Output ("[ktf] tail " + $r.Name + ": " + $s)
}