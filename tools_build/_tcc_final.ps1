$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pb9.log
"BUILD_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pb9.log -Tail 4
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-pb9.log
"STAGE_RC=$LASTEXITCODE"
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED=INSTRUMENTED" } else { "STAGED=CLEAN" }
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo T1 && now && tcc src/cowsay/cowsay.c -o cowsay_t && echo L_OK && now && ls -l cowsay_t && echo T2 && now && cat tcc/libc.a > /dev/null && echo CAT_OK && now && echo RUN && ./cowsay_t -w 20 hi && echo ALL_DONE"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-pr9.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pr9.log -Encoding UTF8 | Select-String -Pattern "now:|L_OK|CAT_OK|RUN|ALL_DONE|^ |_|cowsay_t|run exited" | ForEach-Object { $_.Line }
"PB9 DONE"
