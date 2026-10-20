<#
.SYNOPSIS
  ESL 작업 스케줄러 등록 해제만 한다(ESL-Backend, ESL-Worker). 파일·DB·런타임 파일(secrets)은 그대로 둔다.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
foreach ($t in @('ESL-Backend', 'ESL-Worker')) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "[ESL] 작업 등록 해제: $t"
    } else {
        Write-Host "[ESL] 등록되지 않음: $t"
    }
}
