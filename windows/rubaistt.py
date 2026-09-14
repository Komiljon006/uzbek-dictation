# -*- coding: utf-8 -*-
"""RubaiSTT Dictation — Windows (tray ilova).

Istalgan dasturda Ctrl+Alt+D → o'zbekcha gapiring → Ctrl+Alt+D → matn kursor
turgan joyga yoziladi. Butunlay oflayn: rubaiSTT v2 medium (q8_0) + whisper.cpp.

Tuzilishi (Mac versiyasi bilan bir xil mantiq):
  hotkey (pynput) → mikrofon 16 kHz mono (sounddevice) → WAV →
  whisper-server (model xotirada, tez) yoki whisper-cli (zaxira) →
  clipboard + Ctrl+V (ctypes SendInput) → matn joyida.

Fayllar (%LOCALAPPDATA%\\RubaiSTT):
  bin\\whisper-server.exe, bin\\whisper-cli.exe, models\\ggml-rubaistt.bin,
  app\\rubaistt.py, sozlama.json, log.txt
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import wave
from pathlib import Path

WIN = platform.system() == "Windows"
ROOT = Path(os.environ.get("RUBAISTT_HOME") or (
    Path(os.environ["LOCALAPPDATA"]) / "RubaiSTT" if WIN else Path.home() / "rubai-stt"))
BIN, MODELS, TMP = ROOT / "bin", ROOT / "models", ROOT / "tmp"
MODEL = MODELS / "ggml-rubaistt.bin"
SOZLAMA = ROOT / "sozlama.json"
LOG = ROOT / "log.txt"
EXE = ".exe" if WIN else ""
SERVER = BIN / f"whisper-server{EXE}"
CLI = BIN / f"whisper-cli{EXE}"
PORT = 8178
SR = 16000
THREADS = max(2, min(8, (os.cpu_count() or 4) - 1))
HOTKEY = "<ctrl>+<alt>+d"

for d in (TMP,):
    d.mkdir(parents=True, exist_ok=True)


def log(m: str) -> None:
    line = f"{time.strftime('%d.%m %H:%M:%S')} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sozlama() -> dict:
    try:
        return json.loads(SOZLAMA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sozlama_yoz(d: dict) -> None:
    SOZLAMA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ ovoz signali

def beep(boshlandi: bool) -> None:
    try:
        if WIN:
            import winsound
            winsound.Beep(880 if boshlandi else 660, 120)
        else:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff" if boshlandi
                              else "/System/Library/Sounds/Pop.aiff"])
    except Exception:
        pass


# ------------------------------------------------------------------ mikrofon

class Yozuvchi:
    """sounddevice bilan 16 kHz mono yozib oladi (default mikrofon yoki sozlamadagi)."""

    def __init__(self) -> None:
        self.stream = None
        self.bolaklar: list = []
        self.lock = threading.Lock()

    def boshla(self, device=None) -> None:
        import sounddevice as sd
        self.bolaklar = []

        def cb(indata, frames, t, status):
            with self.lock:
                self.bolaklar.append(bytes(indata))

        self.stream = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16",
                                        device=device, callback=cb, blocksize=1600)
        self.stream.start()

    def tugat(self) -> Path | None:
        if not self.stream:
            return None
        self.stream.stop(); self.stream.close(); self.stream = None
        with self.lock:
            data = b"".join(self.bolaklar)
        if len(data) < SR * 2 * 0.4:                 # 0,4 s dan qisqa — bo'sh
            return None
        # jimlik — whisper jimlikka «musiqa» deb to'qib chiqaradi, oldini olamiz
        try:
            import array
            a = array.array("h", data)
            rms = (sum(x * x for x in a[::4]) / max(1, len(a) // 4)) ** 0.5
            if rms < 120:
                log(f"jimlik (rms {rms:.0f}) — tashlandi"); return None
        except Exception:
            pass
        yol = TMP / f"{uuid.uuid4().hex}.wav"
        with wave.open(str(yol), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data)
        return yol


# ------------------------------------------------------------------ tanib olish

class Tanuvchi:
    """whisper-server (model xotirada) — bo'lmasa whisper-cli."""

    def __init__(self) -> None:
        self.proc = None
        self.tayyor = False

    def server_boshla(self) -> None:
        if not SERVER.exists():
            log("whisper-server yo'q — CLI rejimi"); return
        try:
            flags = {}
            if WIN:
                flags["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                [str(SERVER), "-m", str(MODEL), "-l", "uz", "-t", str(THREADS), "-bs", "5",
                 "--host", "127.0.0.1", "--port", str(PORT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(BIN), **flags)
            for _ in range(120):                      # model yuklanguncha (≤60 s)
                time.sleep(0.5)
                if self.proc.poll() is not None:
                    log("whisper-server to'xtadi — CLI rejimi"); self.proc = None; return
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
                    self.tayyor = True; log(f"whisper-server tayyor ({THREADS} ip)"); return
                except Exception:
                    continue
            log("whisper-server javob bermadi — CLI rejimi")
        except Exception as e:
            log(f"server xato: {e}")

    def tanib_ol(self, wav: Path) -> str:
        if self.tayyor and self.proc and self.proc.poll() is None:
            try:
                return self._server(wav)
            except Exception as e:
                log(f"server tanish xato: {e} — CLI")
        return self._cli(wav)

    def _server(self, wav: Path) -> str:
        chegara = uuid.uuid4().hex
        tana = b""
        for nom, qiymat in (("response_format", "json"), ("language", "uz"),
                            ("temperature", "0.0"), ("temperature_inc", "0.2")):
            tana += (f"--{chegara}\r\nContent-Disposition: form-data; name=\"{nom}\"\r\n\r\n"
                     f"{qiymat}\r\n").encode()
        tana += (f"--{chegara}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
        tana += wav.read_bytes() + f"\r\n--{chegara}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/inference", data=tana,
                                     headers={"Content-Type": f"multipart/form-data; boundary={chegara}"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode("utf-8"))
        return " ".join((d.get("text") or "").split())

    def _cli(self, wav: Path) -> str:
        flags = {"creationflags": 0x08000000} if WIN else {}
        r = subprocess.run([str(CLI), "-m", str(MODEL), "-f", str(wav), "-l", "uz", "-bs", "5",
                            "-t", str(THREADS), "-nt", "--no-prints"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300, cwd=str(BIN), **flags)
        return " ".join(r.stdout.split())

    def yop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


# ------------------------------------------------------------------ matnni joylash

def matn_qoy(matn: str) -> None:
    """Clipboard + Ctrl+V. Oldingi clipboard matni 1,5 s dan keyin qaytariladi."""
    if not matn:
        return
    if WIN:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
        eski = None
        for _ in range(10):
            if u32.OpenClipboard(None):
                break
            time.sleep(0.05)
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if h:
                p = k32.GlobalLock(h)
                if p:
                    eski = ctypes.wstring_at(p); k32.GlobalUnlock(h)
            u32.EmptyClipboard()
            buf = (matn + "\0").encode("utf-16-le")
            hg = k32.GlobalAlloc(GMEM_MOVEABLE, len(buf))
            p = k32.GlobalLock(hg)
            ctypes.memmove(p, buf, len(buf)); k32.GlobalUnlock(hg)
            u32.SetClipboardData(CF_UNICODETEXT, hg)
        finally:
            u32.CloseClipboard()
        time.sleep(0.15)
        _ctrl_v()
        if eski is not None:
            def qaytar():
                time.sleep(1.5)
                try:
                    if u32.OpenClipboard(None):
                        u32.EmptyClipboard()
                        b2 = (eski + "\0").encode("utf-16-le")
                        hg2 = k32.GlobalAlloc(GMEM_MOVEABLE, len(b2))
                        p2 = k32.GlobalLock(hg2); ctypes.memmove(p2, b2, len(b2)); k32.GlobalUnlock(hg2)
                        u32.SetClipboardData(CF_UNICODETEXT, hg2); u32.CloseClipboard()
                except Exception:
                    pass
            threading.Thread(target=qaytar, daemon=True).start()
    else:                                              # macOS — faqat sinov uchun
        subprocess.run(["pbcopy"], input=matn.encode("utf-8"))
        time.sleep(0.15)
        subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'])


def _ctrl_v() -> None:
    import ctypes
    from ctypes import wintypes
    VK_CONTROL, VK_V, KEYEVENTF_KEYUP, INPUT_KEYBOARD = 0x11, 0x56, 0x0002, 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def key(vk, up=False):
        i = INPUT(); i.type = INPUT_KEYBOARD
        i.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)
        return i

    # Ctrl+Alt+D dan qolgan Ctrl/Alt bosilgan bo'lishi mumkin — avval qo'yib yuboramiz
    seq = (key(0x12, True), key(0x11, True), key(0x44, True),
           key(VK_CONTROL), key(VK_V), key(VK_V, True), key(VK_CONTROL, True))
    arr = (INPUT * len(seq))(*seq)
    ctypes.windll.user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


# ------------------------------------------------------------------ ilova

class Ilova:
    def __init__(self) -> None:
        self.yozuvchi = Yozuvchi()
        self.tanuvchi = Tanuvchi()
        self.holat = "tayyor"          # tayyor · yozilmoqda · ogirilmoqda
        self.icon = None
        self.qulf = threading.Lock()

    # --- tray ---
    def rasm(self, rang: str):
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((4, 4, 60, 60), fill=rang)
        d.rounded_rectangle((24, 12, 40, 38), radius=8, fill="white")
        d.rectangle((30, 38, 34, 50), fill="white")
        d.rectangle((22, 50, 42, 54), fill="white")
        return im

    def holat_qoy(self, holat: str) -> None:
        self.holat = holat
        rang = {"tayyor": "#2e7d32", "yozilmoqda": "#d32f2f", "ogirilmoqda": "#f9a825"}[holat]
        matn = {"tayyor": "RubaiSTT — Ctrl+Alt+D bosib gapiring",
                "yozilmoqda": "🔴 Yozilmoqda… (Ctrl+Alt+D — to'xtatish)",
                "ogirilmoqda": "✍️ Matnga o'girilmoqda…"}[holat]
        if self.icon:
            self.icon.icon = self.rasm(rang)
            self.icon.title = matn

    # --- hotkey ---
    def tugma(self) -> None:
        if not self.qulf.acquire(blocking=False):
            return
        try:
            if self.holat == "tayyor":
                try:
                    self.yozuvchi.boshla(sozlama().get("mikrofon"))
                except Exception as e:
                    log(f"mikrofon xato: {e}")
                    if self.icon:
                        self.icon.notify("Mikrofon ochilmadi. Sozlamalar → Maxfiylik → Mikrofon → "
                                         "ish stoli ilovalariga ruxsat bering.", "RubaiSTT")
                    return
                self.holat_qoy("yozilmoqda"); beep(True)
            elif self.holat == "yozilmoqda":
                beep(False)
                wav = self.yozuvchi.tugat()
                self.holat_qoy("ogirilmoqda")
                threading.Thread(target=self.ogir, args=(wav,), daemon=True).start()
        finally:
            self.qulf.release()

    def ogir(self, wav) -> None:
        try:
            if wav is None:
                return
            t0 = time.time()
            matn = self.tanuvchi.tanib_ol(wav)
            log(f"{time.time() - t0:.1f}s → {matn[:80]}")
            if matn:
                matn_qoy(matn + " ")
            elif self.icon:
                self.icon.notify("Hech narsa eshitilmadi — mikrofonga yaqinroq gapiring.", "RubaiSTT")
        except Exception as e:
            log(f"o'girish xato: {e}")
        finally:
            try:
                wav and wav.unlink(missing_ok=True)
            except Exception:
                pass
            self.holat_qoy("tayyor")

    # --- menyu ---
    def mikrofonlar(self):
        import sounddevice as sd
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"]))
        return out

    def menyu(self):
        import pystray
        s = sozlama()

        def mik_tanla(idx):
            def _f(icon, item):
                d = sozlama(); d["mikrofon"] = idx; sozlama_yoz(d)
            return _f

        def mik_tekshir(idx):
            return lambda item: sozlama().get("mikrofon") == idx

        mlar = [pystray.MenuItem(nom[:40], mik_tanla(i), checked=mik_tekshir(i), radio=True)
                for i, nom in self.mikrofonlar()]
        mlar.insert(0, pystray.MenuItem("Standart (Windows tanlagan)", mik_tanla(None),
                                        checked=lambda item: sozlama().get("mikrofon") is None, radio=True))
        return pystray.Menu(
            pystray.MenuItem("RubaiSTT — Ctrl+Alt+D: gapiring, yana Ctrl+Alt+D: yozadi", None, enabled=False),
            pystray.MenuItem("🎤 Mikrofon", pystray.Menu(*mlar)),
            pystray.MenuItem("📄 Log faylni ochish", lambda i, it: os.startfile(LOG) if WIN else None),
            pystray.MenuItem("Chiqish", self.chiqish))

    def chiqish(self, icon=None, item=None) -> None:
        self.tanuvchi.yop()
        if self.icon:
            self.icon.stop()
        os._exit(0)

    def ishga_tushir(self) -> None:
        import pystray
        from pynput import keyboard
        log(f"RubaiSTT boshlandi · {platform.platform()} · model: {MODEL.exists()}")
        if not MODEL.exists() or not (SERVER.exists() or CLI.exists()):
            log("model yoki whisper topilmadi — ORNATISH.bat ni qayta ishga tushiring")
        threading.Thread(target=self.tanuvchi.server_boshla, daemon=True).start()
        hk = keyboard.GlobalHotKeys({HOTKEY: self.tugma})
        hk.daemon = True
        hk.start()
        self.icon = pystray.Icon("RubaiSTT", self.rasm("#2e7d32"), "RubaiSTT — Ctrl+Alt+D bosib gapiring",
                                 self.menyu())
        self.icon.run()


if __name__ == "__main__":
    if "--sinov" in sys.argv:                          # konsoldan: wav → matn
        wav = Path(sys.argv[-1])
        t = Tanuvchi(); t.server_boshla()
        print("MATN:", t.tanib_ol(wav)); t.yop(); sys.exit(0)
    Ilova().ishga_tushir()
