# Install on Linux

This puts the `bcgacha` command on a Linux computer. It is the platform the
author uses every day.

## Steps

1. Install `usbmuxd`, the service that talks to iPhones and iPads over USB,
   and `libgl1`, which the screen reader needs:

   ```
   sudo apt install usbmuxd libgl1          # Debian, Ubuntu, Mint
   sudo dnf install usbmuxd mesa-libGL      # Fedora
   sudo pacman -S usbmuxd libglvnd          # Arch
   ```

2. Plug the phone in and unlock it. If it asks **Trust This Computer?**, tap
   Trust and enter the passcode.

3. Install `uv`, a small tool that installs Python programs:

   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh    # installs uv
   ```

4. Open a new terminal, so it finds `uv`.

5. Install bcgacha:

   ```
   uv tool install https://github.com/NotEoin/battle-cats-automation/archive/refs/heads/main.zip   # takes a few minutes the first time
   ```

6. Check it starts:

   ```
   bcgacha --help    # prints the list of commands
   ```

7. Go on to [Prepare your iPhone or iPad](prepare-your-device.md).

No step needs root apart from installing `usbmuxd`.

## Updating and removing

```
uv tool upgrade bcgacha      # the newest version
uv tool uninstall bcgacha    # removes the program
```

Uninstalling leaves what bcgacha learned in `~/.local/share/bcgacha`. Delete
that folder to remove it too.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `command not found: bcgacha` after installing | Run `uv tool update-shell`, then open a new terminal. |
| "No iPhone is plugged in" | Check `usbmuxd` is running: `systemctl status usbmuxd`. Unplug and replug the phone; try another cable. |
| `Failed to connect to usbmuxd socket` | Install `usbmuxd` (step 1), then unplug and replug the phone, which starts it. |
| `ImportError: libGL.so.1` | Install `libgl1` (or your distribution's `libGL`), step 1. |
