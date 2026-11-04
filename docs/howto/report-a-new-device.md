# Report a new device

bcgacha has been tested on one iPhone. Every report from another iPhone or an
iPad, working or not, tells the next person what to expect. The steps below
spend one Cat Ticket and one Rare Cat Ticket; skip those lines to spend
nothing.

## Steps

1. Plug the device in, unlock it and run the check. Note the model, the iOS
   version and the screen size it prints:

   ```
   bcgacha check    # the "device" line names the model and screen size
   ```

2. Try the parts you use, and note for each whether it worked:

   ```
   bcgacha run --rescan-map       # walks the menus: learns the buttons on this screen
   bcgacha run --capsules cat:1   # opens one Cat Capsule
   bcgacha run --roll --rare 1    # one rare draw (asks first)
   bcgacha run --play-legends     # the Uncanny Legends player
   ```

   Stop any of them with Ctrl+C if it taps somewhere wrong.

3. Open a [device report](https://github.com/NotEoin/battle-cats-automation/issues/new?template=device-report.md)
   and fill it in. If something went wrong, add the last lines the terminal
   printed, and a screenshot of the game screen where it stopped.

## If something goes wrong

| Symptom | Fix |
|---|---|
| A tap lands in the wrong place | Stop the run (Ctrl+C) and say which screen and which button in the report. |
| A screen is never recognised | The terminal names the screen it expected. Put that in the report. |
| You do not have a GitHub account | Creating one is free; an issue cannot be opened without one. |
