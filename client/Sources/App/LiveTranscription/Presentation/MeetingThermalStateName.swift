import Foundation

/// Maps macOS thermal pressure to the stable names the Notetaker web client reports to the resource advisor.
enum MeetingThermalStateName {
    static func name(for state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal:
            return "nominal"
        case .fair:
            return "fair"
        case .serious:
            return "serious"
        case .critical:
            return "critical"
        @unknown default:
            return "nominal"
        }
    }
}
