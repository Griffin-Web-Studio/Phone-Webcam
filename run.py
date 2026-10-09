#!/usr/bin/env python3
"""Entry point. Kept free of third-party imports so the gates can run first."""

import sys

from phone_webcam.main import main

if __name__ == "__main__":
    sys.exit(main())
