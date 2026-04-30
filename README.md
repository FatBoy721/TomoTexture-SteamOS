# TomoTexture for Steam Deck / Linux

Linux port of [TomoTexture](https://github.com/AlfonsoMallozzi/TomoTexture), published with permission from [@AlfonsoMallozzi](https://github.com/AlfonsoMallozzi).

> Ubuntu tested and working. Steam Deck needs further testing — open an issue if you try it!

---

## Install

Download the latest [`TomoTexture-x86_64.AppImage`](../../releases/latest), then:

```bash
chmod +x TomoTexture-x86_64.AppImage
./TomoTexture-x86_64.AppImage
```

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
