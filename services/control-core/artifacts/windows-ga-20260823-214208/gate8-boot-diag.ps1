# Gate 8: defensive firmware/DVD diagnostics, ensure ISO mounted +
# DVD first boot, then reset the VM. ASCII-only. Elevated.
$ErrorActionPreference = 'Continue'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-boot-diag.json'
$Steps = Join-Path $Dir 'gate8-boot-diag-steps.log'
$info = @{ status = 'ok' }

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

$VmName = 'ZCODE-GA-W11-20260823'
$IsoPath = 'D:\Zcode-GA-ISO\Win11_25H2_EnterpriseEval_x64_zh-cn.iso'

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $elev = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  LogStep ('elevated=' + $elev)
  if (-not $elev) { $info.status = 'failed'; $info.reason = 'not elevated' }

  try {
    $fw = Get-VMFirmware -VMName $VmName -ErrorAction Stop
    $sb = 'unknown'; $tpl = 'unknown'
    if ($null -ne $fw.SecureBoot) { $sb = $fw.SecureBoot.ToString() }
    if ($null -ne $fw.SecureBootTemplate) { $tpl = $fw.SecureBootTemplate.ToString() }
    $info.secureboot = $sb; $info.template = $tpl
    LogStep ('secureboot=' + $sb + ' template=' + $tpl)
    if ($null -ne $fw.BootOrder) {
      $order = ($fw.BootOrder | ForEach-Object { [string]$_.DeviceType + ':' + [string]$_.DevicePath }) -join ' | '
      LogStep ('bootorder=' + $order)
    } else { LogStep 'bootorder=<null>' }
  } catch { LogStep ('firmware-query-error: ' + $_.Exception.Message) }

  $isoOk = Test-Path -LiteralPath $IsoPath -PathType Leaf
  LogStep ('iso-file-exists=' + $isoOk)
  if (-not $isoOk) { $info.status = 'failed'; $info.reason = 'ISO missing on host'; throw 'ISO missing' }

  $dvds = @(Get-VMDvdDrive -VMName $VmName -ErrorAction SilentlyContinue)
  LogStep ('dvd-count=' + $dvds.Count)
  foreach ($d in $dvds) { LogStep ('dvd ctrl=' + $d.ControllerNumber + ' loc=' + $d.ControllerLocation + ' path=' + $d.Path) }

  $mounted = @($dvds | Where-Object { $_.Path -eq $IsoPath })
  if ($mounted.Count -eq 0) {
    if ($dvds.Count -gt 0) { $dvds[0] | Set-VMDvdDrive -Path $IsoPath }
    else { Add-VMDvdDrive -VMName $VmName -Path $IsoPath }
    LogStep 'ISO attached now'
  } else { LogStep 'ISO already mounted' }

  $dvdForBoot = @(Get-VMDvdDrive -VMName $VmName | Where-Object { $_.Path -eq $IsoPath })[0]
  Set-VMFirmware -VMName $VmName -FirstBootDevice $dvdForBoot
  LogStep 'first boot = DVD(ISO)'

  Reset-VM -Name $VmName -Force
  LogStep 'VM reset done - prompt reappears in seconds'

  $info.iso_mounted = $true
  $info.action = 'reset'
  $info.next = 'USER: focus VMConnect and press any key at the DVD prompt'
}
catch {
  $info.status = 'failed'
  $info.reason = $_.Exception.Message
  LogStep ('ERROR: ' + $_.Exception.Message)
}
$info | ConvertTo-Json | Set-Content -LiteralPath $Log -Encoding UTF8
Get-Content $Log
if ($info.status -ne 'ok') { exit 2 }
exit 0
