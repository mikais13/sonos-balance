# Sonos Balance

One volume slider for grouped Sonos speakers that get loud at different rates (here: an Era 100 and a Roam).

Sonos changes the volume of all speakers in a group by the same amount. An Era 100 gets louder faster than a Roam, so the balance between them changes as you turn the volume up or down. This app uses a separate volume for each speaker, so that they stay balanced at every slider position.

## How it works

1. You set the two speakers so that they sound equally loud, then save the pair.
2. The app fits one smooth curve through your newest 50 saved pairs. The curve follows the pairs on average and does not go through each pair exactly.
3. Each slider step moves the louder speaker (the speaker with the lower volume number) by exactly one step, and sets the other speaker from the curve. Neither speaker gets quieter when you move the slider up.
4. Above your loudest pair, the same curve continues. The slider stops at the last step that keeps both speakers at 100 or below. Thus you do not have to calibrate at high volume, but one pair near the top makes that part of the curve more accurate.

## Requirements

- macOS 14 or later
- [uv](https://docs.astral.sh/uv/)
- Xcode or the Xcode Command Line Tools (to build the app)
- This computer and the speakers on the same network. The Roam must use Wi-Fi, not Bluetooth.

## Build

```sh
./build.sh
```

This makes `SonosBalance.app` in this folder. Build again after you change `SonosBalance.swift` or move this folder.

## Start

```sh
open SonosBalance.app
```

A speaker icon shows in the menu bar. On the first start, macOS asks for permission to find devices on your local network. Click **Allow**. If macOS does not ask, go to System Settings → Privacy & Security → Local Network and turn on Sonos Balance.

The app starts the Python engine (`sonos_balance.py`) and stops it when you quit. You do not need a terminal.

## Use

Click the menu bar icon. The menu shows:

- **Slider**: the volume of the group.
- **− / +** for each speaker: change one speaker by one step.
- **Save pair**: save the current volumes as a balanced pair.
- **Quit Sonos Balance**

## Calibrate

1. Play music at a comfortable volume.
2. Use **−** and **+** until the two speakers sound equally loud.
3. Click **Save pair**.
4. Do steps 2–3 again at a few different volumes, for example quiet, normal and a little loud.

You can calibrate again at any time. A new pair goes into the list, and the oldest pair is removed when there are more than 50. The curve changes immediately.

## Web page

While the app is open, you can also use http://localhost:8765. The web page has the same controls, a list of the saved pairs with a **×** button to delete a pair, and **Delete all pairs**.

To use only the web page, without the menu bar app:

```sh
uv run sonos_balance.py
```

## Files

| File | Purpose |
|---|---|
| `sonos_balance.py` | Engine: finds the speakers, calculates the curve, serves the web page and the API on port 8765 |
| `SonosBalance.swift` | Menu bar app |
| `build.sh` | Builds `SonosBalance.app` |
| `calibration.json` | Your saved pairs, oldest first |
| `backend.log` | Engine output when it is started by the app |

## Limits

- The curve applies only when you change the volume with this app. The Sonos app and the buttons on the speakers still change the group volume in the Sonos way. When the volumes change, the slider moves to the nearest balanced position.
- The Era 100 has larger volume steps than the Roam. One Era 100 step is approximately three Roam steps. Thus each slider step changes the Era 100 by one and the Roam by approximately three. The **− / +** buttons for each speaker still give the small steps that you use to calibrate.

## Problems

- **"Connecting to speakers…" does not go away**: read `backend.log`. Make sure that Local Network access is on and that the speakers are on Wi-Fi.
- **"The server on port 8765 is an old version"**: a different copy of `sonos_balance.py` is running. Stop it (Ctrl+C in its terminal), then quit and open the app again.
