# Gate 8: remove the config-damaged VM object and recreate it clean,
# reusing the fresh empty VHDX. ASCII-only. Elevated. Always writes JSON.
$ErrorActionPreference = 'Continue'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-recreate-vm.json'
$Steps = Join-Path $Dir 'gate8-recreate-vm-steps.log'
$info = @{ status = 'ok' }

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
  LogStep 'elevated ok'

  $VmName = 'ZCODE-GA-W11-20260823'
  $IsoPath = 'D:\Zcode-GA-ISO\Win11_25H2_EnterpriseEval_x64_zh-cn.iso'
  $VhdPath = 'C:\HyperV\Zcode-GA-20260823\ZCODE-GA-W11-20260823\ZCODE-GA-W11-20260823.vhdx'
  $VmRoot = 'C:\HyperV\Zcode-GA-20260823\ZCODE-GA-W11-20260823'

  if (-not (Test-Path -LiteralPath $IsoPath)) { throw 'ISO missing' }
  if (-not (Test-Path -LiteralPath $VhdPath)) { throw 'VHDX missing' }

  $old = Get-VM -Name $VmName -ErrorAction SilentlyContinue
  if ($old) {
    if ($old.State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force; Start-Sleep -Seconds 2 }
    Remove-VM -Name $VmName -Force
    LogStep 'old VM object removed (VHDX kept)'
  } else { LogStep 'no existing VM' }

  New-VM -Name $VmName -Generation 2 `
    -MemoryStartupBytes 4GB `
    -VHDPath $VhdPath -Path $VmRoot | Out-Null
  LogStep 'VM recreated (defaults + existing empty VHDX)'

  Set-VMProcessor -VMName $VmName -Count 4
  Set-VMMemory -VMName $VmName -DynamicMemoryEnabled $true `
    -MinimumBytes 2GB -StartupBytes 4GB -MaximumBytes 6GB
  LogStep 'cpu/memory set'

  $dvd = Add-VMDvdDrive -VMName $VmName -Path $IsoPath -PassThru
  LogStep 'DVD with ISO added'
  Set-VMFirmware -VMName $VmName -FirstBootDevice $dvd
  LogStep 'first boot = DVD'

  Get-VMIntegrationService -VMName $VmName | Where-Object { -not $_.Enabled } |
    Enable-VMIntegrationService
  LogStep 'integration services enabled'

  Get-VMNetworkAdapter -VMName $VmName -ErrorAction SilentlyContinue |
    Remove-VMNetworkAdapter -ErrorAction SilentlyContinue
  LogStep 'network adapters removed (offline posture)'

  Start-VM -Name $VmName
  Start-Sleep -Seconds 5
  $vm = Get-VM -Name $VmName
  LogStep ('state after: ' + $vm.State)

  $info.vm_name = $VmName; $info.state = $vm.State.ToString(); $info.recreated = $true
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
