import asyncio
import ctypes
import io
import json
import logging
import logging.handlers
import socket
import subprocess
import sys
import time
from pathlib import Path

import mss
import uvicorn
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

# ── Logging (writes to file so errors are visible when run in background) ────
BASE_DIR = Path(__file__).parent
_log_file = BASE_DIR / "lan-remote.log"
_handler = logging.handlers.RotatingFileHandler(
    _log_file, maxBytes=512_000, backupCount=1, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[_handler, logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("lan-remote")

# ── DPI awareness (must be before pynput imports) ────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from pynput import keyboard as kb_lib
from pynput import mouse as mouse_lib

# ── Volume (Windows virtual key codes — no external library needed) ──────────
_VK_VOLUME_MUTE  = 0xAD
_VK_VOLUME_DOWN  = 0xAE
_VK_VOLUME_UP    = 0xAF
_KEYEVENTF_KEYUP = 0x0002

def _send_vk(vk: int):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)

# ── mDNS (zeroconf) ──────────────────────────────────────────────────────────
try:
    from zeroconf import ServiceInfo, Zeroconf

    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Controllers
# ─────────────────────────────────────────────────────────────────────────────

class MouseCtrl:
    def __init__(self):
        self._m = mouse_lib.Controller()

    def move(self, dx: int, dy: int):
        self._m.move(dx, dy)

    def click(self, button: str):
        btn = mouse_lib.Button.right if button == "right" else mouse_lib.Button.left
        self._m.click(btn, 1)

    def double_click(self):
        self._m.click(mouse_lib.Button.left, 2)

    def scroll(self, dx: int, dy: int):
        self._m.scroll(dx, dy)

    def move_to(self, x: int, y: int):
        self._m.position = (x, y)


class KeyboardCtrl:
    SPECIAL_KEYS = {
        "enter":     kb_lib.Key.enter,
        "backspace": kb_lib.Key.backspace,
        "escape":    kb_lib.Key.esc,
        "tab":       kb_lib.Key.tab,
        "space":     kb_lib.Key.space,
        "up":        kb_lib.Key.up,
        "down":      kb_lib.Key.down,
        "left":      kb_lib.Key.left,
        "right":     kb_lib.Key.right,
        "delete":    kb_lib.Key.delete,
        "home":      kb_lib.Key.home,
        "end":       kb_lib.Key.end,
    }
    MODIFIER_KEYS = {
        "ctrl":  kb_lib.Key.ctrl,
        "alt":   kb_lib.Key.alt,
        "shift": kb_lib.Key.shift,
        "win":   kb_lib.Key.cmd,
    }

    def __init__(self):
        self._k = kb_lib.Controller()

    def type_text(self, text: str):
        self._k.type(text)

    def special(self, key: str):
        k = self.SPECIAL_KEYS.get(key)
        if k:
            self._k.press(k)
            self._k.release(k)

    def combo(self, keys: list):
        modifiers = [self.MODIFIER_KEYS[k] for k in keys[:-1] if k in self.MODIFIER_KEYS]
        final = keys[-1]
        final_key = self.SPECIAL_KEYS.get(final, final)
        with self._k.pressed(*modifiers):
            self._k.press(final_key)
            self._k.release(final_key)


class VolumeCtrl:
    def up(self):   _send_vk(_VK_VOLUME_UP)
    def down(self): _send_vk(_VK_VOLUME_DOWN)
    def mute(self): _send_vk(_VK_VOLUME_MUTE)


def media_play_pause():
    k = kb_lib.Controller()
    k.press(kb_lib.Key.media_play_pause)
    k.release(kb_lib.Key.media_play_pause)


def media_next():
    k = kb_lib.Controller()
    k.press(kb_lib.Key.media_next)
    k.release(kb_lib.Key.media_next)


def media_prev():
    k = kb_lib.Controller()
    k.press(kb_lib.Key.media_previous)
    k.release(kb_lib.Key.media_previous)


def system_sleep():
    ctypes.windll.powrprof.SetSuspendState(0, 0, 0)


def system_shutdown():
    subprocess.run(["shutdown", "/a"], check=False)  # cancel any existing first
    subprocess.run(["shutdown", "/s", "/t", "10"], check=True)
    _shutdown_state["ends_at"] = time.time() + 10


def system_shutdown_scheduled(minutes: int):
    seconds = max(1, minutes * 60)
    subprocess.run(["shutdown", "/a"], check=False)  # cancel any existing first
    subprocess.run(["shutdown", "/s", "/t", str(seconds)], check=True)
    _shutdown_state["ends_at"] = time.time() + seconds


def system_shutdown_cancel():
    subprocess.run(["shutdown", "/a"], check=False)
    _shutdown_state["ends_at"] = None


# ── Shutdown state (tracks scheduled shutdowns so the UI can restore on reload) ─
_shutdown_state: dict = {"ends_at": None}  # ends_at = float epoch seconds or None


def capture_screenshot(quality: int = 60, max_width: int = 1280, monitor_idx: int = 1) -> bytes:
    with mss.mss() as sct:
        # monitors[0] is the virtual combined display; monitors[1..n] are individual screens
        idx = max(1, min(monitor_idx, len(sct.monitors) - 1))
        monitor = sct.monitors[idx]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI()

STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

mouse_ctrl = MouseCtrl()
kb_ctrl = KeyboardCtrl()
vol_ctrl = VolumeCtrl()


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/screenshot")
async def screenshot(quality: int = Query(60, ge=10, le=95),
                     monitor: int = Query(1, ge=1)):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, capture_screenshot, quality, 1280, monitor)
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/monitors")
async def api_monitors():
    with mss.mss() as sct:
        result = []
        for i, m in enumerate(sct.monitors):
            if i == 0:
                continue  # skip virtual combined monitor
            result.append({
                "index": i,
                "width": m["width"],
                "height": m["height"],
                "left": m["left"],
                "top": m["top"],
            })
        return {"monitors": result}


