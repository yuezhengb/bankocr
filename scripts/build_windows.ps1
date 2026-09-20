param(
    [ValidateSet("auto", "nuitka", "pyinstaller")]
    [string]$Backend = "auto",
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputRoot = "work\windows-build"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = if ([System.IO.Path]::IsPathRooted($Python)) { $Python } else { Join-Path $RepoRoot $Python }
$BuildRoot = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot))
}
$env:PYTHONPATH = Join-Path $RepoRoot "src"

function Invoke-Python([string[]]$Arguments) {
    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Test-Nuitka {
    & $PythonPath -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('nuitka') else 1)"
    return $LASTEXITCODE -eq 0
}

function Build-Nuitka {
    $NuitkaRoot = Join-Path $BuildRoot "nuitka"
    $Common = @(
        "-m", "nuitka",
        "--standalone",
        "--include-package=bankocr",
        "--include-package-data=rapidocr",
        "--include-data-dir=$RepoRoot\templates=templates"
    )
    Invoke-Python ($Common + @(
        "--output-dir=$NuitkaRoot\process",
        "--output-filename=bankocr-process.exe",
        "--nofollow-import-to=PySide6",
        "$RepoRoot\src\bankocr\cli.py"
    ))
    Invoke-Python ($Common + @(
        "--output-dir=$NuitkaRoot\template",
        "--output-filename=bankocr-template.exe",
        "--nofollow-import-to=PySide6",
        "$RepoRoot\src\bankocr\template_cli.py"
    ))
    Invoke-Python ($Common + @(
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",
        "--output-dir=$NuitkaRoot\review",
        "--output-filename=bankocr-review.exe",
        "$RepoRoot\src\bankocr\review_cli.py"
    ))
    Invoke-Python ($Common + @(
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",
        "--output-dir=$NuitkaRoot\gui",
        "--output-filename=bankocr-gui.exe",
        "$RepoRoot\src\bankocr\gui_cli.py"
    ))
    Write-Output "backend=nuitka"
    Write-Output "output=$NuitkaRoot"
}

function Build-PyInstaller {
    $DistRoot = Join-Path $BuildRoot "pyinstaller\dist"
    $WorkRoot = Join-Path $BuildRoot "pyinstaller\work"
    foreach ($Spec in @("bankocr.spec", "bankocr-template.spec", "bankocr-review.spec", "bankocr-gui.spec")) {
        $Name = [System.IO.Path]::GetFileNameWithoutExtension($Spec)
        Invoke-Python @(
            "-m", "PyInstaller", "--clean", "--noconfirm",
            "$RepoRoot\packaging\windows\$Spec",
            "--distpath", $DistRoot,
            "--workpath", "$WorkRoot\$Name"
        )
    }
    Write-Output "backend=pyinstaller"
    Write-Output "output=$DistRoot"
}

if ($Backend -eq "nuitka") {
    if (-not (Test-Nuitka)) {
        throw "Nuitka is not installed; install the packaging-nuitka extra or use -Backend pyinstaller"
    }
    Build-Nuitka
} elseif ($Backend -eq "pyinstaller") {
    Build-PyInstaller
} elseif (Test-Nuitka) {
    try {
        Build-Nuitka
    } catch {
        Write-Warning "Nuitka build failed; using the PyInstaller fallback: $_"
        Build-PyInstaller
    }
} else {
    Build-PyInstaller
}
