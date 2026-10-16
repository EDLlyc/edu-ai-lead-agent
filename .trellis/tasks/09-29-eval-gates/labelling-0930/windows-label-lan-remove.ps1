#Requires -RunAsAdministrator
# Remove the LAN rule for the labelling page (TCP 4180).
$Name = "edu-ai-labels-4180"
Remove-NetFirewallHyperVRule -Name $Name -ErrorAction SilentlyContinue
Remove-NetFirewallRule -Name $Name -ErrorAction SilentlyContinue
Write-Host "Removed the labelling page LAN rule (TCP 4180)."
