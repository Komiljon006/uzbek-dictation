# RubaiSTT Dictation — Windows o'rnatuvchi (hammasini o'zi qiladi).
# ORNATISH.bat shu faylni ishga tushiradi. Uzilib qolsa qaytadan bosing — davom etadi.
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Host.UI.RawUI.WindowTitle = "RubaiSTT — o'rnatish"

$R      = Join-Path $env:LOCALAPPDATA "RubaiSTT"
$Bin    = Join-Path $R "bin"
$Models = Join-Path $R "models"
$Py     = Join-Path $R "py"
$App    = Join-Path $R "app"
$Tmp    = Join-Path $R "tmp"
$Dl     = Join-Path $R "yuklab"
$Here   = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($d in @($R, $Bin, $Models, $Py, $App, $Tmp, $Dl)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

$PY_URL    = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
$PIP_URL   = "https://bootstrap.pypa.io/get-pip.py"
$WH_URL    = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip"
$MODEL_URL = "https://github.com/Komiljon006/uzbek-dictation/releases/download/v1.0/ggml-rubaistt.bin"
$MODEL_SIZE = 823369796

function Yuk($url, $out, $nom) {
    if (Test-Path $out) { Write-Host "   $nom — bor, o'tkazib yuborildi" -ForegroundColor DarkGray; return }
    Write-Host "==> $nom yuklanmoqda..." -ForegroundColor Cyan
    $tmp = "$out.qism"
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (Test-Path $curl) {
        # curl davom ettira oladi (-C -): 800 MB model uzilsa qaytadan boshlamaydi
        & $curl -L --retry 5 --retry-delay 3 -C - --progress-bar -o $tmp $url
        if ($LASTEXITCODE -ne 0) { throw "$nom yuklanmadi (curl $LASTEXITCODE). Internetni tekshirib qaytadan bosing." }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    }
    Move-Item -Force $tmp $out
}

Write-Host ""
Write-Host "  RubaiSTT Dictation — o'zbekcha ovozli yozuv (Windows)" -ForegroundColor Green
Write-Host "  Papka: $R"
Write-Host ""

# 1) Python (embeddable, tizimga o'rnatilmaydi — faqat shu papkada)
$pyexe = Join-Path $Py "python.exe"
if (-not (Test-Path $pyexe)) {
    Yuk $PY_URL (Join-Path $Dl "python.zip") "Python 3.12"
    Expand-Archive -Force (Join-Path $Dl "python.zip") $Py
}
$pth = Get-ChildItem $Py -Filter "python3*._pth" | Select-Object -First 1
if ($pth) {
    $c = Get-Content $pth.FullName
    if ($c -notcontains "import site") {
        ($c | ForEach-Object { if ($_ -eq "#import site") { "import site" } else { $_ } }) | Set-Content $pth.FullName
        if ((Get-Content $pth.FullName) -notcontains "import site") { Add-Content $pth.FullName "import site" }
    }
    if ((Get-Content $pth.FullName) -notcontains "Lib\site-packages") { Add-Content $pth.FullName "Lib\site-packages" }
}
if (-not (Test-Path (Join-Path $Py "Scripts\pip.exe"))) {
    Yuk $PIP_URL (Join-Path $Dl "get-pip.py") "pip"
    Write-Host "==> pip o'rnatilmoqda..." -ForegroundColor Cyan
    & $pyexe (Join-Path $Dl "get-pip.py") --no-warn-script-location | Out-Null
}
Write-Host "==> Python kutubxonalari (sounddevice, pynput, pystray)..." -ForegroundColor Cyan
& $pyexe -m pip install --no-warn-script-location --disable-pip-version-check -q sounddevice numpy pynput pystray pillow
if ($LASTEXITCODE -ne 0) { throw "pip o'rnatolmadi. Internetni tekshirib qaytadan bosing." }

# 2) whisper.cpp (tayyor .exe — kompilyatsiya yo'q)
if (-not (Test-Path (Join-Path $Bin "whisper-server.exe"))) {
    Yuk $WH_URL (Join-Path $Dl "whisper.zip") "whisper.cpp (dvigatel)"
    Expand-Archive -Force (Join-Path $Dl "whisper.zip") (Join-Path $Dl "whisper")
    Get-ChildItem (Join-Path $Dl "whisper") -Recurse -Include *.exe,*.dll | ForEach-Object { Copy-Item -Force $_.FullName $Bin }
}

# 3) Model (823 MB) — eng uzun qadam
$model = Join-Path $Models "ggml-rubaistt.bin"
if ((Test-Path $model) -and ((Get-Item $model).Length -ne $MODEL_SIZE)) { Remove-Item -Force $model }
Yuk $MODEL_URL $model "rubaiSTT modeli (823 MB — 5–30 daqiqa)"
if ((Get-Item $model).Length -ne $MODEL_SIZE) { throw "Model to'liq yuklanmadi — ORNATISH.bat ni qaytadan bosing (davom etadi)." }

# 4) Ilova fayllari
Copy-Item -Force (Join-Path $Here "rubaistt.py") $App
Copy-Item -Force (Join-Path $Here "OQING.txt") $R -ErrorAction SilentlyContinue
$vbs = Join-Path $App "RubaiSTT.vbs"
@"
' RubaiSTT — konsolsiz ishga tushirish
Set sh = CreateObject("WScript.Shell")
sh.Run """$($Py)\pythonw.exe"" ""$($App)\rubaistt.py""", 0, False
"@ | Set-Content -Encoding ASCII $vbs

# 5) Kompyuter yoqilganda o'zi ishga tushsin (Startup yorlig'i)
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "RubaiSTT.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk); $sc.TargetPath = $vbs; $sc.WorkingDirectory = $App; $sc.Description = "RubaiSTT Dictation"; $sc.Save()
$desk = Join-Path ([Environment]::GetFolderPath("Desktop")) "RubaiSTT.lnk"
$sc2 = $ws.CreateShortcut($desk); $sc2.TargetPath = $vbs; $sc2.WorkingDirectory = $App; $sc2.Description = "RubaiSTT Dictation"; $sc2.Save()

# 6) Ishga tushirish
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Py*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`""

Write-Host ""
Write-Host "  OK — O'RNATILDI. Soat yonida yashil mikrofon belgisi chiqadi (10–40 soniyada model yuklanadi)." -ForegroundColor Green
Write-Host "  Sinab ko'ring: Notepad oching → Ctrl+Alt+D → gapiring → Ctrl+Alt+D → matn chiqadi."
Write-Host "  Birinchi marta Windows mikrofon ruxsatini so'rashi mumkin — ruxsat bering."
Write-Host ""
