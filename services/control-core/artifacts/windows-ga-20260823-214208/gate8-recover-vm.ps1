# Gate 8 recovery: force-off the stuck VM, eject the setup DVD (so it
# boots from disk, not the ISO), then start it again.
# ASCII-only. Elevated. Always writes a JSON result.
$ErrorActionPreference = 'Stop'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-recover-vm.json'
$Steps = Join-Path $Dir 'gate8-recover-vm-steps.log'

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
  LogStep 'elevated ok'

  $VmName = 'ZCODE-GA-W11-20260823'
  $vm = Get-VM -Name $VmName -ErrorAction Stop
  LogStep ('state before: ' + $vm.State)

  if ($vm.State -ne 'Off') {
    # Hard power-off (equivalent to pulling the plug). -Force suppresses
    # the confirmation prompt; -TurnOff skips the graceful path entirely.
    Stop-VM -Name $VmName -TurnOff -Force
    Start-Sleep -Seconds 2
    $vm = Get-VM -Name $VmName
    if ($vm.State -ne 'Off') {
      # Extremely rare: worker process wedged. Kill vmwp for this VM.
      LogStep 'Stop-VM ineffective - killing vmwp worker process'
      $vmwp = Get-Process vmwp -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match [Regex]::Escape($vm.Id.ToString())
      }
      if ($vmwp) { $vmwp | Stop-Process -Force; Start-Sleep -Seconds 3 }
      $vm = Get-VM -Name $VmName
      if ($vm.State -ne 'Off') { throw ('VM still not off: ' + $vm.State) }
    }
  }
  LogStep 'VM is off'

  # Remove the DVD device entirely: phase-1 file copy already completed
  # ("Restart now" screen), so Windows on disk continues OOBE on its own
  # and cannot loop back into setup from the ISO.
  Get-VMDvdDrive -VMName $VmName -ErrorAction SilentlyContinue | Remove-VMDvdDrive
  LogStep 'DVD device removed (boots from disk)'

  Start-VM -Name $VmName
  Start-Sleep -Seconds 5
  $vm = Get-VM -Name $VmName
  LogStep ('state after: ' + $vm.State)

  @{ status = 'ok'; state_before = ''; state_after = $vm.State.ToString(); dvd = 'removed';
     next = 'USER reconnects via VMConnect and completes OOBE (local account)' } |
    ConvertTo-Json | Set-Content -LiteralPath $Log -Encoding UTF8
  Get-Content $Log
  exit 0
}
catch {
  $msg = $_.Exception.Message
  LogStep ('ERROR: ' + $msg)
  @{ status = 'failed'; reason = $msg } | ConvertTo-Json | Set-Content -LiteralPath $Log -Encoding UTF8
  exit 2
}
