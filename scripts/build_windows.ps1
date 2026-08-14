param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = (Get-Content -Raw (Join-Path $projectRoot "VERSION")).Trim()
$distDirectory = Join-Path $projectRoot "dist"
$buildDirectory = Join-Path $projectRoot "build"
$packageDirectory = Join-Path $distDirectory "ProxmoxLxcSshManager-v$version-windows-x64"
$archivePath = "$packageDirectory.zip"

if (-not $SkipTests) {
    python -m unittest discover -s (Join-Path $projectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Test run failed." }
}

python -m PyInstaller --noconfirm --clean `
    --distpath $distDirectory `
    --workpath $buildDirectory `
    (Join-Path $projectRoot "packaging\ProxmoxLxcSshManager.spec")
if ($LASTEXITCODE -ne 0) { throw "EXE build failed." }

if (Test-Path -LiteralPath $packageDirectory) {
    Remove-Item -LiteralPath $packageDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path $packageDirectory | Out-Null
Copy-Item -LiteralPath (Join-Path $distDirectory "ProxmoxLxcSshManager.exe") -Destination $packageDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $packageDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $packageDirectory

if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -Path (Join-Path $packageDirectory "*") -DestinationPath $archivePath -CompressionLevel Optimal

Write-Host "EXE:     $(Join-Path $distDirectory 'ProxmoxLxcSshManager.exe')"
Write-Host "Package: $archivePath"
