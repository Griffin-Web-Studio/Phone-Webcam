## Phone Webcam {{TAG}}

**Channel:** {{CHANNEL}}

### Install

Phone Webcam turns an Android phone's camera into a webcam. Pick the package for
your system, they all contain the same app.

> [!NOTE]
> You need a Linux desktop (X11 or Wayland) with glibc 2.38 or newer, for example
> Fedora 39 or later, Debian 13, or Ubuntu 24.04 or later. The app checks for
> everything else when it starts and tells you what is missing. The
> [README](https://gitlab.com/griffin-web-studio/garage/phone-webcam#requirements)
> lists it all.

#### Fedora

```bash
curl -fL -o phone-webcam.rpm "{{PACKAGE_URL}}/phone-webcam.rpm"
sudo dnf install ./phone-webcam.rpm
```

The virtual camera comes from the `v4l2loopback` kernel module, which is in
[RPM Fusion](https://rpmfusion.org/Configuration). Enable its free repository,
then `sudo dnf install v4l2loopback`.

#### Debian and Ubuntu

```bash
curl -fL -o phone-webcam.deb "{{PACKAGE_URL}}/phone-webcam.deb"
sudo apt install ./phone-webcam.deb
sudo apt install v4l2loopback-dkms linux-headers-$(dpkg --print-architecture)
```

Debian does not package a scrcpy new enough for camera mirroring. Install it
from the [official releases](https://github.com/Genymobile/scrcpy/releases), with
`scrcpy` and `adb` on your `PATH`.

#### Any other Linux

The packages contain one file, which also runs on its own. Nothing is installed
or changed on your system:

```bash
curl -fL -o phone-webcam "{{PACKAGE_URL}}/phone-webcam"
chmod +x phone-webcam
./phone-webcam
```

### Check what you downloaded

```bash
curl -fL -o SHA256SUMS "{{PACKAGE_URL}}/SHA256SUMS"
sha256sum --check --ignore-missing SHA256SUMS
```

### Uninstall

```bash
sudo dnf remove phone-webcam     # Fedora
sudo apt remove phone-webcam     # Debian and Ubuntu
```

Your saved choices stay in `~/.config/phone-webcam/` until you delete them.
