# Install on macOS

This puts the `bcgacha` command on a Mac. macOS already knows how to talk to
an iPhone or iPad, so there are no drivers to install, and you do not need
Python or Git.

The phone link on macOS has not been tested by the author yet (the tests run
on macOS in CI, but no phone was attached). If something here does not work,
please [open an issue](https://github.com/NotEoin/battle-cats-automation/issues).

## Steps

1. Plug the phone in and unlock it. If it asks **Trust This Computer?**, tap
   Trust and enter the passcode.

2. Open **Terminal**: press Cmd+Space, type `terminal`, and press Return.

3. Install `uv`, a small tool that installs Python programs:

   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh    # installs uv
   ```

4. Close Terminal and open it again, so it finds `uv`.

5. Install bcgacha:

   ```
   uv tool install https://github.com/NotEoin/battle-cats-automation/archive/refs/heads/main.zip   # takes a few minutes the first time
   ```

6. Check it starts:

   ```
   bcgacha --help    # prints the list of commands
   ```

7. Go on to [Prepare your iPhone or iPad](prepare-your-device.md).

## Updating and removing

```
uv tool upgrade bcgacha      # the newest version
uv tool uninstall bcgacha    # removes the program
```

Uninstalling leaves what bcgacha learned in
`~/Library/Application Support/bcgacha`. Delete that folder to remove it too.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `command not found: uv` | Close Terminal and open a new window. If it still fails, run step 3 again and read its last lines for the folder it installed into. |
| `command not found: bcgacha` after installing | Run `uv tool update-shell`, then close and reopen Terminal. |
| "No iPhone is plugged in" | Check Finder lists the phone in its sidebar. Try another cable or port: some cables only charge. |
| macOS asks whether Terminal may access something | Allow it; bcgacha only reads the phone and its own folder. |
