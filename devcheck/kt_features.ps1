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
    [bool]$redisk = $true,
    # Seconds to keep collecting after the verdict line matched.
    [int]$holdSec = 20,
    # Build-time selector passthrough (BORUIX_KT_ONLY): run ONE test and skip the
    # whole non-destructive suite. Needed because a stalled test UPSTREAM of the one
    # you care about would otherwise hide it (test_ahci6b does exactly that when it
    # spins). Usage: -onlyTest test_elf_loader
    [string]$onlyTest = "",
    # Override the config verdict regex (useful with -only single -onlyTest <fn>).
    [string]$expect = ""
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outDir = Join-Path $PSScriptRoot ".out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# NOTE: the CLI spells them with dots (--test-m4.3), not the Cargo feature
# names (kernel-test-m43). Keep this table in sync with `python tools/main.py br --help`.
#
# `Expect` = the config own VERDICT line (regex). When it shows up the run is done:
# we then wait `-$holdSec` more seconds to collect any trailing output and stop.
# This exists because "silence = finished" is a LIE for long I/O: test_ahci6b
# switches to interrupt-driven I/O and can go quiet for minutes (the driver itself
# documents the interrupt path as "69x slower"), which made every run look stopped
# in the middle. Verdict-driven stopping is exact; the idle rule stays only as a
# fallback for configs whose verdict we cannot name.
$configs = @(
    @{ Name = "m33";            Args = @("--test-m3.3");         Expect = "user process terminated by" },
    @{ Name = "pre2";           Args = @("--test-pre2");         Expect = "PRE-2" },
    @{ Name = "m41";            Args = @("--test-m4.1");         Expect = "exit\(code=42\)" },
    # m42: judge from the pid= field of the syscall trace (3 distinct pids interleaving).
    # Its marker chars DO reach the serial log in other configs (verified on
    # signal-handler: A/B/C all present), so the chars are not the reliable anchor here —
    # the criterion line is.
    @{ Name = "m42";            Args = @("--test-m4.2");         Expect = "verdict: PASS iff" },
    @{ Name = "m43";            Args = @("--test-m4.3");         Expect = "Hello from ELF" },
    @{ Name = "m44";            Args = @("--test-m4.4");         Expect = "" },
    @{ Name = "m5";             Args = @("--test-m5");           Expect = "ipc-test\] PASS|COW" },
    @{ Name = "waitpid";        Args = @("--test-waitpid");      Expect = "test-waitpid-e2e\]" },
    @{ Name = "sstack";         Args = @("--test-sstack");       Expect = "guard page hit" },
    # signal-*: the run ends in a user `jmp $` loop, so the idle rule finishes it. The
    # evidence is the marker chars (A/B/C/D) plus the rt_sigreturn lines (nr=0x84).
    @{ Name = "signal-handler"; Args = @("--test-signal", "--signal-halt", "handler"); Expect = "" },
    @{ Name = "signal-fault";   Args = @("--test-signal", "--signal-halt", "fault");   Expect = "" },
    @{ Name = "signal-nested";  Args = @("--test-signal", "--signal-halt", "nested");  Expect = "" },
    # Generic single-test probe: pair with -onlyTest <fn>. Built for bisecting ONE test
    # (e.g. test_ahci6b_interrupt_completion) in a few minutes instead of a full suite.
    # NOTE: --test is REQUIRED here: without the kernel-tests feature nothing is compiled
    # and the kernel silently boots with no test at all (measured: 0 test lines, filter
    # banner missing). -onlyTest then narrows it to the single test.
    @{ Name = "single";         Args = @("--test");                Expect = "" }
)

if ($only) { $configs = $configs | Where-Object { $_.Name -eq $only } }
if (-not $configs) { Write-Output ("[ktf] unknown config: " + $only); exit 2 }

# The halt tests run before init: make sure no runtime command is injected.
Remove-Item Env:\BORUIX_INIT_RUN -ErrorAction SilentlyContinue
if ($onlyTest) { $env:BORUIX_KT_ONLY = $onlyTest } else { Remove-Item Env:\BORUIX_KT_ONLY -ErrorAction SilentlyContinue }

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
    $verdictAt = $null
    $expectRe = $c.Expect
    if ($expect) { $expectRe = $expect }
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if ($proc.HasExited) { break }
        $size = 0
        if (Test-Path $log) { $size = (Get-Item $log).Length }
        if ($size -ne $lastSize) {
            $stableSince = $null
            $verdictAt = $null   # new output: restart the hold window
            if ($expectRe -and $size -gt 0) {
                if (Select-String -Path $log -Pattern $expectRe -Quiet -ErrorAction SilentlyContinue) {
                    $verdictAt = Get-Date
                }
            }
            if (-not $armed -and $size -gt 0) {
                if (Select-String -Path $log -Pattern "QEMU" -Quiet -ErrorAction SilentlyContinue) { $armed = $true }
            }
        } else {
            if ($null -ne $verdictAt -and ((Get-Date) - $verdictAt).TotalSeconds -ge $holdSec) { break }
            if ($armed) {
                if ($null -eq $stableSince) { $stableSince = Get-Date }
                elseif (((Get-Date) - $stableSince).TotalSeconds -ge $idleSec) { break }
            }
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
    $hit = "n/a"
    if ($expectRe) {
        $hit = "NO"
        if ($lines.Count -gt 0 -and (Select-String -Path $log -Pattern $expectRe -Quiet -ErrorAction SilentlyContinue)) { $hit = "YES" }
    }
    $rows += [pscustomobject]@{
        Name = $name
        Lines = $lines.Count
        Fail = $fail
        Panic = $panic
        KtMarks = $marks
        Verdict = $hit
        LastLine = ($tail -join " | ")
    }
    Write-Output ("[ktf] " + $name + ": lines=" + $lines.Count + " fail=" + $fail + " panic=" + $panic + " kt=" + $marks + " verdict=" + $hit)
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