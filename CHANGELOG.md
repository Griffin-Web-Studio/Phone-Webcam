## v1.0.0 (2026-10-10)

### Bug Fixes

- **ci**: explain why the nightly release cannot delete the old one
- **deps**: find Qt libraries in a compiled build
- **ui**: copy install command through the qt clipboard

### Features

- **ui**: add the cover toggle and cover image settings
- **webcam**: add the privacy shutter and busy notices
- **pipeline**: show a cover frame instead of the camera
- **settings**: add cover image settings
- **slate**: draw a cover image from an SVG with ffmpeg
- **deps**: check that ffmpeg can draw SVG
- **ui**: apply GWS branding with a resizable side panel and automatic preview
- **api**: resize the window, save the panel width and follow the preview wish
- **webcam**: apply frame rate and bitrate changes live
- **pipeline**: change the output frame rate while running
- **ui**: add camera picker, stream settings and phone notice
- **webcam**: switch cameras live and apply stream settings
- **settings**: add validated stream settings
- **phone**: watch adb and report the phone's state
- **pipeline**: restart the reader, letterbox and set the preview rate
- **cameras**: list phone cameras, sizes and frame rates
- **ui**: show the live preview with a busy overlay
- **webcam**: record through a fifo and drive the preview
- **preview**: serve the turned frames as an mjpeg stream
- **pipeline**: read scrcpy through a fifo
- **ui**: add orientation controls, preview and confirmation dialog
- **webcam**: run scrcpy on a pty and feed the pipeline
- **pipeline**: turn camera frames between loopback devices
- **deps**: gate on ffmpeg and add numpy
- expose webcam controls through the api
- **webcam**: add scrcpy controller with event callback
- **ui**: add main page and skip the gate when all checks pass
- **deps**: add packages_for and drop scrcpy debian package
- add webview window showing dependency check
- add dependency gates for GUI stack and phone tooling

### Refactoring

- **packaging**: use the real reverse domain for the application id
- **loopback**: use a single output device
