# Troubleshooting

The usual problems, with the message you will see and what to do about it. The
first thing to do in every case is read the **log** in the window, because most
of what goes wrong is explained there. The **Copy** button above it copies all of
it, ready to paste into a bug report.

Two commands help from a terminal as well:

```bash
phone-webcam --check      # every dependency, with what is missing
adb devices               # what the phone looks like to adb
```

## The phone

### The window is covered by "No phone connected"

adb cannot see the phone.

- Use a cable that carries data. Many cables only charge, and a different cable is
  the most common fix.
- Turn on **USB debugging** under Developer options. See the
  [user guide](user-guide.md#before-you-start) if you have not unlocked those.
- Pull down the phone's notification shade after plugging in, and make sure the
  USB mode is not set to "charging only". File transfer is the safe choice.
- Run `adb devices`. If the phone is not listed there either, the problem is the
  cable, the port or the phone's settings, not this app.
- In the devcontainer, the USB bus has to be passed through. See
  [CONTRIBUTING.md](../CONTRIBUTING.md#the-devcontainer).

### "Approve USB debugging"

The phone is connected, but has not been told to trust this computer. Look at the
phone and tap **Allow** on the dialog. If it never appears, unplug the phone,
plug it in again, and on the phone choose **Revoke USB debugging authorisations**
in Developer options first.

### "The phone is not responding"

adb sees the phone as `offline`. Unplug it and plug it back in. If it keeps
happening, run `adb kill-server` and try again.

### The camera list is empty

The list comes from `scrcpy --list-cameras`, so it needs the phone, and it needs
scrcpy 2.2 or newer. Press **↻** to ask again. If it is still empty, run
`scrcpy --list-cameras` in a terminal and see what it says. Camera mirroring needs
Android 12 or newer.

## The virtual camera

### The dependency check says the kernel module is missing

`v4l2loopback` is not installed for the kernel you are running.

- **Fedora:** it comes from [RPM Fusion](https://rpmfusion.org/Configuration).
  Enable its free repository, then `sudo dnf install v4l2loopback`. After a
  kernel update, the module is rebuilt on the next boot, so a missing module
  straight after an update usually fixes itself with a restart.
- **Debian and Ubuntu:** `sudo apt install v4l2loopback-dkms` and the headers for
  your kernel (`linux-headers-$(dpkg --print-architecture)`).
- **Secure Boot:** an unsigned module will not load. The log shows the reason
  from `modprobe`, which usually mentions the key being rejected. Either sign the
  module (RPM Fusion's page explains how on Fedora) or turn Secure Boot off.

### "The command failed" while loading the module

The log shows what `modprobe` said. The usual causes are Secure Boot, as above, a
kernel that has no module built for it yet, and no polkit agent in your session
to ask for the password. A normal GNOME or KDE session has one.

### No password prompt appears

The prompt comes from polkit, so the session needs an authentication agent
running. On a desktop environment it is part of the session. On a bare window
manager, start one such as `polkit-gnome-authentication-agent-1`. As a stopgap,
load the module yourself in a terminal and press **Start** again:

```bash
sudo modprobe v4l2loopback devices=1 exclusive_caps=1 card_label="Android Webcam"
```

### "The webcam device cannot be set up while another app uses v4l2loopback"

The module is already loaded by something else, such as OBS's virtual camera, and
the app cannot add its own camera without disturbing it. Close the other
program and press **Start** again.

### The app asks whether to reload v4l2loopback

The module was loaded without the `Android Webcam` camera, and `v4l2loopback-ctl`
is not installed to add one. A reload creates it, and removes any other virtual
cameras until their owners set them up again. Answer **Yes** if that is fine.
Installing `v4l2loopback-ctl` lets the app add its camera without a reload next
time. The dependency check names the package for your distribution.

### Keeping the camera across reboots

The module has to be created again after every boot, which is why the password
prompt comes back. To have the system do it, make two small files:

```bash
echo v4l2loopback | sudo tee /etc/modules-load.d/v4l2loopback.conf
echo 'options v4l2loopback devices=1 exclusive_caps=1 card_label="Android Webcam"' \
  | sudo tee /etc/modprobe.d/v4l2loopback.conf
```

The app finds the camera by its label, so with this in place it never needs to
ask. These are the standard settings for the module, check them against your
distribution's documentation if something differs.

## Other apps do not see the camera

- **Look for "Android Webcam".** The camera is listed under that name.
- **Restart the other app.** Many apps read the list of cameras once, when they
  start. Open them after you press **Start**.
- **Browsers** ask for permission to use the camera, and remember the answer for
  each site.
- **Flatpak and Snap apps** may need permission to reach camera devices. Check the
  app's permissions for camera or device access.
- **A black picture.** The cover may be on, so check the **Cover camera** button.
  If the preview in the window is fine and the other app is black, restart that
  app.
- **"Device or resource busy".** Something has the camera open in a different
  format. Close the other app, then start again. If you changed the resolution, an
  app that opened the camera earlier still expects the old one.

## Picture and performance

### The picture lags

See [Getting a good picture with little delay](user-guide.md#getting-a-good-picture-with-little-delay).
Try 720p first, then a lower bitrate.

### The picture freezes for a moment

That is expected when you switch cameras or change the frame rate or bitrate,
because the phone restarts its camera. The last picture is held, and the cover
image shows a notice if that is turned on, so other apps keep the camera. If
it freezes at other times, the phone may be overheating, or the USB connection
dropping. Try another cable or port.

### The picture is rotated or upside down

Use **Orientation** to turn it. Phones deliver the camera in its natural
direction, and the app turns it as you ask. The choice is remembered.

### A camera will not switch, or settings are refused

The log says "That could not start, going back to the previous choice." The phone
refused what you chose. Some lenses do not support every size or frame rate, so
try 30 frames a second, or 720p. Using a particular camera, not "Default camera",
lets the app keep the choice within what that camera reports.

### The cover shows a plain colour and no text

ffmpeg cannot draw SVG. The dependency check shows "ffmpeg SVG support" with a
dash, and the log says why. Install an ffmpeg built with librsvg, which is the
normal one on Fedora and Debian. If you are using your own SVG, the log says what
was wrong with it.

## The window

### The preview is empty

The preview only runs while the webcam is running and this window is in front, and
the frame says which it is waiting for. If it says "Waiting for the camera...",
the webcam is running but has not delivered a picture yet. If the log shows
"The preview did not produce a picture in time", ffmpeg may be missing or
failing, so check `phone-webcam --check`.

### The window does not open, or is blank

The log is not available yet, so start the app from a terminal and read what it
prints. If it says the graphical stack is incomplete, the dependency check names
the libraries to install. On some graphics setups the web engine needs software
rendering. Try:

```bash
QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu" phone-webcam
```

and, to force the older display protocol when Wayland misbehaves:

```bash
QT_QPA_PLATFORM=xcb phone-webcam
```

The app already picks X11 by itself when the Wayland libraries are missing.

### Copy does not copy

The buttons copy through the desktop's clipboard. If nothing arrives, check that
a clipboard manager is not blocking it, and tell us your desktop and display
protocol in a bug report.

### The first start is slow

The binary unpacks itself into `~/.cache/Griffin Web Studio/Phone Webcam/` the
first time, and uses that afterwards, so only the first start takes a moment.
Starting an updated version unpacks it again, because it is kept in a folder named
after the version.

## Starting over

- **Reset your choices:** delete `~/.config/phone-webcam/prefs.json`.
- **Clear the unpacked app:** delete `~/.cache/Griffin Web Studio/Phone Webcam/`.
  It is made again on the next start.
- **Remove the virtual camera:** `sudo modprobe -r v4l2loopback`, once nothing is
  using it.

## Reporting a problem

Open an issue on [GitLab](https://gitlab.com/griffin-web-studio/garage/phone-webcam/-/issues)
with your distribution and desktop, the phone model and Android version, the
scrcpy version (`scrcpy --version`), the output of `phone-webcam --check`, and the
log from the window. The full list is in
[CONTRIBUTING.md](../CONTRIBUTING.md#how-to-contribute).
