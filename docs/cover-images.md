# Cover images

The cover is the picture other apps receive instead of the camera, when you press
**Cover camera**, and for a moment while the camera starts or switches. It is an
SVG file, so anyone can make or change one in an ordinary vector editor, or a text
editor.

## What the cover does

- **Cover camera** shows it, and **Uncover camera** brings the live picture back
  at once, because the camera keeps being read behind the cover.
- With **Show a notice while the camera starts or switches** on, the same image is
  shown with "One moment" and a short note such as "Switching camera", so a call
  does not look frozen while the phone restarts its camera.
- The preview in the window shows the cover too, because it shows what other apps
  receive.
- With **Mirror the cover with the picture** on, the cover is mirrored when you
  have mirrored the picture, so it follows whatever your apps need. The cover is
  never rotated, because rotation is only there to put the camera right way up.

The cover can only show while the app's own camera is open, which is whenever the
webcam is starting, running or changing.

The cover hides the picture, but it does not turn the phone's camera off. See
[Covering the camera](user-guide.md#covering-the-camera).

## Using your own

Open **Cover image** in the side panel and press **Choose SVG...**. The app draws
the file once before it accepts it. If it cannot be drawn, you are told why and
the image stays as it was. **Use built-in** goes back to the default.

The title and subtitle are typed in the same panel. They are limited to 32 and 64
characters, so they fit on one line.

The app remembers the path, and not a copy of the file, and it reads the file
when the webcam starts and when you change the cover. After editing a cover that is
already chosen, stop and start the webcam, or choose the file again, to see the
change. If the file is moved or deleted, the cover falls back to a plain colour
and the log says so.

## Making a cover

Start from the built-in one, which is
[`phone_webcam/slates/default.svg`](../phone_webcam/slates/default.svg), or from
this small one:

```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="1920" height="1080" viewBox="0 0 1920 1080">
  <rect width="1920" height="1080" fill="#202124"/>
  <image x="80" y="80" width="200" height="200" xlink:href="{{icon}}" href="{{icon}}"/>
  <text x="960" y="560" text-anchor="middle" font-family="sans-serif"
        font-size="96" fill="#ffffff">{{title}}</text>
  <text x="960" y="650" text-anchor="middle" font-family="sans-serif"
        font-size="44" fill="#bbbbbb">{{subtitle}}</text>
</svg>
```

### Placeholders

| Placeholder    | Replaced with                                                       |
| -------------- | ------------------------------------------------------------------- |
| `{{title}}`    | The title you typed, or "One moment" for a notice.                  |
| `{{subtitle}}` | The subtitle you typed, or the notice, such as "Switching camera".  |
| `{{icon}}`     | This app's icon, as an address you can give to an `<image>`.        |

The text is made safe for you, so `&`, `<` and `>` in a title are drawn as they
are. A placeholder you do not use is simply ignored, and a cover with no
placeholders at all is just a picture.

### Rules to keep in mind

- **Size.** Make it 1920x1080, or the size of your output. A picture of another
  shape is scaled to fit and centred with black bars, not stretched. A small one is
  scaled up, so it can look soft, which is why the full size is best.
- **Text does not wrap.** SVG has no line breaking, so keep titles short, and
  place the text on a line that fits. At a font size of 88, 32 characters
  usually fit inside 1920 pixels with room to spare.
- **Fonts come from the computer.** Name a common family such as `sans-serif`. A
  font you have installed may not exist on someone else's machine.
- **Put pictures inside the file.** Use `data:` addresses, as `{{icon}}` does.
  Linked files are not found, because the file is drawn from a temporary copy.
- **Keep it under 2 MB.** Larger files are refused.
- **It is only drawn.** Scripts and animation in an SVG are ignored, and the
  result is a still picture.

Embedding a picture in an SVG is a "Link or embed" choice in most editors. In
Inkscape, choose **Embed** when you import an image. From a terminal, a PNG can be
embedded as a data address:

```bash
printf 'data:image/png;base64,%s' "$(base64 -w0 logo.png)"
```

Paste the result into the `href` of an `<image>`.

## When the cover looks wrong

| You see                                 | Why, and what to do                                           |
| --------------------------------------- | ------------------------------------------------------------- |
| A plain blue colour, no text            | ffmpeg cannot draw SVG, or the file could not be read. The log says which. |
| The old image after you edited the file | The cover is read when it is chosen or the webcam starts. Stop and start, or choose the file again. |
| "ffmpeg could not draw it"              | The SVG is not valid. Open it in a browser or an editor to find the fault. |
| Text runs off the edge                  | It does not wrap. Shorten it, or use a smaller font size.     |
| Text is in a different font             | The font is not on this computer. Use a common family.       |
| A picture is missing                    | It was linked, not embedded. Embed it as a `data:` address.   |
| Black bars around the image             | The SVG is not 16:9. Make it 1920x1080.                       |

## For developers

The cover is drawn by `phone_webcam/slate.py`. It fills the placeholders in, hands
the SVG to ffmpeg's librsvg decoder, and gets one raw frame back, which the
pipeline repeats in place of the camera. ffmpeg is already required, so this adds
no dependency. All four frames, the shutter and the three notices, are drawn at the
same time before the output opens, which takes about 0.15 seconds, and are drawn
again only when the text or the file changes. See the
[architecture](architecture.md#turn-and-cover) for how the pipeline uses them.
