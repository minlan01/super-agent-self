# Gate 8: pull Hyper-V event logs for boot-failure evidence, then
# disable SecureBoot (bisection) and power-cycle the VM.
# ASCII-only. Elevated. Always writes JSON + log.
$ErrorActionPreference = 'Continue'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-secureboot-off.json'
$Steps = Join-Path $Dir 'gate8-secureboot-off-steps.log'
$Evt = Join-Path $Dir 'gate8-hyperv-events.log'
$info = @{ status = 'ok' }

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
  LogStep 'elevated ok'

  $VmName = 'ZCODE-GA-W11-20260823'

  # 1. Evidence: recent Hyper-V events (boot failures are logged here).
  $since = (Get-Date).AddHours(-4)
  $out = @()
  foreach ($logName in @('Microsoft-Windows-Hyper-V-Worker-Admin',
                         'Microsoft-Windows-Hyper-V-VMMS-Admin',
                         'Microsoft-Windows-Hyper-V-VID-Admin')) {
    try {
      $evts = Get-WinEvent -FilterHashtable @{ LogName = $logName; StartTime = $since } `
        -MaxEvents 30 -ErrorAction Stop
      foreach ($e in $evts) {
        $out += ('[' + $logName + '] ' + $e.TimeCreated.ToString('HH:mm:ss') + ' id=' + $e.Id + ' lvl=' + $e.LevelDisplayName + ' ' + ($e.Message -replace "`r`n", ' '))
      }
    } catch { $out += ('[' + $logName + '] (no events: ' + $_.Exception.Message + ')') }
  }
  $out | Set-Content -LiteralPath $Evt -Encoding UTF8
  LogStep ('events captured: ' + $out.Count + ' -> gate8-hyperv-events.log')

  # 2. Bisection: disable SecureBoot on the VM.
  Set-VMFirmware -VMName $VmName -EnableSecureBoot Off -ErrorAction Stop
  LogStep 'secureboot OFF'

  # 3. Power cycle (this module lacks Reset-VM).
  $vm = Get-VM -Name $VmName
  if ($vm.State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force; Start-Sleep -Seconds 2 }
  Start-VM -Name $VmName
  Start-Sleep -Seconds 3
  $vm = Get-VM -Name $VmName
  LogStep ('state: ' + $vm.State)

  $info.secureboot = 'off'; $info.state = $vm.State.ToString()
  $info.events_file = 'gate8-hyperv-events.log'
  $info.next = 'USER: focus VMConnect and press any key at the DVD prompt'
}
catch {
  $info.status = 'failed'; $info.reason = $_.Exception.Message
  LogStep ('ERROR: ' + $_.Exception.Message)
}
$info | ConvertTo-Json | Set-Content -LiteralPath $Log -Encoding UTF8
Get-Content $Log
if ($info.status -ne 'ok') { exit 2 }
exit 0
