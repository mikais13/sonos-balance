# Sonos Balance

A small menu bar app for balancing the volumes of my Sonos speakers.
I have a Sonos Roam and a Sonos Era 100 which I like to pair together when at my desk but struggle to keep them at a similar volume and I find other apps not the best at this (i.e. the slider in the Sonos app or Spotify connect).
This app lets me calibrate the two speakers at a few different volumes, then it calculates a smooth curve that keeps them balanced at every slider position.

This project is not affiliated with or endorsed by Sonos.

## How it works

1. You set the two speakers so that they sound equally loud, then save the pair.
2. The app fits one smooth curve through your newest 50 saved pairs. The curve follows the pairs on average and does not go through each pair exactly.
3. Each slider step moves the louder speaker (the speaker with the lower volume number) by exactly one step, and sets the other speaker from the curve. Neither speaker gets quieter when you move the slider up.
4. Above your loudest pair, the same curve continues. The slider stops at the last step that keeps all speakers at 100 or below. Thus you do not have to calibrate at high volume, but one pair near the top makes that part of the curve more accurate.

## Requirements

- macOS 14 or later on Apple silicon
- [uv](https://docs.astral.sh/uv/)
- Xcode or the Xcode Command Line Tools (to build the app)
- This computer and the speakers on the same network (speakers must be paired via Wi-Fi not Bluetooth)

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

The app starts the Python engine (`sonos_balance.py`) and stops it when you quit.

## Web page

While the app is open, you can also use http://localhost:8765. The web page has the same controls, a list of the saved pairs with a **×** button to delete a pair, and **Delete all pairs**.

To use only the web page, without the menu bar app:

```sh
uv run sonos_balance.py
```

## Files

| File                 | Purpose                                                                                                                     |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `sonos_balance.py`   | Engine: finds the speakers, calculates the curve, serves the web page and the API on port 8765                              |
| `page.html`          | Web page, read by the engine for each request                                                                               |
| `SonosBalance.swift` | Menu bar app                                                                                                                |
| `build.sh`           | Builds `SonosBalance.app`                                                                                                   |
| `calibration.db`     | SQLite database with your saved pairs                                                                                       |
| `backend.log`        | Engine output when it is started by the app                                                                                 |

## Limits

- The curve applies only when you change the volume with this app. The Sonos app and the buttons on the speakers still change the group volume in the Sonos way. When the volumes change, the slider moves to the nearest balanced position.
- The app and the web page poll the speaker volumes every 3 seconds, and the menu also refreshes each time it opens. A change made on a speaker or in the Sonos app can take up to 3 seconds to show.
- Different Sonos speakers get louder at different rates. The app learns this only from your saved pairs, so the balance is as good as those pairs. This may not be perfect, but it is better than the Sonos app which does not take this into account at all.

## Problems

- **"Connecting to speakers…" does not go away**: read `backend.log`. Make sure that Local Network access is on and that the speakers are on Wi-Fi.
- **"The server on port 8765 is an old version"**: a different copy of `sonos_balance.py` is running. Stop it (Ctrl+C in its terminal), then quit and open the app again.
