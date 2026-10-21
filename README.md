# System Widget

A tiny, always-on-top desktop widget for Windows that shows **CPU**, **RAM**,
**GPU**, **temperature**, **network speed** and **estimated system power** at a
glance.

```
┌──────────────────────────────────┐
│ PERFORMANCE        RTX 4070 · 78°C│
│ ● CPU  3.8 GHz              11%  │
│ ▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│ ● RAM  31.9 / 64 GB         51%  │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░  │
│ ● GPU  6.2/8 GB VRAM       100%  │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │
│ ● TEMP  GPU                 78°C │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  │
│ ● NET  ↑ 2.17 KB/s     ↓ 14.5 KB/s│
│ ▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│ ● POWER  GPU 205 W      ≈ 267 W  │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │
└──────────────────────────────────┘
```

## Run it

**Installer (recommended)** — `SystemWidget-1.2.9-win64.msi` from the
[Releases page](https://github.com/mfarazaly/system-widget/releases):

1. Double-click the MSI.
2. Install for the current user (no admin prompt), tick **Launch System Widget**
   on the last page if you want it to start right away.

It installs into `%LOCALAPPDATA%\Programs\SystemWidget` and adds a Start Menu
and a desktop shortcut. Uninstall via **Settings → Apps → System Widget**; the
saved settings in `%APPDATA%` are kept so a re-install picks up where you left.

**Standalone (no Python needed)** — for sharing with anyone on Windows 10/11 (64-bit):

1. Download `SystemWidget-1.2.9-win64.zip` from the same Releases page.
2. Unzip it anywhere and double-click **`SystemWidget.exe`**

Python, psutil and tkinter are bundled inside the exe (~11 MB). On first run
Windows SmartScreen may warn that the publisher is unknown: **More info → Run
anyway**. That is because the exe is not code-signed.

**From source:**

Double-click **`SystemWidget.pyw`** — it runs silently, with no console window.

To launch it from a shortcut / command line instead:

```
pythonw.exe SystemWidget.pyw
```

## Choosing what to show

Right-click → **Show**, unfold the section and tick the rows you want:

| Row          | Shows                                                        |
| ------------ | ------------------------------------------------------------ |
| **CPU**      | Total CPU load + current clock                               |
| **RAM**      | Used / total memory                                          |
| **GPU**      | Utilization, VRAM used / total (+ name & temp in the header) |
| **Temp**     | GPU die temperature, turns red from 80 °C                    |
| **Internet** | Download (`↓`) and upload (`↑`) speed                        |
| **Power**    | Estimated system draw in watts (+ GPU share)                 |

The card resizes itself to fit the selected rows, so you can run it as a single
GPU read-out or as the full six-row panel. At least one row always stays on.
Every row works in every theme.

## Themes

Right-click → **Theme**, unfold the section and pick a layout. The choice is saved.

| Theme              | Looks like                                                        |
| ------------------ | ----------------------------------------------------------------- |
| **Card (vertical)**| The classic panel: one row per metric with a wide bar (default)    |
| **Horizontal bar** | A slim taskbar-style strip: label, value and a short bar per metric, all in one line |
| **Minimal text**   | A plain key/value list — no bars, no header, smallest footprint    |
| **Gauge rings**    | One circular gauge per metric with the value inside and details underneath |

Each theme keeps its own colours, drag-to-move and right-click menu. The window
re-sizes and stays on screen (above the taskbar) when you switch.

## Size

Right-click → **Size**, unfold the section and drag the slider anywhere between
50 % and 150 % — it snaps to 5 % steps and the widget resizes while you drag.
For a quick change without opening the menu, hold `Ctrl` and scroll the mouse
wheel over the widget: same 5 % steps, same range.

Everything inside the widget scales together: text, bars, header and icons. The
right-click menu and the About card keep their normal size, so they stay easy to
read and hit whatever size the widget is. A widget docked against a screen edge
stays on that edge while it grows or shrinks, so it never drifts away from the
taskbar.

## Locking the widget

Right-click → **Lock widget** (or `Ctrl+Alt+L`) makes the widget ignore the
mouse: no dragging, no `Ctrl`+wheel resizing. A stray click while you are working
or a game that grabs the cursor can no longer move or resize it.

A small padlock sits in the top-right corner while it is locked. Right-click
always keeps working and opens the menu with **Lock widget** ticked — untick it,
or press `Ctrl+Alt+L` again, to unlock. The rest of the menu still works while
locked; only the mouse gestures on the widget itself are ignored.

## Shortcuts

| Shortcut                  | Action                          |
| ------------------------- | ------------------------------- |
| `Ctrl+Alt+W`              | Hide / show the widget          |
| `Ctrl+Alt+T`              | Toggle always-on-top            |
| `Ctrl+Alt+L`              | Lock / unlock the mouse         |
| `Ctrl` + mouse wheel      | Resize the widget               |

Double-clicking `SystemWidget.pyw` again while the widget is hidden brings it
back, so it can never get "lost". Only one copy runs at a time.

## Right-click menu

The menu opens where you right-click it and is drawn by the widget itself, so it
matches the dark look of every theme. The first five entries are **sections**:
click one to unfold its choices in place, click it again to fold it away (the
current value stays visible on the right, e.g. `Theme  Horizontal bar`).

- **Lock widget** – ignores the mouse (drag and wheel) until you unlock it
  (`Ctrl+Alt+L`); right-click still opens this menu
- **Show** – tick the rows (see above); the header shows how many are on
- **Theme** – Card / Horizontal bar / Minimal text / Gauge rings
- **Size** – slider from 50 % to 150 % (or `Ctrl` + wheel for quick steps)
- **Opacity** – slider from 20 % to 100 %
- **Refresh rate** – 0.5 s to 3 s
- **Always on top** – checkmark shows the current state (`Ctrl+Alt+T`)
- **Stay above the taskbar** – lets the widget sit over the taskbar and keeps
  it there (on by default). Turn it off to keep the widget inside the desktop
  area only.
- **Hide in fullscreen games** - hides the widget while a fullscreen app has
  focus (off by default; see below)
- **Scale with resolution** - when a game runs at a lower resolution than the
  desktop, the widget shrinks by the same ratio so it covers the same share of
  the screen (on by default; see below)
- **Start with Windows** – adds/removes a registry entry in
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- **Hide** – `Ctrl+Alt+W`
- **Reset position** – back to the bottom-right corner (above the taskbar)
- **About System Widget** – developer, version, created date and a short bio
- **Exit**

Ticked rows, themes, size, opacity and refresh rate apply immediately and the
menu stays open so you can try a few settings in a row. Press `Esc` or click
anywhere outside the menu to close it.

Drag anywhere on the widget to move it. Position, visible rows, theme, size,
opacity, topmost state, taskbar overlap, the fullscreen option and refresh rate
are remembered between sessions.

## Sitting over the taskbar

With **Stay above the taskbar** enabled you can drag the widget all the way down
onto the taskbar and it stays visible there. The taskbar is itself an
always-on-top window, so Windows raises it when you click it; the widget checks
the z-order about once a second (twice as often while it overlaps the taskbar)
and lifts itself back above the taskbar when needed. No flicker or focus
stealing - the checks only reorder windows when the taskbar actually ended up on
top.

Turn the option off if you prefer the widget to stay inside the normal desktop
area (the taskbar then always wins).

## Over fullscreen games

The widget is an ordinary always-on-top window, so it stays visible over
desktop apps, borderless / windowed games and anything else on the desktop -
including games and players that mark themselves always-on-top: the widget
notices when another window covers it and lifts itself back to the front.

**Exclusive fullscreen** (the plain "Fullscreen" option in most games) is the
one exception. There the game takes over the display adapter and draws straight
to the screen, so no normal window - including this widget - can appear over it.

- While a game owns the screen the widget leaves the z-order alone instead of
  fighting for it. That is what stops games from dropping out of fullscreen or
  minimizing when the widget overlaps them, and it is why an exclusive game can
  never be minimized by the widget.
- To see the widget **while playing**, switch the game to **Borderless**,
  **Windowed fullscreen** or **Fullscreen windowed** - every game has one of
  those in its display settings. In Counter-Strike 2 that is
  **Settings → Video → Display Mode → Fullscreen Windowed**.
- Older games that only offer "Fullscreen" or "Windowed" work the same way:
  pick **Windowed**. For Half-Life: **Options → Video → Display Mode →
  Windowed**, or add `-windowed` (optionally `-w 1600 -h 900`) to the game's
  launch options in Steam. A fullscreen-sized window looks the same and the
  widget can stay on top of it.
- Every game can use its own resolution - the widget handles all of them.
  It keeps its gap to the bottom-right corner, so it lands in the same place
  at 1920×1080, 1280×720 or anything in between, and returns to exactly where
  it was when the game exits.
- With **Scale with resolution** on (the default), the size you picked belongs
  to the display you picked it on. At 1280×720 it shrinks to two thirds, so a
  widget that is 30 % of a 1920-wide desktop is still 30 % of a 1280-wide game
  instead of looking half again as big. It never grows past the size you chose
  on larger displays, and never goes below 40 % - below that the text stops
  being legible. Your saved size is untouched: the desktop gets it back the
  moment the game exits. If even the adapted size would not fit, it keeps
  shrinking until it is fully on screen.

**Hide in fullscreen games** is off by default. The widget never fights a game
for the top of the z-order, so exclusive games no longer minimize - they simply
draw over it, because Windows hands them the display outright. Borderless
games, and games using Windows' *Fullscreen Optimizations*, are composited by
the desktop, so the widget stays visible on top of them while you play.

Turn the option on if you would rather it disappear whenever a fullscreen app
has focus. Note that Windows reports the same "a fullscreen app is running"
state for borderless and exclusive windows, so the widget cannot tell them
apart - hiding would also make it vanish over games it could have drawn on.

Menus, tooltips, the Start menu and taskbar flyouts are deliberately left above
the widget, so the tray menu still opens over it instead of behind it.

## About the power figure

There is no general Windows API for "wall power", and reading CPU package power
needs a kernel driver (admin rights + extra software). The widget therefore
combines:

- **GPU power** – measured directly from the NVIDIA driver (NVML), accurate.
- **CPU power** – estimated from load and the `CPU_TDP_W` constant (65 W for the
  Ryzen 7 7700 here).
- **Platform** – a fixed 18 W for motherboard, RAM, drives and fans.

That is why the row is prefixed with `≈`. The GPU part (shown in the row detail)
is the real measurement; expect the total to be within roughly 10–20 % of the
actual draw.

## About the temperature figure

**Temp** shows the GPU die temperature straight from the NVIDIA driver — the same
number `nvidia-smi` reports — refreshed with the rest of the rows. It turns red
from 80 °C.

CPU package temperature is not exposed through any normal Windows API: AMD and
Intel only report it through a signed kernel driver (Ryzen Master,
LibreHardwareMonitor, HWiNFO and friends), which is more than a 12 MB widget
should install just for one number. So the row shows the GPU sensor — the one
that actually matters while gaming. Without an NVIDIA card the row shows
"not detected" like the GPU row.

## Requirements

- Windows 10 or 11
- Python 3.9+ with **psutil** (`pip install psutil`) — already installed here
- GPU stats need an NVIDIA card. They are read through the NVML driver API
  (in-process, no extra process), with `nvidia-smi` as a fallback. On other GPUs
  the GPU row shows "not detected"; everything else still works.

The widget itself uses about 0.5 % of one CPU core.

## Customising

Edit the block at the top of `SystemWidget.pyw`:

```python
HOTKEY_MODIFIERS = ("ctrl", "alt")   # ctrl / alt / shift / win
HOTKEY_KEY = "w"                     # hide / show
TOPMOST_KEY = "t"                    # toggle always-on-top

BASE_W = 262                         # widget width
ROW_H = 44                           # height of one row
CPU_TDP_W = 65                       # your CPU's TDP, for the power estimate
PLATFORM_W = 18                      # motherboard / RAM / drives / fans

COL_BG = "#0c0e13"                   # background
ROWS = (...)                         # add, reorder or recolour rows
```

Saved settings live in `%APPDATA%\SystemWidget\settings.json`:

```json
{
  "x": 1634, "y": 734,
  "opacity": 1.0,
  "topmost": true,
  "above_taskbar": true,
  "locked": false,
  "hide_in_games": false,
  "refresh": 1.0,
  "rows": ["cpu", "ram", "gpu", "temp", "net", "power"],
  "theme": "card",
  "ui_scale": 1.0,
  "adapt_scale": true,
  "scale_ref_w": 1920,
  "scale_ref_h": 1080,
  "corner_dx": 24,
  "corner_dy": 24,
  "cpu_tdp": 65,
  "schema": 2
}
```

## Files

| File                          | Purpose                                                |
| ----------------------------- | ------------------------------------------------------ |
| `SystemWidget.pyw`            | The widget (single file, no dependencies beyond psutil) |
| `dist\SystemWidget-1.2.9-win64.msi` | **Installer** (per-user, Start Menu + desktop shortcut) |
| `dist\SystemWidget-1.2.9-win64.zip` | **Portable package** (exe + README.txt)             |
| `installer\SystemWidget.wxs`  | WiX source for the MSI                                 |
| `installer\license.rtf`       | License text shown by the installer                    |
| `installer\make_bitmaps.py`   | Regenerates the installer banner / panel art           |
| `installer\banner.bmp`, `dialog.bmp` | Installer artwork                               |
| `build.ps1`                   | Rebuilds the exe, the zip and (if WiX is present) the MSI |
| `assets\`                     | Icon generator, icon, Windows version resource         |
| `packaging\README.txt`        | The readme that ships inside the zip                   |
| `requirements.txt`            | Python dependency list                                 |
| `README.md`                   | This file                                              |

## Build the standalone exe

After editing `SystemWidget.pyw`:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This produces `dist\SystemWidget.exe` and `dist\SystemWidget-1.2.9-win64.zip`
(PyInstaller one-file build, icon + version info embedded). Delete the `build\`
folder afterwards if you want to save space — it is only build scratch data.

### Building the MSI

The installer is built with [WiX 5](https://wixtoolset.org) (one-time setup):

```powershell
dotnet tool install --global wix --version 5.0.2
wix extension add -g WixToolset.UI.wixext/5.0.2
```

`build.ps1` then also produces `dist\SystemWidget-1.2.9-win64.msi`. To build it
alone, run from the repo root:

```powershell
wix build installer\SystemWidget.wxs -ext WixToolset.UI.wixext -o dist\SystemWidget-1.2.9-win64.msi
```
