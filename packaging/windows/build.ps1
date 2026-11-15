# Build dist\L99_Screen-<version>-windows.exe (single-file GUI app). Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
$ErrorActionPreference = 'Stop'
$root = (Get-Location).Path
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$name = "L99_Screen-$version-windows"
$work = Join-Path $root 'build\windows'
New-Item -ItemType Directory -Force $work | Out-Null

Write-Host "== installing build dependencies"
python -m pip install --quiet --upgrade pyinstaller pyserial Pillow tkinterdnd2
if ($LASTEXITCODE) { throw 'pip install failed' }

Write-Host "== making icon"
$ico = Join-Path $work 'l99screen.ico'
python -c "from PIL import Image; Image.open(r'packaging\appimage\l99screen.png').save(r'$ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE) { throw 'icon failed' }

Write-Host "== building $name.exe"
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name $name --icon $ico --add-data "$ico;." `
  --paths $root `
  --collect-all tkinterdnd2 `
  --hidden-import serial.tools.list_ports `
  --workpath (Join-Path $work 'pyi') --specpath $work --distpath (Join-Path $root 'dist') `
  packaging\windows\entry.py
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

Get-Item (Join-Path $root "dist\$name.exe") | Select-Object Name, Length
