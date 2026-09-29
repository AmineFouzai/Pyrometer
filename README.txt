PYROMETER LITE

Always-on-top temperature overlay for Windows. It reads CPU, GPU, motherboard,
disk, and memory temperatures and available CPU/GPU/board power sensors in a
small panel that can sit on any monitor. Compact mode shows one temperature per
device with a bar. Expanded mode lists every sensor with dial gauges: scroll
with the wheel, resize from the lower-right corner, and click a device header
to fold or open it. Right-click for power settings, opacity, and themes —
twelve presets, or a custom palette saved on this PC.

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

Compact view:
  One temperature bar per device, plus a PWR bar for the estimated
  CPU + GPU draw against the PSU rating.

Expanded grid:
  Sensors are cards in a grid. Wider panel, more columns.
  Mouse wheel     scroll the grid
  Drag the bar    same, on the right edge when the grid overflows
  Drag the corner cyan lines, inside the panel, to resize
  Ctrl + wheel    make the text (and gauges) bigger or smaller
  Click a header  fold or open that device (the count shows while folded)
  LOCKED          click-through is on; Ctrl+Alt+L turns it off so the
                  panel can be dragged and resized
  Double-click    expand or collapse the whole widget
                  (double-click the title if you are on a header)

Text size:
  Right-click → Text size, from 90% to 200%, or Ctrl + mouse wheel over the
  widget. Rows, gauges, and the panel width grow with the text so nothing
  overlaps. Long sensor names are shortened with "…" instead of running into
  the reading. The choice is saved in widget_config.json.

Themes:
  Right-click → Themes. The dot marks the one in use.
  Presets: Default, Nord, Dracula, Catppuccin, Rose Pine, Gruvbox,
  Solarized, Tokyo Night, OLED, Amber, Matrix, Light.
  New custom theme… picks colors and stores them in widget_config.json.
  Edit and Delete appear while a custom theme is selected.
  #ff00ff is reserved so the rounded corners stay transparent.

Power:
  Right-click → Power → Set PSU capacity… and enter the wattage printed on
  the PSU label. Normal desktop PSUs do not expose their rated wattage to
  software, so Pyrometer cannot detect this value automatically.

  Expanded mode shows every power sensor LibreHardwareMonitor exposes. The
  summary estimates component draw from one CPU package reading plus one GPU
  board reading. Below 70% of the configured PSU rating is labelled NORMAL,
  70–85% ELEVATED, and above 85% HIGH.

  This is not total wall power and is not a PSU safety guarantee. It may omit
  the motherboard, disks, fans, conversion losses, and unsupported hardware.
  A plug-in wall power meter is required for accurate whole-system draw.

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
