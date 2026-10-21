System Widget 1.2.10
=================

A small always-on-top desktop widget for Windows that shows:

    CPU usage        RAM usage         GPU usage
    GPU temperature  Internet speed    System power (estimated)

Nothing to install - Python and everything else is built into the .exe.

HOW TO RUN
----------
1. Unzip this package anywhere you like (for example C:\Users\You\SystemWidget).
2. Double-click SystemWidget.exe.
   The widget appears in the bottom-right corner, above the taskbar.

FIRST RUN
---------
Windows SmartScreen may say "Windows protected your PC" because the file is
not digitally signed. Click "More info" -> "Run anyway".

SHORTCUTS
---------
Ctrl+Alt+W    hide / show the widget
Ctrl+Alt+T    always on top on / off
Ctrl+Alt+L    lock / unlock the mouse (drag and resize)
Ctrl+wheel    resize the widget (over the widget itself)

If the widget is hidden, double-click SystemWidget.exe again to bring it back.

RIGHT-CLICK MENU
----------------
The first entry is a quick toggle: Lock widget makes the widget ignore the
mouse (no dragging, no Ctrl+wheel) until you untick it. A padlock shows in the
top-right corner while it is locked; right-click keeps working.

The next five entries are sections: click one to unfold its choices in place,
click it again to fold it away. The current value stays visible on the right.

Show              tick the rows you want (CPU, RAM, GPU, Temperature,
                  Internet, Power). The widget resizes itself to fit.
Theme             Card (vertical) / Horizontal bar / Minimal text /
                  Gauge rings - four designs, saved automatically.
Size              slider from 50% to 150% - makes the whole widget bigger or
                  smaller. Ctrl+wheel does the same in 5% steps.
Opacity           slider from 20% to 100%
Refresh rate      0.5 s to 3 s
Always on top     keep it above other windows
Stay above the taskbar  let the widget sit over the taskbar and stay there
Hide in fullscreen games  hide it while a fullscreen app has focus (off)
Scale with resolution  shrink proportionally on lower-resolution games
Start with Windows  launch it automatically when you log in
Hide              hide the widget (Ctrl+Alt+W brings it back)
Reset position    move it back to the bottom-right corner
About             developer, email, version, created date and bio
Exit              close it

Changes apply immediately and the menu stays open, so you can try a few
settings in a row. Esc or a click outside closes it.

Drag anywhere on the widget to move it. Position, chosen rows, theme and all
other settings are remembered between sessions.

SITTING OVER THE TASKBAR
------------------------
"Stay above the taskbar" is on by default, so you can drag the widget right
down onto the taskbar and it stays visible there. Windows raises the taskbar
when you click it; the widget notices and lifts itself back on top, without
taking focus. Turn the option off to keep the widget inside the desktop area.

FULLSCREEN GAMES
----------------
The widget stays on top of borderless / windowed games, including ones that
mark themselves always-on-top: it checks the z-order every second and lifts
itself back when another window covers it.

Plain "Fullscreen" (exclusive) mode is the exception - the game takes over the
display and no normal window can draw over it. The widget detects that and
hides itself until the game exits, instead of fighting for the z-order (which
is what made some games drop out of fullscreen and minimize).

To see the widget while playing, switch the game to Borderless / Windowed
fullscreen / Fullscreen windowed. In Counter-Strike 2: Settings > Video >
Display Mode > Fullscreen Windowed. Older games that only offer Fullscreen or
Windowed (Half-Life, Counter-Strike 1.6...) work the same way - pick Windowed,
or add -windowed to the Steam launch options.

Every game can use its own resolution. The widget keeps its gap to the
bottom-right corner, so it lands in the same place at any resolution and
returns to its old spot when the desktop resolution comes back.

With "Scale with resolution" on (default) the size you picked belongs to the
display you picked it on: at 1280x720 the widget shrinks to two thirds, so it
covers the same share of the screen instead of looking half again as big. It
never grows past your size, never goes below 40 %, and your saved size returns
with the desktop.

"Hide in fullscreen games" is off by default. The widget never fights a game
for the z-order, so exclusive games do not minimize - they just draw over it.
Borderless games, and games using Windows' Fullscreen Optimizations, keep the
widget visible on top, which is the usual way to see it while playing.

Check that option if you would rather it disappear while any fullscreen app
has focus. Windows reports the same state for borderless and exclusive games,
so the widget cannot tell them apart.

THEMES
------
Card (vertical)   classic panel, one row per metric with a wide bar
Horizontal bar    slim taskbar-style strip, all metrics in one line
Minimal text      plain key/value list, no bars, smallest footprint
Gauge rings       circular gauge per metric with details underneath

ABOUT THE POWER FIGURE
----------------------
GPU watts are measured directly from the NVIDIA driver (accurate).
CPU watts are estimated from the CPU load and a 65 W TDP, and a fixed 18 W is
added for the motherboard, RAM, drives and fans. That is why the total is
prefixed with "~". Expect it to be within roughly 10-20% of the real draw.

ABOUT THE TEMPERATURE
---------------------
Temp is the GPU die temperature, read live from the NVIDIA driver (the same
number nvidia-smi shows) and turns red from 80 C. CPU package temperature needs
a signed kernel driver (Ryzen Master, LibreHardwareMonitor, HWiNFO...), so the
widget shows the GPU sensor instead - the one that matters in games.

The GPU, Temp and Power rows need an NVIDIA graphics card. On other PCs those
rows show "not detected" and everything else keeps working.

REQUIREMENTS
------------
Windows 10 or 11, 64-bit.

Settings are saved in:  %APPDATA%\SystemWidget\settings.json
