$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pb.log
"BUILD_RC=$LASTEXITCODE"
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-pb.log
"STAGE_RC=$LASTEXITCODE"
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED=HAS_MARKER" } else { "STAGED=NO_MARKER" }
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo P1 && tcc src/cowsay/cowsay.c -o cowsay_t && echo P1_DONE && echo P2 && tcc fswrite.c -o fswrite && echo P2_DONE"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-pr.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pr.log -Encoding UTF8 | Select-String -Pattern "TCCPROF|P1|P2|run exited" | ForEach-Object { $_.Line }
"PB DONE"
