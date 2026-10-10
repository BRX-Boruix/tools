$ErrorActionPreference = "Continue"
$env:BORUIX_SYSROOT = "C:\Users\aixiaoji\AppData\Local\Temp\boruix-sysroot"
Set-Location F:\boruix-project\rtld
& 'F:\boruix-project\sdk\boruix_std\target\debug\cargo-boruix.exe' build *> F:\boruix-project\.tmp-rtldbuild2.log
"RTLD_BUILD_RC=$LASTEXITCODE"
Get-Content F:\boruix-project\.tmp-rtldbuild2.log -Tail 30
