$ErrorActionPreference = "Stop"

$ip = "192.168.12.234"
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = Join-Path $repoDir "c2-neos-alt-fix-install.exe"
$key = Join-Path $env:USERPROFILE ".ssh\id_ed25519"

Write-Host "Waiting for SSH access to $ip with $key..."
Write-Host "If this keeps waiting, re-enter or refresh GitHub username 'rebelscumm' on the comma two setup screen."

while ($true) {
  ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 "comma@$ip" exit 2>$null
  if ($LASTEXITCODE -eq 0) {
    break
  }

  Write-Host "$(Get-Date -Format T) - SSH not ready yet; retrying in 10 seconds..."
  Start-Sleep -Seconds 10
}

Write-Host "SSH is ready. Starting openpilot-JVE installer..."
$inputText = "$ip`n1`n`n"
$inputText | & $installer
