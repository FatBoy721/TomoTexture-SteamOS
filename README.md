# TomoTexture for Steam Deck / Linux

Linux port of [TomoTexture](https://github.com/AlfonsoMallozzi/TomoTexture), published with permission from [@AlfonsoMallozzi](https://github.com/AlfonsoMallozzi).

Tested on Ubuntu and Steam Deck Desktop Mode.

## What it does

TomoTexture lets you replace custom canvas textures in Tomodachi Life saves, including:

- Foods
- Goods and pets
- Face paint

Version `v1.0.1` fixes the blank Goods/Pets item type menu on Steam Deck and adds a **Check Updates** button.

---

## Install

Download the latest [`TomoTexture-x86_64.AppImage`](../../releases/latest), then:

```bash
chmod +x TomoTexture-x86_64.AppImage
./TomoTexture-x86_64.AppImage
```

---

## Update

Use the **Check Updates** button in the app, or download the newest AppImage from [Releases](../../releases/latest).

---

## Run from source

```bash
sudo apt install python3 python3-tk python3-venv git   # Ubuntu/Debian
sudo pacman -S python tk                                # Arch/SteamOS

git clone https://github.com/FatBoy721/TomoTexture-SteamOS.git
cd TomoTexture-SteamOS
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

---

## Credits

- **[@AlfonsoMallozzi](https://github.com/AlfonsoMallozzi)** — original [TomoTexture](https://github.com/AlfonsoMallozzi/TomoTexture)

macOS port: [FatBoy721/TomoTexture-macOS](https://github.com/FatBoy721/TomoTexture-macOS)
