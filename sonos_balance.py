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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import linear_regression, mean

import soco

CALIBRATION_PATH = Path(__file__).with_name("calibration.json")
PORT = 8765
MAX_SAVED_PAIRS = 50


def discover_speakers_by_name() -> dict[str, soco.SoCo]:
    """Search until speakers answer. macOS blocks the search until Local Network access is allowed."""
    while not (speakers := soco.discover(timeout=8, allow_network_scan=True)):
        print("No Sonos speakers found. Check the network and macOS Local Network access. Trying again in 5 s.")
        time.sleep(5)
    return {speaker.player_name: speaker for speaker in speakers}


def load_pairs() -> list[dict[str, int]]:
    """Saved pairs, oldest first."""
    if CALIBRATION_PATH.exists():
        return json.loads(CALIBRATION_PATH.read_text())["pairs"]
    return []


def save_pairs(pairs: list[dict[str, int]]) -> None:
    CALIBRATION_PATH.write_text(json.dumps({"pairs": pairs}, indent=2, ensure_ascii=False))


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
  input[type=range] { flex: 1; accent-color: var(--accent); }
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
    <div class="row">
      <button id="volume-down">−</button>
      <input type="range" id="volume" min="0" step="1">
      <button id="volume-up">+</button>
    </div>
    <div class="hint">Use ← → keys for single steps. The slider stops where the first speaker reaches 100.</div>
  </section>
  <section>
    <div id="speakers"></div>
    <div class="row"><button class="primary" id="save">Save pair</button><button id="reset">Delete all pairs</button></div>
    <p class="hint">To calibrate: nudge each speaker until both sound equally loud, then save the pair. The curve is a best fit through your newest saved pairs. Louder levels continue the ratio of your loudest pair.</p>
  </section>
  <section>
    <h2 id="pairs-heading">Saved pairs</h2>
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
  document.getElementById("pairs-heading").textContent = `Saved pairs (${state.pairs.length} of ${state.max_saved_pairs}, oldest first)`;
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
function stepPosition(step) {
  volumeSlider.value = Number(volumeSlider.value) + step;
  sendPosition(Number(volumeSlider.value));
}
document.getElementById("volume-down").addEventListener("click", () => stepPosition(-1));
document.getElementById("volume-up").addEventListener("click", () => stepPosition(1));
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
