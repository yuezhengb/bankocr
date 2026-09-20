param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir,
    [switch]$RequireSignature,
    [switch]$RunDefender
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $ReleaseDir).Path
$releasePath = Join-Path $root "release.json"
$release = Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8 | ConvertFrom-Json

foreach ($entry in $release.files.PSObject.Properties) {
    $relative = [string]$entry.Name
    $asset = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $asset.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "release asset escapes release directory: $relative"
    }
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
        throw "release asset is missing: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$entry.Value).ToLowerInvariant()) {
        throw "release checksum mismatch: $relative"
    }
}

$executables = Get-ChildItem -LiteralPath $root -Filter *.exe -File
foreach ($executable in $executables) {
    $signature = Get-AuthenticodeSignature -LiteralPath $executable.FullName
    if ($RequireSignature -and $signature.Status -ne "Valid") {
        throw "invalid or missing Authenticode signature: $($executable.Name)"
    }
}

if ($RunDefender) {
    $defender = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
    if (-not (Test-Path -LiteralPath $defender -PathType Leaf)) {
        throw "Microsoft Defender command-line scanner was not found"
    }
    & $defender -Scan -ScanType 3 -File $root -DisableRemediation
    if ($LASTEXITCODE -ne 0) {
        throw "Microsoft Defender scan did not pass"
    }
}

Write-Output "release_hashes=valid"
Write-Output "authenticode_required=$($RequireSignature.IsPresent)"
Write-Output "defender_scan=$($RunDefender.IsPresent)"
