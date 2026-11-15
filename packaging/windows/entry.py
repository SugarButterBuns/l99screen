"""PyInstaller entry point for the Windows build: opens the GUI (optionally with a file)."""
import sys

from l99screen.gui import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
