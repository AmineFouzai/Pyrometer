PYROMETER LITE

Always-on-top temperature overlay for Windows. It reads CPU, GPU, motherboard,
disk, and memory temperatures and draws them in a small panel that can sit on
any monitor. Compact mode shows one reading per device. Expanded mode lists
every sensor: scroll with the wheel when the list is taller than the screen,
and click a device header to fold or open that device. Right-click for opacity
and themes — twelve presets, or a custom palette saved on this PC.

The widget is built to stay light. It polls hardware every few seconds, pauses
polling while hidden, redraws only when a reading changes, runs at below-normal
priority, and hands unused memory back to Windows.

Install:
  Double-click Install.bat, then open Pyrometer Lite from Start.

Portable:
  Run dist\PyrometerLite.exe.

Position:
  Drag anywhere on the widget. It can be placed on any monitor, including
  monitors at negative coordinates (left of / above the primary screen).
  The spot is remembered in widget_config.json.

If sensors fail to load, the reason is written to pyrometer-error.log
next to the exe.

Hotkeys:
  Ctrl+Alt+T  show/hide
  Ctrl+Alt+E  expand/collapse
  Ctrl+Alt+L  click-through
  Ctrl+Alt+Q  quit

Expanded list:
  Mouse wheel     scroll the sensor list
  Drag the bar    same, on the right edge when the list overflows
  Click a header  fold or open that device (the count shows while folded)
  Double-click    expand or collapse the whole widget
                  (double-click the title if you are on a header)

Themes:
  Right-click → Themes. The dot marks the one in use.
  Presets: Default, Nord, Dracula, Catppuccin, Rose Pine, Gruvbox,
  Solarized, Tokyo Night, OLED, Amber, Matrix, Light.
  New custom theme… picks colors and stores them in widget_config.json.
  Edit and Delete appear while a custom theme is selected.
  #ff00ff is reserved so the rounded corners stay transparent.

Low-resource changes:
  - redraws only when sensor data changes
  - 3-second hardware polling
  - hardware polling completely pauses while hidden
  - no history/sparkline buffers
  - below-normal Windows process priority
  - reclaims resident memory when hidden and every ~30s while visible

Measured memory (Task Manager "Memory" column):
  visible  ~17-27 MB
  hidden   ~6 MB
LibreHardwareMonitor's hardware scan reserves ~120 MB of pagefile-backed
commit that is not resident in RAM.
