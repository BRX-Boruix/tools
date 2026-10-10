$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
git -C F:\boruix-project\tcc-on-boruix checkout -- tccelf.c
"REVERT_DIFF=" + (git -C F:\boruix-project\tcc-on-boruix status --porcelain | Measure-Object -Line).Lines
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-rb.log
"BUILD_RC=$LASTEXITCODE"
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-rb.log
"STAGE_RC=$LASTEXITCODE"
$b=[System.IO.File]::ReadAllBytes('F:\boruix-project\tools\diskfiles\3p\tcc.elf')
if ([System.Text.Encoding]::ASCII.GetString($b).Contains('TCCPROF')) { "STAGED=STILL_INSTRUMENTED" } else { "STAGED=CLEAN" }
"REVERT DONE"
