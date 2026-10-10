# User guide

A walkthrough of Phone Webcam, from the first start to getting the best picture
with the least delay. If something does not work, the
[troubleshooting guide](troubleshooting.md) has the usual fixes.

## Before you start

You need the tools and the kernel module listed in the
[README](../README.md#requirements), and an Android phone with USB debugging
turned on. If you have not turned that on before:

1. Open **Settings**, then **About phone**, and tap **Build number** seven times
   to unlock developer options. The exact names differ between makers.
2. Open **Developer options** and turn on **USB debugging**.
3. Plug the phone in with a cable that carries data. Some cables only charge.
4. When the phone asks whether to allow USB debugging from this computer, tap
   **Allow**. You can tick the box to always allow it.

You do not need to do anything else on the phone. There is no app to install.

## The first start

### The dependency check

The first thing you see is a short checklist. Each line is one thing the app
needs.

| Mark        | Meaning                                                               |
| ----------- | --------------------------------------------------------------------- |
| a tick      | Found, nothing to do.                                                 |
| a cross     | Required, and missing. The app cannot run without it.                 |
| a dash      | Optional, and missing. The app works, with a small loss, explained next to it. |

When something is missing, the page shows one command that installs all of it,
with a **Copy** button. Paste it in a terminal, then press **Re-check**. The
**Continue** button appears once nothing required is missing. If every line is a
tick, the app skips this page and goes straight to the main window.

The optional ones are `v4l2-ctl`, `v4l2loopback-ctl` and ffmpeg's SVG support.
Without `v4l2loopback-ctl` the app can still create its camera, but if another
program already loaded the module it has to reload it instead of adding a camera
beside the others. Without SVG support the cover image is a plain colour.

### Waiting for the phone

Until a phone is ready, a notice covers the whole window and cannot be closed.
It says what to do:

| It says                      | What to do                                              |
| ---------------------------- | ------------------------------------------------------- |
| No phone connected           | Plug it in, turn on USB debugging, try another cable.   |
| Approve USB debugging        | Look at the phone and tap **Allow**.                    |
| The phone is not responding  | Unplug it and plug it in again.                         |
| adb could not be run         | Install the Android platform tools (the `adb` command). |

The notice goes away by itself the moment the phone is ready, and the list of
cameras is loaded. It comes back if you unplug the phone, and the webcam stops.

## The main window

The window has two panels. The **side panel** on the left has the controls, and
the **main area** on the right has the preview and the log. Drag the divider
between them to change the widths. It also moves with the left and right arrow
keys when it has focus, and double-clicking it puts it back. The width is
remembered.

### Starting and stopping

The first button under the status is **Start** while the webcam is stopped, and
**Stop** while it is anything else, so it also cancels a start that is under way.
The status shows what is happening:

| Status               | Meaning                                                      |
| -------------------- | ------------------------------------------------------------ |
| Stopped              | Nothing is running.                                          |
| Starting...          | Setting up the camera, until the first picture arrives.      |
| Running              | The webcam is working.                                       |
| Switching camera...  | Moving to another lens, see below.                           |
| Applying settings... | The frame rate or bitrate is changing.                       |
| Stopping...          | Shutting down.                                               |

The first start after each boot shows a password prompt. It is your system asking
permission to create the virtual camera, and nothing else is changed. If another
program, such as OBS, already loaded the virtual camera module, the app adds its
camera beside the existing ones when it can, and otherwise asks before
reloading the module, because that removes the others until they are set up
again.

Once it is running, open your video call or browser and choose the camera called
**Android Webcam**.

### Choosing a camera

Open **Camera** and pick a lens from the list, for example "Back camera 0,
4000x3000" or "Front camera 1". The ↻ button asks the phone again. The list loads
by itself when the phone is ready, so you rarely need it.

- Before you start, the choice is used for the next start.
- While running, choosing another lens switches to it. The picture holds for a
  couple of seconds, and other apps keep the camera. The window shows a notice
  from the cover image while it happens. If the phone cannot start that lens, the
  app goes back to the one before and says so in the log.

"Default camera" lets scrcpy choose, which is usually the main back camera.

### Rotating and mirroring

Open **Orientation**. The two arrows rotate a quarter turn each way, **Mirror**
flips the picture, and **Reset** undoes both. The line underneath shows the
current angle.

It changes at once, with no restart, and it is remembered. Use rotation to put
the picture the right way up when the phone is mounted sideways. Mirroring is for
apps that treat it differently. Some show you a mirrored self-view but send the
real picture, others do not, and you can match whatever your apps need.

### The preview

The big frame shows what other apps receive, after rotation, mirroring and any
cover. It starts by itself once the webcam is running, and it only runs while
this window is in front, to save the work of encoding it when nobody can see it.
It comes back when you return to the window. While it is not showing, the frame
says why.

It does not use the virtual camera, so it never gets in the way of another app
using it. Its frame rate is set under **Stream settings**.

### Covering the camera

**Cover camera** replaces the picture other apps receive with the cover image,
and **Uncover camera** brings the live picture back at once. It also works before
you press Start, so a call can begin covered.

The cover hides the picture from other apps and from the preview, but the
phone's camera keeps running behind it. Its indicator stays on and the battery
keeps draining. Stop the webcam to turn the camera off.

The cover is always off when the app starts. Customising it is covered in the
[cover images guide](cover-images.md), and the options are under **Cover image**.

### Stream settings

These trade picture quality against delay and load. Frame rate and bitrate change
while running, with a short pause while the phone restarts its camera, and the
resolution only changes while stopped, because other apps agree on it when they
open the camera.

| Setting      | Choices                 | Default |
| ------------ | ----------------------- | ------- |
| Resolution   | 1080p, 720p             | 1080p   |
| Frame rate   | 15, 24, 30, 60          | 30      |
| Bitrate      | 4, 8, 12, 16, 24 Mbit/s | 8       |
| Preview rate | 15, 30, 60              | 30      |

A camera that does not offer what you chose is held to the closest thing it does
offer. If the phone refuses outright, for instance 60 frames a second on a lens
that cannot do it, the app goes back to your previous settings and says so in the
log.

### The log

The log shows what the app and scrcpy are doing, which is the first place to look
when something goes wrong. Select text with the mouse, or press **Copy** above it
to copy everything, which is what to paste into a bug report.

## Getting a good picture with little delay

Delay comes from the phone encoding the video, the computer decoding it, and the
steps in between. These can all help, and the first ones usually matter most,
though how much depends on your phone and computer:

1. **Use 720p.** It is less than half the pixels of 1080p, so every step has less
   to do.
2. **Lower the bitrate** to 4 or 8 Mbit/s. A USB cable carries far more, so this
   is about the work on both ends, not bandwidth.
3. **Keep to 30 frames a second**, unless the call is a place where you need
   smoother motion. A higher rate costs more encoding on the phone, and the
   output follows the rate you choose.
4. **Use a good cable and a fast port.** A USB 3 port and a short, good cable
   avoid retries.
5. **Close the preview** by putting another window in front, if the computer is
   struggling. It is cheap, but not free.

For the best quality, use 1080p with 12 or 16 Mbit/s, and make sure the phone is
not getting hot. A phone that overheats can slow its camera down.

## Command line

```bash
phone-webcam                       # open the window
phone-webcam --check               # run the dependency checks and exit
phone-webcam --simulate-missing scrcpy,ffmpeg   # see how a missing tool looks
```

`--check` prints the same checklist as the window and returns `0`, or `1` if
something required is missing, which makes it usable in scripts. The names that
`--simulate-missing` accepts are `scrcpy`, `adb`, `ffmpeg`, `ffmpeg_svg`,
`v4l2_ctl`, `v4l2loopback_ctl`, `pkexec`, `modprobe` and `v4l2loopback`.

## Your files

| Path                                                  | What it is                                    |
| ----------------------------------------------------- | --------------------------------------------- |
| `~/.config/phone-webcam/prefs.json`                   | Your saved choices.                           |
| `~/.cache/Griffin Web Studio/Phone Webcam/<version>/` | The unpacked app, made on the first start.    |

The saved file holds the rotation and mirror, the stream settings, the cover
settings and the side panel width. It does not hold the camera you chose or the
cover being on. Delete the file to go back to the defaults. The location follows
`XDG_CONFIG_HOME` when that is set.

## Privacy and safety

- The video goes from the phone to your computer over USB. Nothing is sent over
  the network.
- The preview is served by a small local web server that only listens on your own
  computer, on a random port, behind a random address that changes every time
  the preview opens.
- The only thing the app asks permission for is creating the virtual camera.
- A cover image is only drawn, and any script inside an SVG is ignored. Still,
  only choose covers you trust, because the file is read from your disk when you
  pick it.
