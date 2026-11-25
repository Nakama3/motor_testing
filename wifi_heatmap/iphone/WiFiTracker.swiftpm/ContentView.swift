import ARKit
import SceneKit
import SwiftUI

struct ContentView: View {
    @StateObject private var streamer = PoseStreamer()
    @FocusState private var editingAddress: Bool

    var body: some View {
        ZStack(alignment: .bottom) {
            CameraPreview(session: streamer.session)
                .ignoresSafeArea()
                .onTapGesture { editingAddress = false }

            VStack(alignment: .leading, spacing: 12) {
                Text("WiFi Heatmap Tracker")
                    .font(.headline)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Laptop address (shown when server.py starts)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextField("192.168.1.23:8000", text: $streamer.serverAddress)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder)
                        .focused($editingAddress)
                        .disabled(streamer.streaming)
                }

                Button {
                    editingAddress = false
                    streamer.streaming ? streamer.stop() : streamer.start()
                } label: {
                    Text(streamer.streaming ? "Stop tracking" : "Start tracking")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(streamer.streaming ? .red : .blue)
                .controlSize(.large)

                statusRow(ok: streamer.trackingOK, text: streamer.trackingText, icon: "location.viewfinder")
                if !streamer.connectionText.isEmpty {
                    statusRow(ok: streamer.connected, text: streamer.connectionText, icon: "laptopcomputer")
                }
                if streamer.streaming {
                    Text(String(format: "x %.2f   y %.2f   z %.2f m   ·   %d sent",
                                streamer.position.x, streamer.position.y, streamer.position.z, streamer.sent))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                Text("Keep the camera pointing ahead as you walk, not at the floor or ceiling.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
            .padding()
        }
    }

    private func statusRow(ok: Bool, text: String, icon: String) -> some View {
        Label {
            Text(text).font(.subheadline)
        } icon: {
            Image(systemName: ok ? "checkmark.circle.fill" : icon)
                .foregroundStyle(ok ? .green : .orange)
        }
    }
}

/// Shows the camera feed with ARKit's feature points, so you can see that tracking works.
struct CameraPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView()
        view.session = session
        view.scene = SCNScene()
        view.automaticallyUpdatesLighting = false
        view.debugOptions = [.showFeaturePoints]
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}
