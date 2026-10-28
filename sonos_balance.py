# /// script
# requires-python = ">=3.11"
# dependencies = ["soco>=0.30"]
# ///
"""One master volume for grouped Sonos speakers that get loud at different rates.

Each speaker gets its own volume from a calibration curve. You build the curve by ear:
set the master level, adjust each speaker until they sound equal, then save the match.
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


def load_calibration(speakers_by_name: dict[str, soco.SoCo]) -> dict:
    if CALIBRATION_PATH.exists():
        return json.loads(CALIBRATION_PATH.read_text())
    # First run: treat the current volumes as a matched pair, so the curve starts from what you hear now.
    current_volumes = {name: speaker.volume for name, speaker in speakers_by_name.items()}
    seed_master = max(current_volumes.values()) or 30
    return {"master": seed_master, "points": [{"master": seed_master, "volumes": current_volumes}]}


def save_calibration(calibration: dict) -> None:
    CALIBRATION_PATH.write_text(json.dumps(calibration, indent=2, ensure_ascii=False))


def volume_for_speaker(points: list[dict], speaker_name: str, master: int) -> int:
    """Linear interpolation over the saved points, with (0, 0) as an implicit point.

    Above the highest point, the last segment is extended and the result is clamped to 100.
    """
    curve = [(0, 0)] + sorted(
        (point["master"], point["volumes"][speaker_name])
        for point in points
        if speaker_name in point["volumes"] and point["master"] > 0
    )
    if len(curve) == 1:
        return master
    for (low_master, low_volume), (high_master, high_volume) in zip(curve, curve[1:]):
        if master <= high_master:
            break
    fraction = (master - low_master) / (high_master - low_master)
    volume = low_volume + fraction * (high_volume - low_volume)
    return max(0, min(100, round(volume)))


class Handler(BaseHTTPRequestHandler):
    speakers_by_name: dict[str, soco.SoCo]
    calibration: dict

    def do_GET(self):
        if self.path == "/":
            self.send_body(PAGE_HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self.send_json(self.state())
        else:
            self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/master":
            self.set_master(int(body["master"]))
        elif self.path == "/api/speaker":
            self.speakers_by_name[body["name"]].volume = int(body["volume"])
        elif self.path == "/api/save-match":
            self.save_match()
        elif self.path == "/api/reset":
            self.calibration["points"] = []
            save_calibration(self.calibration)
        else:
            self.send_error(404)
            return
        self.send_json(self.state())

    def set_master(self, master: int) -> None:
        self.calibration["master"] = master
        for name, speaker in self.speakers_by_name.items():
            speaker.volume = volume_for_speaker(self.calibration["points"], name, master)
        save_calibration(self.calibration)

    def save_match(self) -> None:
        master = self.calibration["master"]
        current_volumes = {name: speaker.volume for name, speaker in self.speakers_by_name.items()}
        self.calibration["points"] = [p for p in self.calibration["points"] if p["master"] != master]
        self.calibration["points"].append({"master": master, "volumes": current_volumes})
        self.calibration["points"].sort(key=lambda point: point["master"])
        save_calibration(self.calibration)

    def state(self) -> dict:
        return {
            "master": self.calibration["master"],
            "points": self.calibration["points"],
            "speakers": [
                {"name": name, "volume": speaker.volume} for name, speaker in self.speakers_by_name.items()
            ],
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
  section { background: var(--card); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .row { display: flex; align-items: center; gap: 12px; }
  .row + .row { margin-top: 12px; }
  .label { flex: 1; }
  .value { width: 3ch; text-align: right; font-variant-numeric: tabular-nums; }
  input[type=range] { width: 100%; accent-color: var(--accent); }
  .master-value { font-size: 40px; font-weight: 600; font-variant-numeric: tabular-nums; }
  button { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--muted); background: transparent; color: var(--fg); cursor: pointer; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .hint, .points { color: var(--muted); font-size: 14px; }
</style></head>
<body><main>
  <h1>Sonos Balance</h1>
  <section>
    <div class="master-value" id="master-value">–</div>
    <input type="range" id="master" min="0" max="100">
    <div class="hint">Master volume. Use ← → keys for single steps.</div>
  </section>
  <section>
    <div id="speakers"></div>
    <div class="row"><button class="primary" id="save">Save match at this level</button><button id="reset">Reset curve</button></div>
    <p class="hint">To calibrate: set the master level, nudge each speaker until both sound equally loud, then save. Save matches at a low, a middle and a high level for a good curve.</p>
    <div class="points" id="points"></div>
  </section>
</main>
<script>
const masterSlider = document.getElementById("master");
let masterRequestInFlight = false, pendingMaster = null;

async function post(path, body) {
  const response = await fetch(path, { method: "POST", body: JSON.stringify(body || {}) });
  render(await response.json());
}

function render(state) {
  if (!masterRequestInFlight) masterSlider.value = state.master;
  document.getElementById("master-value").textContent = masterSlider.value;
  document.getElementById("speakers").innerHTML = state.speakers.map(s => `
    <div class="row">
      <span class="label">${s.name}</span>
      <button data-name="${s.name}" data-step="-1">−</button>
      <span class="value">${s.volume}</span>
      <button data-name="${s.name}" data-step="1">+</button>
    </div>`).join("");
  document.getElementById("points").textContent = state.points.length
    ? "Saved matches: " + state.points.map(p => `master ${p.master} → ` + Object.entries(p.volumes).map(([n, v]) => `${n} ${v}`).join(", ")).join(" · ")
    : "No saved matches. Both speakers follow the master directly.";
  window.currentSpeakers = state.speakers;
}

// Send at most one master request at a time; keep only the newest value while waiting.
async function sendMaster(value) {
  if (masterRequestInFlight) { pendingMaster = value; return; }
  masterRequestInFlight = true;
  await post("/api/master", { master: value });
  masterRequestInFlight = false;
  if (pendingMaster !== null) { const next = pendingMaster; pendingMaster = null; sendMaster(next); }
}

masterSlider.addEventListener("input", () => {
  document.getElementById("master-value").textContent = masterSlider.value;
  sendMaster(Number(masterSlider.value));
});
document.getElementById("speakers").addEventListener("click", event => {
  const button = event.target.closest("button[data-name]");
  if (!button) return;
  const speaker = window.currentSpeakers.find(s => s.name === button.dataset.name);
  post("/api/speaker", { name: speaker.name, volume: Math.max(0, Math.min(100, speaker.volume + Number(button.dataset.step))) });
});
document.getElementById("save").addEventListener("click", () => post("/api/save-match"));
document.getElementById("reset").addEventListener("click", () => post("/api/reset"));

async function refresh() { if (!masterRequestInFlight) render(await (await fetch("/api/state")).json()); }
refresh();
setInterval(refresh, 3000);
</script>
</body></html>
"""


def main() -> None:
    Handler.speakers_by_name = discover_speakers_by_name()
    Handler.calibration = load_calibration(Handler.speakers_by_name)
    save_calibration(Handler.calibration)
    print("Speakers:", ", ".join(Handler.speakers_by_name))
    print(f"Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
