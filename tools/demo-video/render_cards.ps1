# Animated cards (Remotion, 1080p 30 fps) for polish.py. node_modules is a junction to
# C:\claude\video-tools\remotion-studio\node_modules, so nothing is installed here.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "remotion")
$out = Join-Path $PSScriptRoot "build\cards"
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($c in "Titel", "Ziele", "Datenschutz", "Abspann") {
    Write-Output "card $c"
    npx remotion render src/index.ts $c "$out\$c.mp4" --codec=h264 --crf=14 --pixel-format=yuv420p --image-format=png --log=error
}
Write-Output "cards done"
