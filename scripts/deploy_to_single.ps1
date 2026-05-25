[CmdletBinding()]
param(
    [string]$RemoteHost = "root@single",
    [string]$RemoteDir = "/opt/odysseia-guidance",
    [string]$ServiceName = "alyce-bot.service",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command: $Name"
    }
}

Require-Command git
Require-Command ssh
Require-Command scp
Require-Command tar

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Current directory is not inside a Git repository."
}

Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "odysseia-deploy-$timestamp"
$stageDir = Join-Path $tempRoot "package"
$archivePath = Join-Path $tempRoot "odysseia.deploy.tar.gz"
$remoteArchive = "/tmp/odysseia-deploy-$timestamp.tar.gz"

try {
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    $filesToDeploy = Get-ChildItem -Path $repoRoot -Recurse -File | Where-Object {
        $relativePath = $_.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')

        if ($relativePath -eq ".env") { return $false }
        if ($relativePath -eq "package.json") { return $false }
        if ($relativePath -eq "package-lock.json") { return $false }
        if ($relativePath -eq "odysseia-deploy.tar.gz") { return $false }
        if ($relativePath -like "*.deploy.tar.gz") { return $false }
        if ($relativePath -like "*.pyc") { return $false }
        if ($relativePath -like "*.docx") { return $false }
        if ($relativePath -like "*.jpg") { return $false }
        if ($relativePath -like "*.jpeg") { return $false }
        if ($relativePath -like "*.png") { return $false }
        if ($relativePath -like "*.webp") { return $false }
        if ($relativePath -like "*.gif") { return $false }
        if ($relativePath -like "*.ttf") { return $false }
        if ($relativePath -like "*.woff") { return $false }
        if ($relativePath -like "*.woff2") { return $false }
        if ($relativePath.StartsWith(".devcontainer/")) { return $false }
        if ($relativePath.StartsWith(".git/")) { return $false }
        if ($relativePath.StartsWith(".venv/")) { return $false }
        if ($relativePath.StartsWith("assets/")) { return $false }
        if ($relativePath.StartsWith("caddy/")) { return $false }
        if ($relativePath.StartsWith("data/")) { return $false }
        if ($relativePath.StartsWith("docs/")) { return $false }
        if ($relativePath.StartsWith("logs/")) { return $false }
        if ($relativePath.StartsWith("node_modules/")) { return $false }
        if ($relativePath.StartsWith("plans/")) { return $false }
        if ($relativePath.StartsWith("tests/")) { return $false }
        if ($relativePath.StartsWith("web/")) { return $false }
        if ($relativePath.Contains("/__pycache__/")) { return $false }
        if ($relativePath.StartsWith("__pycache__/")) { return $false }
        if ($relativePath.StartsWith("src/chat/assets/")) { return $false }
        if ($relativePath.StartsWith("src/chat/features/games/blackjack-web/")) { return $false }
        if ($relativePath.StartsWith("src/chat/features/tarot/cards/")) { return $false }
        if ($relativePath.StartsWith("src/guidance/")) { return $false }

        return $true
    }

    if (-not $filesToDeploy) {
        throw "No deployable files were found."
    }

    foreach ($file in $filesToDeploy) {
        $relativePath = $file.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
        $sourcePath = $file.FullName
        $targetPath = Join-Path $stageDir $relativePath
        $targetDir = Split-Path -Parent $targetPath
        if ($targetDir) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    }

    tar -czf $archivePath -C $stageDir .
    if (-not (Test-Path $archivePath -PathType Leaf)) {
        throw "Failed to build deploy archive: $archivePath"
    }

    Write-Host "Uploading deploy archive to $RemoteHost ..."
    scp $archivePath "${RemoteHost}:$remoteArchive"

    $skipInstallFlag = if ($SkipInstall) { "1" } else { "0" }
    $remoteScript = @'
set -euo pipefail

REMOTE_DIR='__REMOTE_DIR__'
SERVICE_NAME='__SERVICE_NAME__'
ARCHIVE_PATH='__ARCHIVE_PATH__'
DEPLOY_TS='__DEPLOY_TS__'
SKIP_INSTALL='__SKIP_INSTALL__'
RELEASE_DIR="/tmp/odysseia-release-$DEPLOY_TS"
BACKUP_DIR="$REMOTE_DIR/data/deploy-backups"

mkdir -p "$BACKUP_DIR"

if [ -d "$REMOTE_DIR" ]; then
  BACKUP_PATH="$BACKUP_DIR/code-$DEPLOY_TS.tar.gz"
  tar \
    --exclude='.venv' \
    --exclude='data' \
    --exclude='.env' \
    --exclude='requirements-chatonly.txt' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.bak-*' \
    -czf "$BACKUP_PATH" -C "$REMOTE_DIR" .
  echo "backup=$BACKUP_PATH"
fi

mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$RELEASE_DIR"

systemctl stop "$SERVICE_NAME"

export REMOTE_DIR RELEASE_DIR
python3 - <<'PY'
from pathlib import Path
import os
import shutil

remote = Path(os.environ["REMOTE_DIR"])
release = Path(os.environ["RELEASE_DIR"])
preserve = {".env", ".venv", "data", "requirements-chatonly.txt"}

remote.mkdir(parents=True, exist_ok=True)

for item in list(remote.iterdir()):
    name = item.name
    if name in preserve or ".bak-" in name:
        continue
    if item.is_dir():
        shutil.rmtree(item)
    else:
        item.unlink()

for item in release.iterdir():
    target = remote / item.name
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    if item.is_dir():
        shutil.copytree(item, target)
    else:
        shutil.copy2(item, target)
PY

if [ ! -x "$REMOTE_DIR/.venv/bin/python" ]; then
  python3 -m venv "$REMOTE_DIR/.venv"
fi

if [ ! -x "$REMOTE_DIR/.venv/bin/pip" ]; then
  "$REMOTE_DIR/.venv/bin/python" -m ensurepip --upgrade
fi

REQ_FILE="$REMOTE_DIR/requirements.txt"
if [ -f "$REMOTE_DIR/requirements-chatonly.txt" ]; then
  REQ_FILE="$REMOTE_DIR/requirements-chatonly.txt"
fi

if [ "$SKIP_INSTALL" != "1" ]; then
  "$REMOTE_DIR/.venv/bin/pip" install --upgrade pip
  "$REMOTE_DIR/.venv/bin/pip" install -r "$REQ_FILE"
fi

find "$REMOTE_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$REMOTE_DIR" -type f -name '*.pyc' -delete

systemctl start "$SERVICE_NAME"
sleep 4
systemctl is-active "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager

rm -rf "$RELEASE_DIR" "$ARCHIVE_PATH"
'@
    $remoteScript = $remoteScript.Replace("__REMOTE_DIR__", $RemoteDir)
    $remoteScript = $remoteScript.Replace("__SERVICE_NAME__", $ServiceName)
    $remoteScript = $remoteScript.Replace("__ARCHIVE_PATH__", $remoteArchive)
    $remoteScript = $remoteScript.Replace("__DEPLOY_TS__", $timestamp)
    $remoteScript = $remoteScript.Replace("__SKIP_INSTALL__", $skipInstallFlag)

    Write-Host "Starting remote deploy ..."
    ($remoteScript -replace "`r", "") | ssh $RemoteHost "bash -s"
    Write-Host "Deploy finished."
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -Recurse -Force $tempRoot
    }
}
