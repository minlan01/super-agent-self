# Gate 8: reset for a clean reinstall. The VHDX is 4MB (phase-1 file copy
# never happened - setup froze before writing to disk), so repair is
# meaningless: recreate the disk, reattach the ISO, boot DVD-first.
# ASCII-only. Elevated. Always writes a JSON result.
$ErrorActionPreference = 'Stop'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-reinstall-prep.json'
$Steps = Join-Path $Dir 'gate8-reinstall-prep-steps.log'

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
  LogStep 'elevated ok'

  $VmName = 'ZCODE-GA-W11-20260823'
  $IsoPath = 'D:\Zcode-GA-ISO\Win11_25H2_EnterpriseEval_x64_zh-cn.iso'
  $VhdPath = 'C:\HyperV\Zcode-GA-20260823\ZCODE-GA-W11-20260823\ZCODE-GA-W11-20260823.vhdx'
  if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) { throw "ISO missing: $IsoPath" }

  $vm = Get-VM -Name $VmName -ErrorAction Stop
  if ($vm.State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force; Start-Sleep -Seconds 2 }
  $vm = Get-VM -Name $VmName
  if ($vm.State -ne 'Off') { throw ('cannot turn off VM: ' + $vm.State) }
  LogStep 'VM off'

  # Any checkpoints would pin the old VHDX; remove them so the file is
  # deletable and the VM state is fully clean.
  Get-VMSnapshot -VMName $VmName -ErrorAction SilentlyContinue | Remove-VMSnapshot -ErrorAction SilentlyContinue
  LogStep 'snapshots cleared (if any)'

  Get-VMHardDiskDrive -VMName $VmName | Remove-VMHardDiskDrive
  if (Test-Path -LiteralPath $VhdPath) { Remove-Item -LiteralPath $VhdPath -Force }
  New-VHD -Path $VhdPath -SizeBytes 48GB -Dynamic | Out-Null
  Add-VMHardDiskDrive -VMName $VmName -Path $VhdPath
  LogStep 'fresh 48GB dynamic VHDX attached (SCSI)'

  $dvd = Get-VMDvdDrive -VMName $VmName -ErrorAction SilentlyContinue
  if (-not $dvd) { $dvd = Add-VMDvdDrive -VMName $VmName -PassThru }
  $dvd | Set-VMDvdDrive -Path $IsoPath
  LogStep 'ISO attached'

  Set-VMFirmware -VMName $VmName -FirstBootDevice $dvd
  LogStep 'firmware: DVD first boot'

  Start-VM -Name $VmName
  Start-Sleep -Seconds 5
  $vm = Get-VM -Name $VmName
  LogStep ('state after: ' + $vm.State)

  @{ status = 'ok'; state_after = $vm.State.ToString(); vhdx = $VhdPath; iso = $IsoPath;
     note = 'fresh empty disk; setup runs cleanly from ISO';
     next = 'USER: install Windows (keyboard: Tab/Enter/Alt+N), local account, then notify Zcode' } |
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
