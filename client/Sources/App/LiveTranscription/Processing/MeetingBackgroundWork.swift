import Foundation

struct MeetingBackgroundWorkOwner: Equatable, Sendable {
    let displayID: String
    let representativeMeetingID: String
    let selectedHistoryMeetingID: String?
}

struct MeetingPostProcessingWorkRequest: Equatable, Sendable {
    let owner: MeetingBackgroundWorkOwner
    let meetingIDs: [String]
    let operation: String
    let model: String
    let startedAutomatically: Bool
    let autoAnalyzeOnComplete: Bool
    let autoAnalyzeModes: [String]
    let autoAnalyzeCustomInstructions: String
    let autoAnalyzeTiming: String
}

struct MeetingAnalysisWorkRequest: Equatable, Sendable {
    let owner: MeetingBackgroundWorkOwner
    let modelID: String?
    let modeValues: [String]
    let customInstructions: String
    let startedAutomatically: Bool
}

enum MeetingBackgroundWorkRequest: Equatable, Sendable {
    case postProcessing(MeetingPostProcessingWorkRequest)
    case analysis(MeetingAnalysisWorkRequest)

    var owner: MeetingBackgroundWorkOwner {
        switch self {
        case .postProcessing(let request):
            return request.owner
        case .analysis(let request):
            return request.owner
        }
    }
}

@MainActor
final class MeetingBackgroundWorkCoordinator {
    private(set) var active: MeetingBackgroundWorkRequest?
    private(set) var pending: [MeetingBackgroundWorkRequest] = []

    var hasActiveWork: Bool {
        active != nil
    }

    func enqueue(_ request: MeetingBackgroundWorkRequest) {
        pending.append(request)
    }

    func beginNext() -> MeetingBackgroundWorkRequest? {
        guard active == nil, !pending.isEmpty else { return nil }
        let request = pending.removeFirst()
        active = request
        return request
    }

    func finishActive(ownerID: String) {
        guard active?.owner.displayID == ownerID else { return }
        active = nil
    }
}
