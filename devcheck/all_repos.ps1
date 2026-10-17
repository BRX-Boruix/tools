# Status summary for every git repo in the workspace: unpushed commits,
# dirty working trees, missing remotes.
# The workspace root is derived from this script's own location
# (<root>/tools/devcheck/), so the caller's cwd does not matter.
# KEEP THIS FILE PURE ASCII - see the note in lc_run.ps1.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$rows = @()
foreach ($d in Get-ChildItem -Directory $root) {
    $g = Join-Path $d.FullName '.git'
    if (-not (Test-Path $g)) { continue }
    $sb = (& git -C $d.FullName status -sb 2>$null | Select-Object -First 1)
    if (-not $sb) { $sb = '(?)' }
    $dirty = (& git -C $d.FullName status --porcelain 2>$null | Measure-Object).Count
    $remote = (& git -C $d.FullName remote 2>$null | Select-Object -First 1)
    if (-not $remote) { $remote = '(no remote)' }
    $ahead = 0; $behind = 0
    if ($sb -match '\[ahead (\d+)') { $ahead = [int]$Matches[1] }
    if ($sb -match 'behind (\d+)') { $behind = [int]$Matches[1] }
    $rows += [pscustomobject]@{ Repo = $d.Name; Ahead = $ahead; Behind = $behind; Dirty = $dirty; Remote = $remote; Branch = ($sb -replace '^## ', '') }
}
Write-Output ("repos: " + $rows.Count)
Write-Output "=== unpushed commits (ahead>0) ==="
$rows | Where-Object { $_.Ahead -gt 0 } | ForEach-Object { "  {0,-18} ahead={1} behind={2} dirty={3}  {4}" -f $_.Repo, $_.Ahead, $_.Behind, $_.Dirty, $_.Branch }
Write-Output "=== dirty working trees (dirty>0) ==="
$rows | Where-Object { $_.Dirty -gt 0 } | ForEach-Object { "  {0,-18} dirty={1}  {2}" -f $_.Repo, $_.Dirty, $_.Branch }
Write-Output "=== no remote ==="
$rows | Where-Object { $_.Remote -eq '(no remote)' } | ForEach-Object { "  {0,-18} {1}" -f $_.Repo, $_.Branch }
Write-Output "=== all (repo/ahead/behind/dirty) ==="
$rows | Sort-Object Repo | ForEach-Object { "  {0,-18} a={1} b={2} d={3}" -f $_.Repo, $_.Ahead, $_.Behind, $_.Dirty }
