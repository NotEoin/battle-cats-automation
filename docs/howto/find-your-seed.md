# Find your seed

bcgacha predicts draws from your account's seed: one number that decides
every Rare Cat Capsule draw. It needs it once. After that it keeps track of
where you are by itself, as long as every rare draw goes through bcgacha.

Finding the seed costs about ten Rare Cat Tickets, drawn by hand. If you
already know your seed from bc.godfat.org, skip to step 5.

## Steps

1. Pick an event that is live today:

   ```
   bcgacha tools banners    # lists today's banners and their keys, such as 2026-09-21_979
   ```

2. In the game, open the Rare Cat Capsule on that event and draw **one at a
   time** with Rare Cat Tickets, ten times. Do not use an 11-draw. Write down
   every cat in the order it came out, including the Rare ones.

3. Search for the seed. Put the names in draw order, separated by commas:

   ```
   bcgacha tools find-seed --event 2026-09-21_979 --cats "Cat A,Cat B,Cat C,Cat D,Cat E,Cat F,Cat G,Cat H,Cat I,Cat J"
   ```

   This tries every possible seed and takes a few minutes. It ends by
   printing the seed and the command for step 5.

4. If it says more than one seed fits, draw once more, add that cat to the
   end of the list, and run step 3 again.

5. Save the seed, naming the last cat you drew:

   ```
   bcgacha tools set-seed 1234567890 --cat "Cat J"    # use your own seed and cat
   ```

   bcgacha works out where along the seed that cat came out, and saves it.

6. Check it:

   ```
   bcgacha status    # shows the seed and position
   ```

## Keeping it right

Every rare draw moves the position on. bcgacha follows the draws it makes
itself, and checks each result against its prediction. If you draw by hand
later, tell it which cat came out last:

```
bcgacha tools resync --cat "Figure Skating Cats"    # finds the position that gives that cat
```

## If something goes wrong

| Symptom | Fix |
|---|---|
| "no seed matches" | A name is wrong or out of order, or a draw was missed. Check the names with `bcgacha search NAME`. |
| More than one seed fits | Draw once more and add that cat to the list. |
| `set-seed` says the cat appears at more than one position | Draw once more by hand, then run `set-seed` again naming that cat. |
| `set-seed` refuses because a position is already saved | Add `--force` to replace it. The old one is lost. |
| Predictions stop matching the game | Draws were made outside bcgacha. Use `bcgacha tools resync`. |
