# Documentation

Phone Webcam turns an Android phone's camera into a webcam. The
[README](../README.md) is the place to start. These pages go further.

## For people using the app

| Page                                      | Read it to                                                |
| ----------------------------------------- | --------------------------------------------------------- |
| [User guide](user-guide.md)               | Learn every part of the window, and get a good picture with little delay. |
| [Cover images](cover-images.md)           | Use the privacy cover, and make your own from an SVG.     |
| [Troubleshooting](troubleshooting.md)     | Fix a phone that is not found, a virtual camera that will not load, a black picture and the like. |

## For people working on it

| Page                                      | Read it to                                                |
| ----------------------------------------- | --------------------------------------------------------- |
| [Contributing](../CONTRIBUTING.md)        | Set up, run the tests, follow the commit rules, cut a release. |
| [Architecture](architecture.md)           | Understand how the video path, the threads and the window fit together, and why. |
| [Building and packaging](packaging.md)    | Make the binary, the RPM and the DEB, and avoid the traps. |

## Keeping them true

Documentation that is wrong is worse than none. When you change what the app does,
change the page that describes it in the same merge request:

- A new or changed setting: the README's settings tables and the
  [user guide](user-guide.md).
- A new message the app shows, or a new way for it to fail:
  [troubleshooting](troubleshooting.md).
- A change to the video path, the threads or the bridge:
  [architecture](architecture.md).
- A new file the app reads at run time, a new dependency, or a build change:
  [packaging](packaging.md).
