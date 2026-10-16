#Requires -RunAsAdministrator
# Let phones and PCs on the same Wi-Fi open the labelling page served from WSL (mirrored networking).
# Scope: inbound TCP 4180 only, from the local subnet only. Undo: windows-label-lan-remove.ps1
param([string]$Subnet = "192.168.110.0/24")
$ErrorActionPreference = "Stop"
$Name = "edu-ai-labels-4180"
$Display = "edu-ai labelling 4180 (LAN only)"
$WslVmCreator = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"

# WSL traffic is filtered by the Hyper-V firewall, which blocks inbound by default.
Remove-NetFirewallHyperVRule -Name $Name -ErrorAction SilentlyContinue
New-NetFirewallHyperVRule -Name $Name -DisplayName $Display -Direction Inbound `
  -VMCreatorId $WslVmCreator -Protocol TCP -LocalPorts 4180 -RemoteAddresses $Subnet `
  -Action Allow | Out-Null

# Matching host rule (the Wi-Fi profile is Public), same port and subnet.
Remove-NetFirewallRule -Name $Name -ErrorAction SilentlyContinue
New-NetFirewallRule -Name $Name -DisplayName $Display -Direction Inbound -Protocol TCP `
  -LocalPort 4180 -RemoteAddress $Subnet -Profile Any -Action Allow | Out-Null

Write-Host "Allowed: $Subnet -> TCP 4180 (labelling page). Remove with windows-label-lan-remove.ps1"
