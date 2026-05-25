[CmdletBinding()]
param(
    [string]$RemoteName = "origin",
    [string]$Branch = "main",
    [string]$RemoteUrl
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command: $Name"
    }
}

function Should-IncludeFile {
    param([string]$RelativePath)

    $excludedExact = @(
        ".env",
        "package.json",
        "package-lock.json",
        "odysseia-deploy.tar.gz",
        "dive"
    )

    $excludedPrefixes = @(
        ".devcontainer/",
        ".git/",
        ".venv/",
        "assets/",
        "caddy/",
        "data/",
        "docs/",
        "logs/",
        "node_modules/",
        "plans/",
        "tests/",
        "web/",
        "src/chat/assets/",
        "src/chat/features/games/blackjack-web/",
        "src/chat/features/tarot/cards/",
        "src/guidance/"
    )

    $excludedSuffixes = @(
        ".deploy.tar.gz",
        ".docx",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".pyc",
        ".ttf",
        ".webp",
        ".woff",
        ".woff2"
    )

    if ($excludedExact -contains $RelativePath) {
        return $false
    }

    foreach ($prefix in $excludedPrefixes) {
        if ($RelativePath.StartsWith($prefix)) {
            return $false
        }
    }

    foreach ($suffix in $excludedSuffixes) {
        if ($RelativePath.EndsWith($suffix)) {
            return $false
        }
    }

    if ($RelativePath.Contains("/__pycache__/")) {
        return $false
    }

    return $true
}

Require-Command git

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Current directory is not inside a Git repository."
}

if (-not $RemoteUrl) {
    $RemoteUrl = (git remote get-url --push $RemoteName).Trim()
}

if (-not $RemoteUrl) {
    throw "Unable to resolve remote URL. Pass -RemoteUrl explicitly."
}

Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "alyce-github-publish-$timestamp"
$stageDir = Join-Path $tempRoot "snapshot"

try {
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    $filesToPublish = Get-ChildItem -Path $repoRoot -Recurse -File | Where-Object {
        $relativePath = $_.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
        Should-IncludeFile -RelativePath $relativePath
    }

    if (-not $filesToPublish) {
        throw "No publishable files were found."
    }

    foreach ($file in $filesToPublish) {
        $relativePath = $file.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
        $targetPath = Join-Path $stageDir $relativePath
        $targetDir = Split-Path -Parent $targetPath
        if ($targetDir) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
    }

    $fileCount = ($filesToPublish | Measure-Object).Count
    $totalBytes = ($filesToPublish | Measure-Object -Property Length -Sum).Sum
    $totalMiB = [Math]::Round($totalBytes / 1MB, 2)
    Write-Host "Prepared snapshot with $fileCount files ($totalMiB MiB)."

    Push-Location $stageDir
    try {
        git init -b $Branch | Out-Null
        git config user.name "Alyce Snapshot Bot"
        git config user.email "alyce-snapshot@local"
        git add .
        git commit -m "Sync Alyce bot snapshot $timestamp" | Out-Null

        git remote add origin $RemoteUrl

        $pushArgs = @(
            "-c", "http.version=HTTP/1.1",
            "-c", "http.postBuffer=524288000",
            "-c", "core.compression=0",
            "push", "--force", "-u", "origin", $Branch
        )

        Write-Host "Pushing snapshot to $RemoteUrl ..."
        & git @pushArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Git push failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Snapshot published successfully."
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -Recurse -Force $tempRoot
    }
}
