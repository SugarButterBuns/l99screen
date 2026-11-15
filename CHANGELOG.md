# Changelog

All notable changes to L99 Screen. Each version below is a GitHub release with an AppImage.

## [1.0-3] - 2026-11-15

### Added
- The window can be resized to any size, as long as the controls still fit. The preview grows or
  shrinks with the window while keeping the screen's shape. Its caption shows the zoom level when
  the preview isn't 1:1; the upload is always 320 × 480.
- A file-type badge (JPG, PNG, GIF, APNG, WEBP, BMP) next to the file name. It's based on the
  file's actual contents, not just its extension.
- The original image size and file size, e.g. "1200 × 1800 · 94 KB", plus what will be sent,
  e.g. "→ Animation · 12 frames · 1.2 s".

### Fixed
- Long file names ran under the Browse button and hid the extension. They're now shortened in the
  middle so the extension always shows, and they have a full-width row of their own.
- Loading a file no longer shifts the layout.

## [1.0-2] - 2026-11-15

### Added
- **Windows version:** `L99_Screen-1.0-2-windows.exe`, a single file with nothing to install and no
  need for AULA's software. It's the same app as on Linux, with drag-and-drop and the app icon. It
  isn't code-signed, so SmartScreen may warn the first time: click **More info → Run anyway**.
- Every release now includes both the Linux AppImage and the Windows exe.

### Fixed
- Text is sharp on Windows displays scaled to 125% or 150%. It used to be blurry because the
  window was being stretched.

## [1.0-1] - 2026-11-15

First stable release.

### Changed
- Redesigned the app window:
  - dark theme with AULA's orange as the highlight colour
  - controls grouped into cards
  - one large **Upload to keyboard** button that shows progress as a percentage
- The preview is drawn inside a screen-style frame. With no file loaded it's a drop zone that lights
  up while you drag a file over it.
- Fit, Rotate and Send to are now button groups instead of radio lists. A line underneath says
  which slot the upload goes to and that the other slot is kept.
- File info is shown in plain words, e.g. "Animation · 12 frames · 1.2s loop".
- Frame delay and port selection moved into a collapsible **Advanced** section.
- The progress bar only appears while uploading. The status line is coloured: green when
  ready or done, orange while working, red on errors.

### Added
- Connection indicator ("Connected · ttyACM0" / "Keyboard not connected") that updates when the
  keyboard is plugged in or out.
- Keyboard shortcuts: Ctrl+O to open a file, Ctrl+U to upload.

## [0.1.1] - 2026-11-15

### Added
- Linux permissions are set up automatically. The first time Linux refuses access to the keyboard's
  screen, the app asks for your password once and installs the udev rule, then the upload carries on.
  You won't be asked again, and you don't need to replug the keyboard.
- `l99screen setup` command to do the permission setup up front.

### Fixed
- "Permission denied" on `/dev/ttyACM0` (seen on CachyOS/Arch). The udev rule was named
  `99-aula-l99-screen.rules`, which sorts after systemd's `73-seat-late.rules`, so its access tag
  had no effect. It's now `70-aula-l99-screen.rules`, and the old file is removed during setup.
- Permission errors now say how to fix them instead of showing the raw serial-port error.

## [0.1.0] - 2026-11-15

First release.

### Added
- Upload a still picture (JPG, PNG, …) or an animation (GIF, APNG, WebP) to the AULA L99's
  320×480 screen from Linux or Windows, without AULA's software.
- Pictures and animations go to separate slots on the keyboard, so uploading one keeps the other.
- Fill, Fit (letterbox) and Stretch modes, rotation, and up to 15 animation frames. Longer GIFs are
  thinned out evenly and keep roughly their original speed.
- Graphical app with drag-and-drop and a live preview, and an `l99screen` command-line tool.
- Self-contained Linux AppImage.

[1.0-3]: https://github.com/SugarButterBuns/l99screen/releases/tag/v1.0-3
[1.0-2]: https://github.com/SugarButterBuns/l99screen/releases/tag/v1.0-2
[1.0-1]: https://github.com/SugarButterBuns/l99screen/releases/tag/v1.0-1
[0.1.1]: https://github.com/SugarButterBuns/l99screen/releases/tag/v0.1.1
[0.1.0]: https://github.com/SugarButterBuns/l99screen/releases/tag/v0.1.0
