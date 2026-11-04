# Install on Windows

This puts the `bcgacha` command on a Windows 10 or 11 computer. You need to
be signed in as a user who may install apps. You do not need Python or Git;
the installer below fetches what it needs.

The phone link on Windows has not been tested by the author yet (the tests
run on Windows in CI, but no phone was attached). If something here does not
work, please [open an issue](https://github.com/NotEoin/battle-cats-automation/issues).

## Steps

1. Install Apple's device driver. Open the Microsoft Store, search for
   **Apple Devices**, and install it. (iTunes from apple.com works too.)
   Without it, Windows cannot talk to an iPhone or iPad over USB.

2. Plug the phone in and unlock it. If it asks **Trust This Computer?**, tap
   Trust and enter the passcode. Open the Apple Devices app once and check
   the phone appears there; then close the app.

3. Open **PowerShell**: press the Windows key, type `powershell`, and press
   Enter.

4. Install `uv`, a small tool that installs Python programs:

   ```
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # installs uv
   ```

5. Close PowerShell and open it again, so it finds `uv`.

6. Install bcgacha:

   ```
   uv tool install https://github.com/NotEoin/battle-cats-automation/archive/refs/heads/main.zip   # takes a few minutes the first time
   ```

7. Check it starts:

   ```
   bcgacha --help    # prints the list of commands
   ```

8. Go on to [Prepare your iPhone or iPad](prepare-your-device.md).

## Updating and removing

```
uv tool upgrade bcgacha      # the newest version
uv tool uninstall bcgacha    # removes the program
```

Uninstalling leaves what bcgacha learned in `%LOCALAPPDATA%\bcgacha`. Delete
that folder to remove it too.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `uv` is not recognised | Close PowerShell and open a new one. If it still fails, run step 4 again and read its last lines for the folder it installed into. |
| `bcgacha` is not recognised after installing | Run `uv tool update-shell`, then close and reopen PowerShell. |
| `running scripts is disabled on this system` | Use the exact command in step 4; `-ExecutionPolicy ByPass` allows that one script only. |
| "No iPhone is plugged in" | Check the Apple Devices app sees the phone. Try another cable or port: some cables only charge. |
| The install stops with an error about building a package | Your Windows may be missing the Microsoft Visual C++ Redistributable. Install the latest one from Microsoft, then run step 6 again. |
