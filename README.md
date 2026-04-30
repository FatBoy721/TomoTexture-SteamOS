# TomoTexture for Steam Deck / SteamOS / Linux

> ⚠️ **Work in progress.** Untested on actual hardware yet. AppImage builds via CI, but real-world Steam Deck validation is pending.

A SteamOS / Linux port of [TomoTexture](https://github.com/AlfonsoMallozzi/TomoTexture), the save-canvas editor for **Tomodachi Life**. Edit the textures players paint inside the game by replacing the canvas images in your Ryujinx save folder.

Maintained with permission from [@AlfonsoMallozzi](https://github.com/AlfonsoMallozzi). See [upstream issue #31](https://github.com/AlfonsoMallozzi/TomoTexture/issues/31).

---

## Install on Steam Deck

1. Switch to **Desktop Mode** (Steam button → Power → Switch to Desktop).
2. Download the latest [`TomoTexture-x86_64.AppImage`](../../releases/latest).
3. Right-click the file → **Properties** → **Permissions** → tick **Is executable**, OR open Konsole and run:
   ```bash
   chmod +x ~/Downloads/TomoTexture-x86_64.AppImage
   ```
4. Double-click the AppImage to launch.

### Pinning to the taskbar / Steam library

- **Taskbar:** right-click the running app icon → **Pin to Task Manager**.
- **Steam library** (run from Gaming Mode): in Steam (Desktop Mode), **Add a Non-Steam Game** → browse to the AppImage. Then it shows up in your library and works in Gaming Mode too.

---

## Install on regular Linux

Same as above, just download the AppImage, `chmod +x`, run.

Tested on:
- _(none yet — please open an issue if you've tried it)_

Should work on anything with FUSE 2 (Ubuntu, Fedora, Arch, SteamOS, Bazzite, etc.).

---

## Run from source

Requires Python 3.10+ with Tkinter.

```bash
# Debian / Ubuntu
sudo apt install python3 python3-tk python3-venv

# Arch / SteamOS / Manjaro
sudo pacman -S python tk

# Fedora
sudo dnf install python3 python3-tkinter
```

Then:

```bash
git clone https://github.com/FatBoy721/TomoTexture-SteamOS.git
cd TomoTexture-SteamOS

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

---

## Build the AppImage yourself

Must be on Linux (or a Linux VM / CI runner — won't work on macOS).

```bash
./build-linux.sh
```

Output: `dist/TomoTexture-x86_64.AppImage`

The build pipeline also runs in [GitHub Actions](.github/workflows/build-appimage.yml) on any pushed `v*` tag — that's what produces the official release AppImages.

---

## Where Ryujinx puts saves

The app auto-detects the most common locations:

| Install method | Path |
| --- | --- |
| **Flatpak (Steam Deck default)** | `~/.var/app/org.ryujinx.Ryujinx/config/Ryujinx/bis/user/save/` |
| **Native install / AppImage** | `~/.config/Ryujinx/bis/user/save/` |

If your save lives elsewhere, hit **Browse** in the app and point it manually.

---

## Credits

- **[@AlfonsoMallozzi](https://github.com/AlfonsoMallozzi)** — original [TomoTexture](https://github.com/AlfonsoMallozzi/TomoTexture) tool and the public permission that made this port possible.

The macOS counterpart lives at [FatBoy721/TomoTexture-macOS](https://github.com/FatBoy721/TomoTexture-macOS).

---

## Disclaimer

**Always back up your save folder before editing.** TomoTexture creates `.bak` files automatically when you replace a canvas, but a clean external backup costs nothing.

The official Windows build lives on the [upstream repo](https://github.com/AlfonsoMallozzi/TomoTexture).
