# Troubleshooting

Find the message or symptom, then try the fix. `bcgacha check` goes through
the setup in order and is the best first step for anything about the device.
Installing problems are covered at the end of each install guide.

## The device

| Symptom | Fix |
|---|---|
| "No iPhone or iPad is plugged in" | Use a cable that carries data. On Windows, install Apple Devices from the Microsoft Store; on Linux, install `usbmuxd`. Unlock the device. |
| "does not trust this computer" | Unlock the device, unplug and replug it, and tap Trust. |
| "Developer Mode is off", and there is no switch in Settings | Run `bcgacha check` with the device unlocked; it makes the switch appear. Reopen Settings. |
| "The developer disk image would not mount" | Unlock the device and try again. The first mount downloads the image, so the computer must be online. |
| "taps need iOS 27 or later" | Update iOS. Earlier versions do not let a computer tap the screen. |
| "attached but would not connect" | Unlock the device. Unplug and replug it. Restart the device if it persists, then run `bcgacha check`. |
| "has a shape nobody has tested" | Not an error. Watch the first run, stop it with Ctrl+C if a tap lands in the wrong place, and [report the device](howto/report-a-new-device.md). |
| The run stops when the screen goes dark | Set **Settings > Display & Brightness > Auto-Lock** to Never while bcgacha works. |

## Runs

| Symptom | Fix |
|---|---|
| "seed not identified" | bcgacha needs the seed once: [Find your seed](howto/find-your-seed.md). |
| "there is no complete list of owned cats" | Run anything on the device once (`bcgacha run`); it reads the Cat Guide first. |
| A draw came out different from the plan | Draws were made by hand since the last run. `bcgacha tools resync --cat "NAME"` with the cat that came out. |
| "The live page is already running" | A page from an earlier run is still open. Start the run from that page, or close the other terminal. |
| A screen is never recognised | Make sure the game is in English. Delete the screen-size folder under `state/devices` in the bcgacha folder to make it learn again. |
| Cat Storage is full | Add `--empty-storage` to the run. |
| "no unit is called ..." | `bcgacha search` with part of the name, then use the name or `#id` it shows. |

## Data

| Symptom | Fix |
|---|---|
| "using the schedule saved" | The computer is offline. Events are updated on the next run that is online. |
| A new event is missing | `bcgacha tools update`. godfat's dataset usually has new events within a day. |
| Where are bcgacha's files? | `bcgacha status` prints the folder. See [the user guide](user-guide.md#where-bcgacha-keeps-its-files). |
| Starting over | Delete the bcgacha folder. The seed's position is lost with it; keep `state/account.json` if you want it. |
