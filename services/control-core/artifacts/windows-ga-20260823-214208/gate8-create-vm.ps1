# Gate 8: create/configure the Windows 11 validation VM (manual 10.3).
# ASCII-only. Elevated. Fully try/catch wrapped; every step logged; idempotent.
$ErrorActionPreference = 'Stop'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-create-vm.json'
$Steps = Join-Path $Dir 'gate8-create-vm-steps.log'

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'not elevated'
  }
  LogStep ('elevated ok ' + (Get-Date -Format o))

  $vmms = Get-Service vmms -ErrorAction Stop
  if ($vmms.Status -ne 'Running') { Start-Service vmms -ErrorAction Stop }
  $null = Get-VM -ErrorAction Stop
  LogStep 'vmms running, Get-VM ok'

  $VmName = 'ZCODE-GA-W11-20260823'
  $IsoPath = 'D:\Zcode-GA-ISO\Win11_25H2_EnterpriseEval_x64_zh-cn.iso'
  $VmRoot = Join-Path 'C:\HyperV\Zcode-GA-20260823' $VmName
  $VhdPath = Join-Path $VmRoot "$VmName.vhdx"

  if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) { throw "ISO missing: $IsoPath" }

  $existing = Get-VM -Name $VmName -ErrorAction SilentlyContinue
  if (-not $existing) {
    New-Item -ItemType Directory -Path $VmRoot -Force | Out-Null
    New-VM -Name $VmName -Generation 2 `
      -MemoryStartupBytes 4GB `
      -NewVHDPath $VhdPath -NewVHDSizeBytes 48GB `
      -Path $VmRoot | Out-Null
    LogStep 'New-VM created'
  } else {
    LogStep 'VM already exists - reusing'
  }

  Set-VMProcessor -VMName $VmName -Count 4
  LogStep 'Set-VMProcessor ok'
  Set-VMMemory -VMName $VmName -DynamicMemoryEnabled $true `
    -MinimumBytes 2GB -StartupBytes 4GB -MaximumBytes 6GB
  LogStep 'Set-VMMemory ok'

  $dvd = Get-VMDvdDrive -VMName $VmName | Where-Object { $_.Path -eq $IsoPath }
  if (-not $dvd) { $dvd = Add-VMDvdDrive -VMName $VmName -Path $IsoPath -PassThru }
  LogStep 'DvdDrive ok'
  Set-VMFirmware -VMName $VmName -FirstBootDevice $dvd
  LogStep 'Firmware ok'
  $allSvc = Get-VMIntegrationService -VMName $VmName
  LogStep ('integration services: ' + (($allSvc | ForEach-Object { $_.Name + '=' + $_.Enabled }) -join ', '))
  # Locale-proof: enable every disabled integration service (names are
  # localized on zh-CN hosts: Guest Service Interface == U+6765U+5BBE...).
  $disabled = $allSvc | Where-Object { -not $_.Enabled }
  if ($disabled) { $disabled | Enable-VMIntegrationService; LogStep ('enabled: ' + (($disabled | ForEach-Object Name) -join ',')) }
  Get-VMNetworkAdapter -VMName $VmName -ErrorAction SilentlyContinue |
    Remove-VMNetworkAdapter -ErrorAction SilentlyContinue
  LogStep 'Network adapters removed (offline VM)'

  if ((Get-VM -Name $VmName).State -ne 'Running') { Start-VM -Name $VmName }
  Start-Sleep -Seconds 3
  $vm = Get-VM -Name $VmName
  LogStep ('VM state: ' + $vm.State)

  @{ status = 'ok'; vm_name = $VmName; state = $vm.State.ToString(); vhdx = $VhdPath;
     iso = $IsoPath; network = 'none'; next_step = 'USER installs Windows inside the VM' } |
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
