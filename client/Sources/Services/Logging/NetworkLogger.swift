import Foundation
import Network

/// Network logger that sends logs to a remote server for real-time debugging
@MainActor
final class NetworkLogger: ObservableObject {
    static let shared = NetworkLogger()
    
    @Published private(set) var isEnabled = false
    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "NetworkLogger", qos: .utility)
    
    private init() {}
    
    func startNetworkLogging(host: String, port: UInt16) {
        guard !isEnabled else { return }
        
        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port) ?? 12345
        )
        
        connection = NWConnection(to: endpoint, using: .tcp)
        
        connection?.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async {
                switch state {
                case .ready:
                    self?.isEnabled = true
                    self?.sendLog("🌐 Network logging connected to \(host):\(port)")
                    print("✅ Network logging enabled - sending to \(host):\(port)")
                case .failed(let error):
                    print("❌ Network logging failed: \(error)")
                    self?.isEnabled = false
                case .cancelled:
                    print("🛑 Network logging cancelled")
                    self?.isEnabled = false
                default:
                    break
                }
            }
        }
        
        connection?.start(queue: queue)
    }
    
    func stopNetworkLogging() {
        sendLog("🛑 Network logging disconnected")
        connection?.cancel()
        connection = nil
        isEnabled = false
    }
    
    func sendLog(_ message: String) {
        guard isEnabled, let connection = connection else { return }
        
        let timestamp = DateFormatter.logFormatter.string(from: Date())
        let logEntry = "[\(timestamp)] \(message)\n"
        
        guard let data = logEntry.data(using: .utf8) else { return }
        
        connection.send(content: data, completion: .contentProcessed { error in
            if let error = error {
                print("❌ Failed to send log: \(error)")
            }
        })
    }
}

extension DateFormatter {
    static let logFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return formatter
    }()
} 