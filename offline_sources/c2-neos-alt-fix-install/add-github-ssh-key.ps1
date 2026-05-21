Write-Host "Refreshing GitHub CLI auth for admin:public_key..."
gh auth refresh -h github.com -s admin:public_key --clipboard
if ($LASTEXITCODE -ne 0) {
  Write-Host "Auth refresh failed. Press Enter to close."
  Read-Host
  exit $LASTEXITCODE
}
Write-Host "Adding SSH key to GitHub account rebelscumm..."
gh ssh-key add "$env:USERPROFILE\.ssh\id_ed25519.pub" --title "rebelscumm-c2-neos-installer"
Write-Host "Done. Press Enter to close."
Read-Host
