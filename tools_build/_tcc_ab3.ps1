$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
$repo = "F:\boruix-project\tcc-on-boruix"
Set-Location F:\boruix-project

# 1) build the FIXED version (current worktree) and stage it
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pbD1.log
"BUILD_NEW_RC=$LASTEXITCODE"
Copy-Item $repo\_build\tcc.elf F:\boruix-project\tools\diskfiles\3p\tcc.elf -Force
$newHash = (Get-FileHash F:\boruix-project\tools\diskfiles\3p\tcc.elf -Algorithm SHA256).Hash
"NEW_HASH=$newHash"

# 2) build the PRE-FIX version by stashing this round's changes; VERIFY the stash took effect and was restored
git -C $repo stash push -- tcc.h tccelf.c *> F:\boruix-project\.tmp-stash1.log
$d = (git -C $repo diff --stat | Measure-Object -Line).Lines
"AFTER_STASH_DIFFLINES=$d"
if ($d -ne 0) { "ABORT: stash did not clean the worktree"; exit 1 }
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pbD2.log
"BUILD_OLD_RC=$LASTEXITCODE"
Copy-Item $repo\_build\tcc.elf F:\boruix-project\tools\diskfiles\3p\tcc_old.elf -Force
git -C $repo stash pop *> F:\boruix-project\.tmp-stash2.log
$d2 = (git -C $repo diff --stat | Measure-Object -Line).Lines
"AFTER_POP_DIFFLINES=$d2"
if ($d2 -lt 2) { "ABORT: stash pop did not restore the changes"; exit 1 }
$oldHash = (Get-FileHash F:\boruix-project\tools\diskfiles\3p\tcc_old.elf -Algorithm SHA256).Hash
"OLD_HASH=$oldHash"
if ($newHash -eq $oldHash) { "ABORT: the two binaries are identical (A/B would be void)"; exit 1 }
"DIFFER=OK"

# 3) interleaved A/B/A/B inside one boot
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo M1 && now && ./tcc_old.elf src/cowsay/cowsay.c -o b1 && echo M2 && now && ./tcc.elf src/cowsay/cowsay.c -o a1 && echo M3 && now && ./tcc_old.elf src/cowsay/cowsay.c -o b2 && echo M4 && now && ./tcc.elf src/cowsay/cowsay.c -o a2 && echo M5 && now && echo ALL_DONE"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-prD.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-prD.log -Encoding UTF8 | Select-String -Pattern "now:|^M1|^M2|^M3|^M4|^M5|ALL_DONE|run exited" | ForEach-Object { $_.Line }
"PBD DONE"
