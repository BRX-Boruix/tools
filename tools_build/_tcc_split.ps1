$ErrorActionPreference = "Continue"
$env:BORUIX_CLANG = "F:\clang\18.1.8x86_64\bin\clang.exe"
$env:BORUIX_LLD = "F:\clang\18.1.8x86_64\bin\ld.lld.exe"
$s = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project
Get-Process qemu-system-x86_64,rustc,cargo,clang -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
python tcc-on-boruix\boruix\build.py --sysroot $s *> F:\boruix-project\.tmp-pbE.log
"BUILD_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-pbE.log -Tail 3
python tcc-on-boruix\boruix\stage_assets.py --sysroot $s *>> F:\boruix-project\.tmp-pbE.log
"STAGE_RC=$LASTEXITCODE"
$env:BORUIX_INIT_RUN = "cd /volumes/BORUIX_DATA/3p && echo T1 && now && tcc src/cowsay/cowsay.c -o cowsay_t && echo L_OK && now && ./cowsay_t -w 20 hi"
python tools\main.py br --serial --redisk --mem 1024M *> F:\boruix-project\.tmp-prE.log
"RUN_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-prE.log -Encoding UTF8 | Select-String -Pattern "TCCPROF|now:|L_OK|run exited" | ForEach-Object { $_.Line }
"PBE DONE"
