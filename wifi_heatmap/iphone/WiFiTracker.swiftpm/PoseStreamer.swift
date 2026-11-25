import ARKit
import Foundation
import UIKit

/// Runs ARKit world tracking and sends the phone's position to the laptop
/// (POST http://<laptop>/api/pose) five times a second.
///
/// ARKit coordinates are in meters, y points up (gravity aligned), and the
/// origin is wherever the phone was when tracking started. The web app turns
/// them into house coordinates with a two-point calibration.
final class PoseStreamer: ObservableObject {
    @Published var serverAddress: String = UserDefaults.standard.string(forKey: "server") ?? ""
    @Published private(set) var streaming = false
    @Published private(set) var trackingText = "Not started"
    @Published private(set) var trackingOK = false
    @Published private(set) var connectionText = ""
    @Published private(set) var connected = false
    @Published private(set) var sent = 0
    @Published private(set) var position = SIMD3<Float>(repeating: 0)

    let session = ARSession()
    private var timer: Timer?
    private var inFlight = false
    private var sessionID = UUID().uuidString
    private let http: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 2
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    private var endpoint: URL? {
        var s = serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }
        if !s.lowercased().hasPrefix("http") { s = "http://" + s }
        if s.hasSuffix("/") { s.removeLast() }
        return URL(string: s + "/api/pose")
    }

    func start() {
        guard ARWorldTrackingConfiguration.isSupported else {
            trackingText = "ARKit world tracking isn't supported on this device"
            return
        }
        guard endpoint != nil else {
            connectionText = "Enter the laptop address first, e.g. 192.168.1.23:8000"
            return
        }
        UserDefaults.standard.set(serverAddress, forKey: "server")
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
        // A new tracking session has a new origin, so the laptop must recalibrate.
        sessionID = UUID().uuidString
        sent = 0
        streaming = true
        UIApplication.shared.isIdleTimerDisabled = true
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            self?.tick()
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        session.pause()
        streaming = false
        trackingText = "Stopped"
        trackingOK = false
        UIApplication.shared.isIdleTimerDisabled = false
    }

    private func tick() {
        guard let frame = session.currentFrame else { return }
        let t = frame.camera.transform
        let p = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let (ok, text) = Self.describe(frame.camera.trackingState)
        position = p
        trackingOK = ok
        trackingText = text
        send(p, ok: ok, state: text)
    }

    private func send(_ p: SIMD3<Float>, ok: Bool, state: String) {
        guard !inFlight, let url = endpoint else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "x": Double(p.x), "y": Double(p.y), "z": Double(p.z),
            "ok": ok, "state": state, "session": sessionID,
        ]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        inFlight = true
        http.dataTask(with: req) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.inFlight = false
                if let error {
                    self.connected = false
                    self.connectionText = "Can't reach the laptop: \(error.localizedDescription)"
                } else if let h = response as? HTTPURLResponse, h.statusCode == 200 {
                    self.connected = true
                    self.sent += 1
                    self.connectionText = "Connected to laptop"
                } else {
                    self.connected = false
                    self.connectionText = "Laptop answered with an error. Is it running server.py?"
                }
            }
        }.resume()
    }

    static func describe(_ state: ARCamera.TrackingState) -> (Bool, String) {
        switch state {
        case .normal:
            return (true, "Tracking OK")
        case .notAvailable:
            return (false, "Tracking not available")
        case .limited(let reason):
            switch reason {
            case .initializing:
                return (false, "Starting up: move the phone slowly")
            case .excessiveMotion:
                return (false, "Moving too fast: slow down")
            case .insufficientFeatures:
                return (false, "Not enough detail: point at furniture or walls, turn on lights")
            case .relocalizing:
                return (false, "Relocalizing")
            @unknown default:
                return (false, "Tracking limited")
            }
        }
    }
}
