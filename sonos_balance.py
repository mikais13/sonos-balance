# /// script
# requires-python = ">=3.11"
# dependencies = ["soco>=0.30"]
# ///
"""One volume slider for grouped Sonos speakers that get loud at different rates.

You save pairs of volumes that sound equally loud. The slider walks along a curve fitted
through the newest saved pairs, one step of the louder speaker at a time, so the speakers
stay balanced at every position.
"""

import json
import math
import sqlite3
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import linear_regression, mean

import soco

DATABASE_PATH = Path(__file__).with_name("calibration.db")
PAGE_PATH = Path(__file__).with_name("page.html")
PORT = 8765
MAX_SAVED_PAIRS = 50
ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}


def discover_speakers_by_name() -> dict[str, soco.SoCo]:
    """Search until speakers answer. macOS blocks the search until Local Network access is allowed."""
    while not (speakers := soco.discover(timeout=8, allow_network_scan=True)):
        print("No Sonos speakers found. Check the network and macOS Local Network access. Trying again in 5 s.")
        time.sleep(5)
    return {speaker.player_name: speaker for speaker in speakers}


def open_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS saved_pair_volumes (
            pair_index INTEGER NOT NULL,
            speaker_name TEXT NOT NULL,
            volume INTEGER NOT NULL,
            PRIMARY KEY (pair_index, speaker_name)
        )"""
    )
    return connection


def load_pairs() -> list[dict[str, int]]:
    """Saved pairs, oldest first."""
    with closing(open_database()) as connection:
        rows = connection.execute(
            "SELECT pair_index, speaker_name, volume FROM saved_pair_volumes ORDER BY pair_index"
        ).fetchall()
    volumes_by_pair_index: dict[int, dict[str, int]] = {}
    for pair_index, speaker_name, volume in rows:
        volumes_by_pair_index.setdefault(pair_index, {})[speaker_name] = volume
    return list(volumes_by_pair_index.values())


def save_pairs(pairs: list[dict[str, int]]) -> None:
    """Replace all saved pairs in one transaction."""
    rows = [
        (pair_index, speaker_name, volume)
        for pair_index, pair in enumerate(pairs)
        for speaker_name, volume in pair.items()
    ]
    with closing(open_database()) as connection, connection:
        connection.execute("DELETE FROM saved_pair_volumes")
        connection.executemany("INSERT INTO saved_pair_volumes VALUES (?, ?, ?)", rows)


def fit_power_curve(reference_volumes: list[int], volumes: list[int]) -> tuple[float, float]:
    """Scale and exponent of volume = scale * reference_volume ** exponent, a least squares fit on log volumes.

    A single reference volume cannot show a bend, so that case keeps a constant ratio. The exponent
    is never negative, so a volume never drops when the reference volume goes up.
    """
    log_reference_volumes = [math.log(volume) for volume in reference_volumes]
    log_volumes = [math.log(volume) for volume in volumes]
    exponent = 1.0
    if len(set(reference_volumes)) > 1:
        exponent = max(linear_regression(log_reference_volumes, log_volumes).slope, 0.0)
    return math.exp(mean(log_volumes) - exponent * mean(log_reference_volumes)), exponent


def build_volume_steps(pairs: list[dict[str, int]], speaker_names: list[str]) -> list[dict[str, int]]:
    """Every slider position, one for each volume of the louder speaker.

    The louder speaker has the lowest saved volumes, so its steps are the coarsest. A smooth curve
    gives each other speaker its volume, so saved pairs set the curve on average and no single
    pair pulls it. The positions stop before any speaker would go above 100.
    """
    audible_pairs = [pair for pair in pairs if all(pair[name] for name in speaker_names)]
    if not audible_pairs:
        return [{name: volume for name in speaker_names} for volume in range(101)]
    louder_speaker = min(speaker_names, key=lambda name: sum(pair[name] for pair in audible_pairs))
    louder_speaker_volumes = [pair[louder_speaker] for pair in audible_pairs]
    curves_by_name = {
        name: fit_power_curve(louder_speaker_volumes, [pair[name] for pair in audible_pairs]) for name in speaker_names
    }
    steps = [{name: 0 for name in speaker_names}]
    for louder_volume in range(1, 101):
        volumes = {
            name: round(scale * louder_volume**exponent) for name, (scale, exponent) in curves_by_name.items()
        }
        if max(volumes.values()) > 100:
            break
        steps.append(volumes)
    return steps


def nearest_step_index(steps: list[dict[str, int]], volumes: dict[str, int]) -> int:
    return min(
        range(len(steps)),
        key=lambda index: sum(abs(steps[index][name] - volumes[name]) for name in volumes),
    )


class Handler(BaseHTTPRequestHandler):
    speakers_by_name: dict[str, soco.SoCo]
    pairs: list[dict[str, int]]

    def do_GET(self):
        if self.path == "/":
            self.send_body(PAGE_PATH.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self.send_json(self.state())
        else:
            self.send_error(404)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            # Browsers send Origin on every POST, so other websites stop here. The menu bar app sends none.
            self.send_error(403)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/position":
            self.set_volumes(self.volume_steps()[int(body["position"])])
        elif self.path == "/api/speaker":
            self.speakers_by_name[body["name"]].volume = int(body["volume"])
        elif self.path == "/api/save-pair":
            Handler.pairs = (self.pairs + [self.current_volumes()])[-MAX_SAVED_PAIRS:]
            save_pairs(self.pairs)
        elif self.path == "/api/delete-pair":
            del self.pairs[int(body["index"])]
            save_pairs(self.pairs)
        elif self.path == "/api/reset":
            Handler.pairs = []
            save_pairs(self.pairs)
        else:
            self.send_error(404)
            return
        self.send_json(self.state())

    def volume_steps(self) -> list[dict[str, int]]:
        return build_volume_steps(self.pairs, list(self.speakers_by_name))

    def current_volumes(self) -> dict[str, int]:
        return {name: speaker.volume for name, speaker in self.speakers_by_name.items()}

    def set_volumes(self, volumes: dict[str, int]) -> None:
        for name, volume in volumes.items():
            self.speakers_by_name[name].volume = volume

    def state(self) -> dict:
        steps = self.volume_steps()
        current_volumes = self.current_volumes()
        return {
            "position": nearest_step_index(steps, current_volumes),
            "max_position": len(steps) - 1,
            "pairs": self.pairs,
            "max_saved_pairs": MAX_SAVED_PAIRS,
            "speakers": [{"name": name, "volume": volume} for name, volume in current_volumes.items()],
        }

    def send_json(self, data: dict) -> None:
        self.send_body(json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def send_body(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main() -> None:
    Handler.speakers_by_name = discover_speakers_by_name()
    Handler.pairs = load_pairs()
    print("Speakers:", ", ".join(Handler.speakers_by_name))
    print(f"Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
