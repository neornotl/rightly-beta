param(
    [string]$OutputDirectory = "",
    [string]$InstallerPath = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repo "release"
}
if (-not $InstallerPath) {
    $InstallerPath = Join-Path $repo "dist\Rightly-Setup.exe"
}

# Stage outside the repository first. This keeps the checked-in tree free of
# ZIP/EXE artifacts and makes it impossible to accidentally include .env,
# private user documents, local memory, logs, or model caches.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stage = Join-Path ([IO.Path]::GetTempPath()) "rightly-btc-$stamp"
New-Item -ItemType Directory -Path $stage -Force | Out-Null

function Copy-ReleaseFile([string]$relativePath) {
    $source = Join-Path $repo $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Release file missing: $relativePath"
    }
    $target = Join-Path $stage $relativePath
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}

function Copy-ReleaseDirectory([string]$relativePath) {
    $source = Join-Path $repo $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Release directory missing: $relativePath"
    }
    Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
        $full = $_.FullName
        $full -notmatch "\\(__pycache__|\.pytest_cache|private_cache|logs|results|eval)\\" -and
        $full -notmatch "\\(user_chunks\.jsonl|user_registry\.json|\.ingested_state\.json)$" -and
        $_.Extension -notin @(".npz", ".onnx", ".bin", ".sqlite3")
    } | ForEach-Object {
        $relative = $_.FullName.Substring($repo.Length + 1)
        $target = Join-Path $stage $relative
        New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}

$rootFiles = @(
    ".env.example", "CaiDat-Rightly.bat", "Rightly.bat", "start.bat",
    "TaiOllamaModel.bat", "Dockerfile", "LICENSE", "Makefile", "README.md",
    "README-NGUOI-DUNG.txt", "pyproject.toml", "requirements.txt",
    "requirements-deploy.txt", "requirements-optional.txt", "vercel.json",
    "render.yaml", "setup_installer.py", "rightly_desktop.py", "webhook_server.py"
)
$rootFiles | ForEach-Object { Copy-ReleaseFile $_ }

@("api", "app", "assets", "data", "Bach-Xuan", "tests", "web") |
    ForEach-Object { Copy-ReleaseDirectory $_ }
Copy-ReleaseFile "docs\supabase_context.sql"

# Keep only scripts required to install, start, validate, and reproduce the
# public pack. One-off debate/debug/patch scripts are intentionally omitted.
@(
    "scripts\bootstrap_offline.py", "scripts\build_rightly_exe.py",
    "scripts\build_vercel_rag.py", "scripts\detect_hardware.py",
    "scripts\make_rightly_icon.py", "scripts\predeploy_check.py",
    "scripts\preflight_offline.py", "scripts\preflight.py",
    "scripts\validate_data.py", "scripts\verify_database.py",
    "scripts\build_btc_release.ps1"
) | ForEach-Object { Copy-ReleaseFile $_ }

if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer not found: $InstallerPath. Build dist\Rightly-Setup.exe first."
}
New-Item -ItemType Directory -Path (Join-Path $stage "installer") -Force | Out-Null
Copy-Item -LiteralPath $InstallerPath -Destination (Join-Path $stage "installer\Rightly-Setup.exe") -Force

$manifest = @(
    "Rightly BTC submission package",
    "Built: $(Get-Date -Format o)",
    "Installer: installer/Rightly-Setup.exe",
    "Secrets excluded: .env, Vercel exports, service-role keys",
    "Private runtime excluded: local memory, user documents/chunks, logs, results, model caches",
    "Supabase schema: docs/supabase_context.sql"
)
$manifest | Set-Content -LiteralPath (Join-Path $stage "RELEASE-MANIFEST.txt") -Encoding utf8

if (Test-Path -LiteralPath $OutputDirectory) {
    Remove-Item -LiteralPath $OutputDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$packageDirectory = Join-Path $OutputDirectory "rightly-btc-release"
Copy-Item -LiteralPath $stage -Destination $packageDirectory -Recurse -Force
$zip = Join-Path $OutputDirectory "rightly-btc-release.zip"
Compress-Archive -Path (Join-Path $packageDirectory "*") -DestinationPath $zip -CompressionLevel Optimal -Force
Write-Output "PACKAGE=$zip"
Write-Output "STAGED=$packageDirectory"
