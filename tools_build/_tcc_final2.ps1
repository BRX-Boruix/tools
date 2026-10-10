$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64,rustc,cargo,clang -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pbF.log
"BUILD_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pbF.log -Tail 3
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-pbF.log
"STAGE_RC=$LASTEXITCODE"
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED=INSTRUMENTED" } else { "STAGED=CLEAN" }
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo T1 && now && tcc src/cowsay/cowsay.c -o cowsay_t && echo L_OK && now && echo T2 && now && tcc src/cowsay/cowsay.c -o cowsay_t2 && echo L2_OK && now && ./cowsay_t -w 20 hi"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-prF.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-prF.log -Encoding UTF8 | Select-String -Pattern "now:|L_OK|L2_OK|run exited" | ForEach-Object { $_.Line }
"PBF DONE"
