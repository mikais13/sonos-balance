// Menu bar front end for sonos_balance.py. The app starts the Python backend at launch,
// stops it at quit, and talks to it over http://127.0.0.1:8765.

import AppKit
import SwiftUI

let backendURL = URL(string: "http://127.0.0.1:8765")!

struct SpeakerState: Decodable {
    let name: String
    let volume: Int
}

struct BalanceState: Decodable {
    let position: Int
    let maxPosition: Int
    let pairs: [[String: Int]]
    let maxSavedPairs: Int
    let speakers: [SpeakerState]
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var backendProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let info = Bundle.main.infoDictionary!
        let scriptPath = info["BackendScriptPath"] as! String
        let uvPath = info["UvPath"] as! String
        let logPath = URL(fileURLWithPath: scriptPath).deletingLastPathComponent().appendingPathComponent("backend.log").path
        FileManager.default.createFile(atPath: logPath, contents: nil)
        let logHandle = FileHandle(forWritingAtPath: logPath)!

        let process = Process()
        process.executableURL = URL(fileURLWithPath: uvPath)
        process.arguments = ["run", "--quiet", scriptPath]
        process.environment = ProcessInfo.processInfo.environment.merging(["PYTHONUNBUFFERED": "1"]) { $1 }
        process.standardOutput = logHandle
        process.standardError = logHandle
        do {
            try process.run()
            backendProcess = process
        } catch {
            logHandle.write("Could not start backend: \(error)\n".data(using: .utf8)!)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        backendProcess?.terminate()
        backendProcess?.waitUntilExit()
    }
}

@MainActor
final class BalanceModel: ObservableObject {
    @Published var state: BalanceState?
    @Published var sliderPosition: Double = 0
    @Published var errorMessage: String?

    private var positionRequestInFlight = false
    private var pendingPosition: Int?

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    func refresh() async {
        guard !positionRequestInFlight else { return }
        await request(path: "/api/state", body: nil)
    }

    // Send at most one position request at a time; keep only the newest value while waiting.
    func sendPosition(_ position: Int) {
        if positionRequestInFlight {
            pendingPosition = position
            return
        }
        positionRequestInFlight = true
        Task {
            await request(path: "/api/position", body: ["position": position])
            positionRequestInFlight = false
            if let next = pendingPosition {
                pendingPosition = nil
                sendPosition(next)
            }
        }
    }

    func stepPosition(by step: Int) {
        guard let state else { return }
        let position = min(state.maxPosition, max(0, Int(sliderPosition) + step))
        sliderPosition = Double(position)
        sendPosition(position)
    }

    func nudge(_ speaker: SpeakerState, by step: Int) {
        let volume = min(100, max(0, speaker.volume + step))
        Task { await request(path: "/api/speaker", body: ["name": speaker.name, "volume": volume]) }
    }

    func savePair() {
        Task { await request(path: "/api/save-pair", body: [:]) }
    }

    private func request(path: String, body: [String: Any]?) async {
        var urlRequest = URLRequest(url: backendURL.appendingPathComponent(path))
        urlRequest.timeoutInterval = 5
        if let body {
            urlRequest.httpMethod = "POST"
            urlRequest.httpBody = try! JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, _) = try await URLSession.shared.data(for: urlRequest)
            let newState = try Self.decoder.decode(BalanceState.self, from: data)
            state = newState
            if !positionRequestInFlight || path == "/api/position" {
                sliderPosition = Double(newState.position)
            }
            errorMessage = nil
        } catch is DecodingError {
            errorMessage = "The server on port 8765 is an old version. Stop it and reopen this app."
        } catch {
            errorMessage = state == nil
                ? "Connecting to speakers…"
                : "Lost connection to the backend. See backend.log in the project folder."
        }
    }
}

struct BalanceView: View {
    @ObservedObject var model: BalanceModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sonos Balance").font(.headline)
            if let state = model.state {
                HStack {
                    Button("−") { model.stepPosition(by: -1) }
                    Image(systemName: "speaker.fill").foregroundStyle(.secondary)
                    Slider(
                        value: Binding(
                            get: { model.sliderPosition },
                            set: { newValue in
                                model.sliderPosition = newValue
                                model.sendPosition(Int(newValue))
                            }
                        ),
                        in: 0...Double(max(state.maxPosition, 1)),
                        step: 1
                    )
                    Image(systemName: "speaker.wave.3.fill").foregroundStyle(.secondary)
                    Button("+") { model.stepPosition(by: 1) }
                }
                Divider()
                ForEach(state.speakers, id: \.name) { speaker in
                    HStack {
                        Text(speaker.name).lineLimit(1)
                        Spacer()
                        Button("−") { model.nudge(speaker, by: -1) }
                        Text("\(speaker.volume)").monospacedDigit().frame(width: 28, alignment: .trailing)
                        Button("+") { model.nudge(speaker, by: 1) }
                    }
                }
                Button { model.savePair() } label: {
                    Text("Save pair").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                Text("Curve uses \(state.pairs.count) of the last \(state.maxSavedPairs) saved pairs.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let errorMessage = model.errorMessage {
                Text(errorMessage).font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            Button("Quit Sonos Balance") { NSApp.terminate(nil) }
        }
        .padding()
        .frame(width: 300)
        .task {
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(model.state == nil ? 1 : 3))
            }
        }
    }
}

@main
struct SonosBalanceApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = BalanceModel()

    var body: some Scene {
        MenuBarExtra("Sonos Balance", systemImage: "hifispeaker.2.fill") {
            BalanceView(model: model)
        }
        .menuBarExtraStyle(.window)
    }
}
