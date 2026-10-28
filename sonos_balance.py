# /// script
# requires-python = ">=3.11"
# dependencies = ["soco>=0.30"]
# ///
"""One volume slider for grouped Sonos speakers that get loud at different rates.

You save pairs of volumes that sound equally loud. The slider walks along those pairs,
one volume step at a time, so the speakers stay balanced at every position.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import soco

CALIBRATION_PATH = Path(__file__).with_name("calibration.json")
PORT = 8765


def discover_speakers_by_name() -> dict[str, soco.SoCo]:
    speakers = soco.discover(timeout=8, allow_network_scan=True)
    if not speakers:
        sys.exit("No Sonos speakers found. Is this computer on the same network as the speakers?")
    return {speaker.player_name: speaker for speaker in speakers}


def load_pairs() -> list[dict[str, int]]:
    if CALIBRATION_PATH.exists():
        return json.loads(CALIBRATION_PATH.read_text())["pairs"]
    return []


def save_pairs(pairs: list[dict[str, int]]) -> None:
    CALIBRATION_PATH.write_text(json.dumps({"pairs": pairs}, indent=2, ensure_ascii=False))


def is_quieter_or_equal(pair: dict[str, int], other: dict[str, int]) -> bool:
    return all(pair[name] <= other[name] for name in pair)


def add_pair(pairs: list[dict[str, int]], new_pair: dict[str, int]) -> list[dict[str, int]]:
    """Add a pair and drop the old pairs that contradict it.

    A pair contradicts the new one when one speaker is louder and the other is quieter,
    because then the slider could not go up on both speakers at once.
    """
    consistent_pairs = [
        pair
        for pair in pairs
        if pair != new_pair and (is_quieter_or_equal(pair, new_pair) or is_quieter_or_equal(new_pair, pair))
    ]
    return sorted(consistent_pairs + [new_pair], key=lambda pair: sum(pair.values()))


def build_volume_steps(pairs: list[dict[str, int]], speaker_names: list[str]) -> list[dict[str, int]]:
    """Every slider position, from silent to the point where the first speaker reaches 100.

    Between two pairs, the speaker that changes most moves one volume step per slider step
    and the other speakers follow in proportion. Above the loudest pair, the volume ratio
    of that pair continues.
    """
    if not pairs:
        return [{name: volume for name in speaker_names} for volume in range(101)]
    loudest_pair = pairs[-1]
    scale_to_max = 100 / max(loudest_pair.values())
    top_pair = {name: round(loudest_pair[name] * scale_to_max) for name in speaker_names}
    anchors = [{name: 0 for name in speaker_names}] + pairs + [top_pair]
    steps = [anchors[0]]
    for start, end in zip(anchors, anchors[1:]):
        step_count = max(abs(end[name] - start[name]) for name in speaker_names)
        for step in range(1, step_count + 1):
            fraction = step / step_count
            steps.append({name: round(start[name] + fraction * (end[name] - start[name])) for name in speaker_names})
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
            self.send_body(PAGE_HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self.send_json(self.state())
        else:
            self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/position":
            self.set_volumes(self.volume_steps()[int(body["position"])])
        elif self.path == "/api/speaker":
            self.speakers_by_name[body["name"]].volume = int(body["volume"])
        elif self.path == "/api/save-pair":
            Handler.pairs = add_pair(self.pairs, self.current_volumes())
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


PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sonos Balance</title>
<style>
  :root { color-scheme: light dark; --bg: #f6f5f2; --fg: #1d1d1b; --muted: #77756f; --card: #fff; --accent: #c2410c; }
  @media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ecebe7; --muted: #9a978f; --card: #222220; --accent: #fb923c; } }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.4 -apple-system, system-ui, sans-serif; }
  main { max-width: 520px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 20px; margin: 0 0 16px; }
  h2 { font-size: 15px; margin: 0 0 8px; }
  section { background: var(--card); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .row { display: flex; align-items: center; gap: 12px; }
  .row + .row { margin-top: 12px; }
  .label { flex: 1; }
  .value { width: 3ch; text-align: right; font-variant-numeric: tabular-nums; }
  input[type=range] { width: 100%; accent-color: var(--accent); }
  button { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--muted); background: transparent; color: var(--fg); cursor: pointer; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .hint { color: var(--muted); font-size: 14px; }
  ul { list-style: none; margin: 0; padding: 0; font-variant-numeric: tabular-nums; }
  li { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; }
  li button { padding: 2px 8px; }
</style></head>
<body><main>
  <h1>Sonos Balance</h1>
  <section>
    <input type="range" id="volume" min="0" step="1">
    <div class="hint">Use ← → keys for single steps. The slider stops where the first speaker reaches 100.</div>
  </section>
  <section>
    <div id="speakers"></div>
    <div class="row"><button class="primary" id="save">Save pair</button><button id="reset">Delete all pairs</button></div>
    <p class="hint">To calibrate: nudge each speaker until both sound equally loud, then save the pair. Louder levels continue the ratio of your loudest pair.</p>
  </section>
  <section>
    <h2>Saved pairs</h2>
    <ul id="pairs"></ul>
  </section>
</main>
<script>
const volumeSlider = document.getElementById("volume");
let positionRequestInFlight = false, pendingPosition = null;

async function post(path, body) {
  const response = await fetch(path, { method: "POST", body: JSON.stringify(body || {}) });
  render(await response.json());
}

function render(state) {
  volumeSlider.max = state.max_position;
  if (!positionRequestInFlight) volumeSlider.value = state.position;
  document.getElementById("speakers").innerHTML = state.speakers.map(s => `
    <div class="row">
      <span class="label">${s.name}</span>
      <button data-name="${s.name}" data-step="-1">−</button>
      <span class="value">${s.volume}</span>
      <button data-name="${s.name}" data-step="1">+</button>
    </div>`).join("");
  document.getElementById("pairs").innerHTML = state.pairs.length
    ? state.pairs.map((pair, index) => `
        <li><span>${Object.entries(pair).map(([name, volume]) => `${name} ${volume}`).join(" · ")}</span>
        <button data-delete="${index}">×</button></li>`).join("")
    : `<li class="hint">No pairs yet. Both speakers use the same volume.</li>`;
  window.currentSpeakers = state.speakers;
}

// Send at most one position request at a time; keep only the newest value while waiting.
async function sendPosition(position) {
  if (positionRequestInFlight) { pendingPosition = position; return; }
  positionRequestInFlight = true;
  await post("/api/position", { position });
  positionRequestInFlight = false;
  if (pendingPosition !== null) { const next = pendingPosition; pendingPosition = null; sendPosition(next); }
}

volumeSlider.addEventListener("input", () => sendPosition(Number(volumeSlider.value)));
document.getElementById("speakers").addEventListener("click", event => {
  const button = event.target.closest("button[data-name]");
  if (!button) return;
  const speaker = window.currentSpeakers.find(s => s.name === button.dataset.name);
  post("/api/speaker", { name: speaker.name, volume: Math.max(0, Math.min(100, speaker.volume + Number(button.dataset.step))) });
});
document.getElementById("pairs").addEventListener("click", event => {
  const button = event.target.closest("button[data-delete]");
  if (button) post("/api/delete-pair", { index: Number(button.dataset.delete) });
});
document.getElementById("save").addEventListener("click", () => post("/api/save-pair"));
document.getElementById("reset").addEventListener("click", () => post("/api/reset"));

async function refresh() { if (!positionRequestInFlight) render(await (await fetch("/api/state")).json()); }
refresh();
setInterval(refresh, 3000);
</script>
</body></html>
"""


def main() -> None:
    Handler.speakers_by_name = discover_speakers_by_name()
    Handler.pairs = load_pairs()
    print("Speakers:", ", ".join(Handler.speakers_by_name))
    print(f"Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
