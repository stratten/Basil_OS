import SwiftUI

struct IOSPairingPanel: View {
    @State private var pairingResponse: IOSPairStartResponse?
    @State private var statusMessage: String = "Pairing is disabled until BASIL_IOS_PAIR_ENABLED is true on the backend."
    @State private var isLoading = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("iOS Pairing")
                .font(.title2.bold())

            Text(statusMessage)
                .foregroundStyle(.secondary)

            if let pairingResponse {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Pairing ID: \(pairingResponse.pairingId)")
                        .font(.system(.body, design: .monospaced))
                    Text("Secret: \(pairingResponse.secret)")
                        .font(.system(.body, design: .monospaced))
                    Text("Expires: \(pairingResponse.expiresAt)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding()
                .background(Color(NSColor.windowBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            Button(isLoading ? "Starting..." : "Start Pairing") {
                Task { await startPairing() }
            }
            .disabled(isLoading)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func startPairing() async {
        isLoading = true
        defer { isLoading = false }

        do {
            pairingResponse = try await APIClient.shared.startIOSPairing()
            statusMessage = "Scan or transfer this pairing payload to BasilMobile."
        } catch {
            statusMessage = "Unable to start iOS pairing: \(error.localizedDescription)"
        }
    }
}

#Preview {
    IOSPairingPanel()
}

