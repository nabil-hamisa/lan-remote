# LAN Remote

Control your Windows PC from your iPhone over Wi-Fi — no app store, no Mac needed.

## Requirements

- Python 3.10 or newer
- PC and iPhone on the same Wi-Fi network

## Install & auto-start on boot

Double-click **`install.bat`** (right-click → Run as administrator for best results).

It will:
1. Install all Python dependencies
2. Register a Task Scheduler task so the server **starts silently every time you log into Windows**
3. Offer to start it right now without rebooting

The server runs in the background with no visible window. Connection info is written to **`lan-remote.log`** in the same folder.

Open **`http://lan-remote.local:8000`** in **Safari** on your iPhone.

> **IP fallback:** if `.local` doesn't work, check `lan-remote.log` for the numeric IP.

## Uninstall

Double-click **`uninstall.bat`** to stop the server and remove the startup task.

## Manual start (no auto-start)

```bash
pip install -r requirements.txt
python server.py
```

## Controls

| Section | What it does |
|---------|-------------|
| **Trackpad** | Drag = move mouse · Tap = left click · Long press = right click · 2 fingers = scroll |
| **Left / Right / Double Click** | Explicit click buttons |
| **⏮ ⏯ ⏭** | Previous / Play-Pause / Next (works with Spotify, VLC, browsers, etc.) |
| **🔇 🔉 🔊** | Mute / Volume Down / Volume Up |
| **Text input** | Type text and tap ↵ to send it to the PC |
| **Special keys** | Esc, Tab, arrow keys, Home, End, Delete, Backspace |
| **Sleep** | Puts PC to sleep (with confirmation) |
| **Shutdown** | Shuts down PC after 10 seconds — run `shutdown /a` on PC to cancel |

## Add to iPhone Home Screen

In Safari: tap the **Share** button → **Add to Home Screen** → gives you a full-screen app icon, no address bar.

## Windows Firewall

If your iPhone can't connect, Python needs to be allowed through the firewall:

**Option A — GUI:**
1. Windows Security → Firewall & network protection → Allow an app through Firewall
2. Find **Python** → check both **Private** and **Public**

**Option B — Run once in an admin terminal:**
```batch
netsh advfirewall firewall add rule name="LAN Remote" dir=in action=allow protocol=TCP localport=8000
```

## Stopping the server

Press `Ctrl+C` in the terminal.
