param(
    [Parameter(Mandatory = $true)]
    [string[]]$Executable,
    [Parameter(Mandatory = $true)]
    [string]$CertificateThumbprint,
    [string]$TimestampUrl
)

$ErrorActionPreference = "Stop"
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse |
        Sort-Object FullName -Descending |
        Select-Object -First 1
}
if (-not $signtool) {
    throw "signtool.exe was not found"
}

foreach ($item in $Executable) {
    $path = (Resolve-Path -LiteralPath $item).Path
    $arguments = @("sign", "/fd", "SHA256", "/sha1", $CertificateThumbprint)
    if ($TimestampUrl) {
        $arguments += @("/tr", $TimestampUrl, "/td", "SHA256")
    }
    $arguments += $path
    & $signtool.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "signing failed: $path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne "Valid") {
        throw "signature verification failed: $path ($($signature.Status))"
    }
}

Write-Output "windows_signatures=valid"
