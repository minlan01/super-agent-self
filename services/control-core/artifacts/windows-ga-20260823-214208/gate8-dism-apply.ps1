# Gate 8: host-side direct deployment - bypass the broken DVD boot entirely.
# Partition the empty VHDX (GPT), DISM-apply install.wim from the verified
# ISO, bcdboot the EFI partition, attach a NIC (offline test waived by user),
# and boot the VM from disk. ASCII-only. Elevated. Always writes JSON.
$ErrorActionPreference = 'Continue'
$Dir = 'D:\agent\Agents\super-agent-self\services\control-core\artifacts\windows-ga-20260823-214208'
$Log = Join-Path $Dir 'gate8-dism-apply.json'
$Steps = Join-Path $Dir 'gate8-dism-apply-steps.log'
$info = @{ status = 'ok' }

function LogStep($msg) { $msg | Out-File -FilePath $Steps -Append -Encoding utf8; Write-Output $msg }

try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'not elevated' }
  LogStep 'elevated ok'

  $VmName = 'ZCODE-GA-W11-20260823'
  $IsoPath = 'D:\Zcode-GA-ISO\Win11_25H2_EnterpriseEval_x64_zh-cn.iso'
  $VhdPath = 'C:\HyperV\Zcode-GA-20260823\ZCODE-GA-W11-20260823\ZCODE-GA-W11-20260823.vhdx'
  if (-not (Test-Path -LiteralPath $IsoPath)) { throw 'ISO missing' }
  if (-not (Test-Path -LiteralPath $VhdPath)) { throw 'VHDX missing' }

  # 0. VM must be off while we write its disk.
  $vm = Get-VM -Name $VmName -ErrorAction Stop
  if ($vm.State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force; Start-Sleep -Seconds 2 }
  LogStep 'VM off'

  # 1. Mount ISO for the wim.
  $img = Mount-DiskImage -ImagePath $IsoPath -PassThru -ErrorAction Stop
  $isoLetter = ($img | Get-Volume).DriveLetter
  $wim = $isoLetter + ':\sources\install.wim'
  if (-not (Test-Path $wim)) { throw "wim not found: $wim" }
  LogStep ('ISO mounted at ' + $isoLetter + ':')

  # 2. Pick the Enterprise Evaluation index.
  $wimInfo = dism /Get-WimInfo /WimFile:$wim 2>&1
  $index = $null
  foreach ($line in $wimInfo) {
    if ($line -match 'Index\s*:\s*(\d+)') { $candidate = $Matches[1] }
    if ($line -match 'Enterprise Evaluation') { $index = $candidate; break }
  }
  if (-not $index) { $index = 1 }
  LogStep ('wim index chosen: ' + $index)

  # 3. Mount the VHDX as a disk and partition GPT.
  $vhd = Mount-VHD -Path $VhdPath -PassThru -ErrorAction Stop
  $disk = Get-Disk -Number $vhd.DiskNumber
  if ($disk.PartitionStyle -eq 'RAW') { Initialize-Disk -Number $vhd.DiskNumber -PartitionStyle GPT | Out-Null }
  LogStep ('VHDX mounted as disk ' + $vhd.DiskNumber + ', partitioned GPT')

  $efi = New-Partition -DiskNumber $vhd.DiskNumber -Size 150MB -GptType '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' -AssignDriveLetter
  Format-Volume -Partition $efi -FileSystem FAT32 -NewFileSystemLabel 'System' | Out-Null
  $efiLetter = (Get-Partition -DiskNumber $vhd.DiskNumber | Where-Object { $_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' } | Get-Volume).DriveLetter
  $msr = New-Partition -DiskNumber $vhd.DiskNumber -Size 16MB -GptType '{e3c9e316-0b5c-4db8-817d-f92df00215ae}'
  $win = New-Partition -DiskNumber $vhd.DiskNumber -UseMaximumSize -AssignDriveLetter
  Format-Volume -Partition $win -FileSystem NTFS -NewFileSystemLabel 'Windows' | Out-Null
  $winLetter = (Get-Partition -DriveLetter $win.DriveLetter | Get-Volume).DriveLetter
  LogStep ('partitions: EFI=' + $efiLetter + ': Windows=' + $winLetter + ':')

  # 4. Apply the image (long step).
  LogStep ('applying install.wim index ' + $index + ' -> ' + $winLetter + ':\')
  $apply = dism /Apply-Image /ImageFile:$wim /Index:$index /ApplyDir:$winLetter`:\ 2>&1
  $apply | Select-Object -Last 5 | ForEach-Object { LogStep ([string]$_) }
  if ($LASTEXITCODE -ne 0) { throw ('dism apply failed exit ' + $LASTEXITCODE) }
  LogStep 'image applied'

  # 5. Boot files.
  $bcd = bcdboot $winLetter`:\Windows /s $efiLetter`:\ /f UEFI 2>&1
  $bcd | ForEach-Object { LogStep ([string]$_) }
  if ($LASTEXITCODE -ne 0) { throw ('bcdboot failed exit ' + $LASTEXITCODE) }
  LogStep 'bcdboot ok'

  Dismount-VHD -Path $VhdPath
  Dismount-DiskImage -ImagePath $IsoPath | Out-Null
  LogStep 'vhdx and iso dismounted'

  # 6. NIC (offline test waived by user 2026-08-24) + boot from disk.
  if (-not (Get-VMNetworkAdapter -VMName $VmName -ErrorAction SilentlyContinue)) {
    $sw = Get-VMSwitch | Select-Object -First 1
    Add-VMNetworkAdapter -VMName $VmName -SwitchName $sw.Name
    LogStep ('NIC added to switch: ' + $sw.Name)
  }
  $hdd = Get-VMHardDiskDrive -VMName $VmName | Select-Object -First 1
  Set-VMFirmware -VMName $VmName -FirstBootDevice $hdd
  LogStep 'first boot = disk'

  Start-VM -Name $VmName
  Start-Sleep -Seconds 5
  $vm = Get-VM -Name $VmName
  LogStep ('state after: ' + $vm.State)

  $info.state = $vm.State.ToString()
  $info.wim_index = $index
  $info.next = 'VM boots installed Windows -> OOBE -> local account'
}
catch {
  $info.status = 'failed'; $info.reason = $_.Exception.Message
  LogStep ('ERROR: ' + $_.Exception.Message)
  try { Dismount-VHD -Path $VhdPath -ErrorAction SilentlyContinue } catch {}
  try { Dismount-DiskImage -ImagePath $IsoPath -ErrorAction SilentlyContinue } catch {}
}
$info | ConvertTo-Json | Set-Content -LiteralPath $Log -Encoding UTF8
Get-Content $Log
if ($info.status -ne 'ok') { exit 2 }
exit 0
