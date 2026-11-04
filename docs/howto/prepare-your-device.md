# Prepare your iPhone or iPad

bcgacha reads the screen and taps it through the developer features built
into iOS. They are off until you turn them on. This is done once per device.
Install bcgacha on your computer first.

## Before you update to iOS 27

bcgacha needs iOS 27 or later. If your device runs an older version, know
what the update brings before you agree to it.

iOS 27 adds Apple's age checks to the whole device, not to one app. In
Australia, Brazil, Singapore, South Korea, the UK and the US state of Texas,
the device asks you to prove you are an adult. The prompt can come up when
you install the update, when you change some safety settings, or when you
download an app rated 18+. Depending on where you live, the proof is a selfie
scan, a credit card, or a passport, driving licence or other government ID.

You can say no and keep using the device. Until you confirm, though, it keeps
some safety settings switched on and will not install apps rated 18+. Apple
does not let you go back to an older iOS once it stops signing it, which it
usually does a few weeks after a new version comes out, so treat the update as
permanent.

This is what was reported when iOS 27.2 came out, checked on 2026-11-06
([MacRumors](https://macrumors.com/2026/10/28/ios-27-2-adds-selfie-based-age-verification/),
[Privacy Guides](https://www.privacyguides.org/news/2026/10/29/apple-introduces-selfie-age-verification-in-ios-27-2/)).
Apple can change it, and add more countries. Read what your device asks for
before you tap through it.

## Steps

1. Check the iOS version: **Settings > General > About > iOS Version**. It
   must be 27 or later to let bcgacha tap. If it is older, read
   [Before you update to iOS 27](#before-you-update-to-ios-27), then update in
   **Settings > General > Software Update**.

2. Plug the device into the computer and unlock it. Tap **Trust** if it asks,
   and enter the passcode.

3. Run the check. It makes the Developer Mode switch appear on the device,
   which iOS hides until a developer tool has connected:

   ```
   bcgacha check    # says what is ready and what to do next
   ```

4. On the device, open **Settings > Privacy & Security > Developer Mode**
   (near the bottom of the list), turn it on, and tap **Restart**.

5. After the restart, unlock the device and tap **Turn On** when it asks
   about Developer Mode, then enter the passcode.

6. Run the check again. The first time, it downloads Apple's developer disk
   image for your iOS version and mounts it, which needs an internet
   connection and can take a minute:

   ```
   bcgacha check    # every line should now say ok
   ```

7. Stop the screen locking while bcgacha works: **Settings > Display &
   Brightness > Auto-Lock > Never**. A locked screen stops a run. Set it back
   when you are done.

8. Open The Battle Cats and leave it on any screen. Run `bcgacha` to begin.

The disk image comes off every time the device restarts. bcgacha mounts it
again by itself before each run.

## If something goes wrong

| Symptom | Fix |
|---|---|
| There is no Developer Mode entry in Privacy & Security | Run `bcgacha check` with the device unlocked and plugged in, then close and reopen Settings. |
| The check says "not trusted" or "pairing" | Unlock the device, unplug and replug it, and tap Trust. If you tapped Don't Trust before: **Settings > General > Transfer or Reset > Reset > Reset Location & Privacy**, then replug. |
| "taps need iOS 27 or later" | Update iOS. Below 27, Apple does not let a computer tap the screen. |
| "The developer disk image would not mount" | Unlock the device and try again; it must be unlocked while mounting. Check the computer is online the first time. |
| The run stops with the screen black | The device locked itself. Set Auto-Lock to Never (step 7). |