@app.get("/api/info")
async def api_info(monitor: int = Query(1, ge=1)):
    with mss.mss() as sct:
        idx = max(1, min(monitor, len(sct.monitors) - 1))
        m = sct.monitors[idx]
        return {"screen_width": m["width"], "screen_height": m["height"]}


@app.get("/api/shutdown-status")
async def api_shutdown_status():
    ends_at = _shutdown_state["ends_at"]
    if ends_at is None:
        return {"pending": False, "seconds_remaining": 0}
    remaining = ends_at - time.time()
    if remaining <= 0:
        _shutdown_state["ends_at"] = None
        return {"pending": False, "seconds_remaining": 0}
    return {"pending": True, "seconds_remaining": remaining}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps({"type": "connected", "version": "1.0"}))
    loop = asyncio.get_event_loop()

    def dispatch(data: dict):
        t = data.get("type", "")
        if t == "mouse_move":
            mouse_ctrl.move(int(data.get("dx", 0)), int(data.get("dy", 0)))
        elif t == "mouse_move_to":
            mouse_ctrl.move_to(int(data.get("x", 0)), int(data.get("y", 0)))
        elif t == "mouse_click":
            mouse_ctrl.click(data.get("button", "left"))
        elif t == "mouse_double_click":
            mouse_ctrl.double_click()
        elif t == "mouse_scroll":
            mouse_ctrl.scroll(int(data.get("dx", 0)), int(data.get("dy", 0)))
        elif t == "key_text":
            kb_ctrl.type_text(data.get("text", ""))
        elif t == "key_special":
            kb_ctrl.special(data.get("key", ""))
        elif t == "key_combo":
            kb_ctrl.combo(data.get("keys", []))
        elif t == "volume_up":
            vol_ctrl.up()
        elif t == "volume_down":
            vol_ctrl.down()
        elif t == "volume_mute":
            vol_ctrl.mute()
        elif t == "media_play_pause":
            media_play_pause()
        elif t == "media_next":
            media_next()
        elif t == "media_prev":
            media_prev()
        elif t == "system_sleep":
            system_sleep()
        elif t == "system_shutdown":
            system_shutdown()
        elif t == "system_shutdown_scheduled":
            system_shutdown_scheduled(int(data.get("minutes", 30)))
        elif t == "system_shutdown_cancel":
            system_shutdown_cancel()

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            await loop.run_in_executor(None, dispatch, data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# mDNS registration
# ─────────────────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def register_mdns(ip: str, port: int) -> object | None:
    if not ZEROCONF_AVAILABLE:
        return None
    try:
        zc = Zeroconf()
        info = ServiceInfo(
            "_http._tcp.local.",
            "lan-remote._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={"path": "/"},
            server="lan-remote.local.",
        )
        zc.register_service(info)
        return zc
    except Exception as e:
        log.warning("mDNS registration failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PORT = 8000
    ip = get_local_ip()
    zc = register_mdns(ip, PORT)

    msg_lines = [
        "",
        "=" * 52,
        "  LAN Remote Control",
        "=" * 52,
        "  Open on your iPhone (Safari):",
        "",
    ]
    if zc:
        msg_lines.append(f"    http://lan-remote.local:{PORT}    <- bookmark this")
    msg_lines.append(f"    http://{ip}:{PORT}    <- fallback (IP may change)")
    msg_lines += ["", "  Press Ctrl+C to stop", "=" * 52, ""]

    for line in msg_lines:
        log.info(line)

    try:
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning",
                    ws_ping_interval=None)
    finally:
        if zc:
            zc.unregister_all_services()
            zc.close()
