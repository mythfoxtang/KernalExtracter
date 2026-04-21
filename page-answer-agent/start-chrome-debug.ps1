$StartUrl = $args[0]

$programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
$programFiles = [Environment]::GetFolderPath("ProgramFiles")

$chromePaths = @(
  (Join-Path $programFiles "Google\Chrome\Application\chrome.exe"),
  (Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe")
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
  Write-Error "Google Chrome was not found."
  exit 1
}

$debugProfileDir = Join-Path $env:TEMP "page-answer-agent-chrome-profile"
if (-not (Test-Path $debugProfileDir)) {
  New-Item -ItemType Directory -Path $debugProfileDir | Out-Null
}

if ([string]::IsNullOrWhiteSpace($StartUrl)) {
  $StartUrl = "https://www.google.com"
}

Start-Process -FilePath $chrome -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=$debugProfileDir",
  "--new-window",
  $StartUrl
)
