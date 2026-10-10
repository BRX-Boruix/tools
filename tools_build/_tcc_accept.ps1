$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pbB.log
"BUILD_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pbB.log -Tail 3
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-pbB.log
"STAGE_RC=$LASTEXITCODE"
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED=INSTRUMENTED" } else { "STAGED=CLEAN" }
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo T1 && now && tcc src/cowsay/cowsay.c -o cowsay_t && echo L_OK && now && echo RUN1 && ./cowsay_t -w 20 hi && echo OK2 && echo T2 && tcc readbench.c -o readbench && ./readbench && echo ALL_DONE"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-prB.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-prB.log -Encoding UTF8 | Select-String -Pattern "now:|L_OK|RUN1|OK2|readbench|ALL_DONE|run exited" | ForEach-Object { $_.Line }
"PBB DONE"
