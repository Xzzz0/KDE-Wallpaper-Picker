# Wallpaper Picker

A lightweight wallpaper picker daemon for **KDE Plasma** (Wayland & X11), built with Python and PyQt6.

Press a shortcut — a frosted-glass CoverFlow window appears in the center of your screen. Browse your wallpapers with arrow keys or scroll wheel, apply with Enter or a click.

---

## Features

- **Frosted-glass background** — blurs your current wallpaper behind the window
- **CoverFlow carousel** with smooth 200ms animations
- **Category support** — organizes wallpapers by subfolder, switch with ↑/↓
- **Daemon mode** — starts once, opens/closes instantly via shortcut
- **Thumbnail cache** at `/tmp/wp_thumbs/` — instant display after first launch
- **Auto-reload** — new wallpapers in your folder are detected automatically
- **All monitors** are set simultaneously
- **State persistence** — remembers your last used category

---

## Requirements

- KDE Plasma (Wayland or X11)
- Python 3.10+
- PyQt6

```bash
sudo pacman -S python-pyqt6
```

`plasma-apply-wallpaperimage` is included with KDE Plasma.

---

## Installation

```bash
git clone https://github.com/YOUR-USERNAME/wallpaper-picker.git
cd wallpaper-picker
bash install.sh
```

The script checks dependencies and sets up **autostart** (daemon launches automatically on KDE login).

---

## Shortcut Setup

One manual step required:

1. **System Settings** → **Shortcuts** → **Custom Shortcuts**
2. Edit → New → **Global Shortcut → Command/URL**
3. Settings:
   - **Name:** `Wallpaper Picker`
   - **Trigger:** `Shift+Alt+W` (or whatever you prefer)
   - **Action:** `python "/PATH/TO/wallpaper_picker.py"`

---

## Start Without Restarting

```bash
python "/PATH/TO/wallpaper_picker.py" &
```

The shortcut works immediately after.

---

## Usage

| Key / Action | Function |
|---|---|
| `←` / `→` | Previous / next wallpaper |
| Scroll wheel | Navigate |
| `↑` / `↓` | Previous / next category |
| `Enter` | Apply wallpaper + close |
| Click center image | Apply wallpaper + close |
| Click side image | Navigate to that image |
| `Escape` | Close without change |

---

## Folder Structure

Wallpapers are organized by subfolders inside your wallpaper directory:

```
~/wallpapers/
├── nature/
│   ├── forest.jpg
│   └── mountains.png
├── abstract/
│   └── waves.webp
└── loose_wallpaper.jpg      ← goes into "Unsorted"
```

If no subfolders exist, all images are shown in a single "All" category.

---

## Configuration

Edit the top of `wallpaper_picker.py`:

```python
WALLPAPER_DIR = Path("/home/YOUR_USER/wallpapers")  # your wallpaper folder
THUMB_CACHE_DIR = Path("/tmp/wp_thumbs")             # thumbnail cache
BASE_W, BASE_H = 350, 220                            # center image size
SPREAD = 230                                         # spacing between images
BLUR_RADIUS = 30                                     # frosted glass blur strength
BLUR_OVERLAY_ALPHA = 100                             # dark overlay opacity (0–255)
```

---

## Supported Formats

`.jpg` `.jpeg` `.png` `.webp` `.bmp`

---

## Project Structure

```
wallpaper-picker/
├── wallpaper_picker.py   # complete daemon + UI (single file)
└── install.sh            # installer + autostart setup
```

---
## Troubleshooting

¯\\_(ツ)_/¯

## License

MIT
