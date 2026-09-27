import AppKit
import Combine
import Foundation

/// Identifies one attached WebKit presentation of the single live meeting
/// session. Detaching a token never tears down the shared
/// `LiveTranscriptionViewModel` unless it was the last attached presentation.
struct MeetingPresentationToken: Hashable {
    let id: UUID
}

struct MeetingSessionInitializationOperations {
    let loadMeetingHistory: (LiveTranscriptionViewModel) async -> Void
    let initialize: (LiveTranscriptionViewModel) async -> Void
    let loadAvailableModels: (LiveTranscriptionViewModel) async -> Void
    let loadAnalysisModels: (LiveTranscriptionViewModel) async -> Void

    static let live = MeetingSessionInitializationOperations(
        loadMeetingHistory: { await $0.loadMeetingHistory() },
        initialize: { await $0.initialize() },
        loadAvailableModels: { await $0.loadAvailableModels() },
        loadAnalysisModels: { await $0.loadAnalysisModels() }
    )
}

/// Owns the single live `LiveTranscriptionViewModel` for the process and every
/// attached WebKit presentation (the main Meeting Assistant and analysis-result
/// windows). This is the only type allowed to create a
/// `LiveTranscriptionViewModel` or call its lifecycle/cleanup methods.
/// Individual window controllers attach/detach a token and never construct or
/// tear down the model themselves, preventing duplicate audio engines,
/// duplicate WebSocket connections, and conflicting cleanup races.
@MainActor
final class MeetingSessionCoordinator {
    private let initializationOperations: MeetingSessionInitializationOperations
    private(set) var viewModel: LiveTranscriptionViewModel?
    private var presentations: Set<MeetingPresentationToken> = []
    private(set) var bridgePublisher: MeetingBridgePublisher?
    private var sessionInitializationTask: Task<Void, Never>?
    private var detectedMeetingLaunchPending = false
    private var detectedMeetingRecordingCancellable: AnyCancellable?

    private var webWindowController: MeetingAssistantWindowController?
    private var analysisWebWindowController: MeetingAnalysisWebWindowController?

    init(initializationOperations: MeetingSessionInitializationOperations = .live) {
        self.initializationOperations = initializationOperations
    }

    /// Meeting detection can receive an audio-sourced event immediately after
    /// the user accepts a calendar-sourced prompt but before the recorder has
    /// finished connecting. Treat that accepted launch as active from the
    /// moment it is reserved; once `isRecording` becomes true, the live
    /// recording itself keeps the gate closed.
    var shouldSuppressDetectedMeetingPrompt: Bool {
        detectedMeetingLaunchPending || viewModel?.isRecording == true
    }

    /// Atomically reserve the one detected-meeting launch allowed while no
    /// recording is active. Returns `false` when another detected meeting is
    /// already starting or recording, so callers can ignore a duplicate prompt.
    @discardableResult
    func reserveDetectedMeetingLaunch() -> Bool {
        guard !shouldSuppressDetectedMeetingPrompt else { return false }
        detectedMeetingLaunchPending = true
        return true
    }

    /// Lazily creates the shared model on first attach; every later attach
    /// reuses the same instance. `bridgePublisher` observes it from the same
    /// moment so late-attaching WebKit windows never miss initialization
    /// state.
    private func ensureSession() -> LiveTranscriptionViewModel {
        if let viewModel {
            return viewModel
        }
        let model = LiveTranscriptionViewModel()
        self.viewModel = model
        model.meetingSessionCoordinator = self
        self.bridgePublisher = MeetingBridgePublisher(viewModel: model)
        detectedMeetingRecordingCancellable = model.$isRecording
            .removeDuplicates()
            .sink { [weak self] isRecording in
                if isRecording {
                    self?.detectedMeetingLaunchPending = false
                }
            }
        sessionInitializationTask = Task { [weak model, initializationOperations] in
            guard let model else { return }
            await initializationOperations.loadMeetingHistory(model)
            guard !Task.isCancelled else {
                model.cleanupAllResources()
                return
            }
            await initializationOperations.initialize(model)
            guard !Task.isCancelled else {
                model.cleanupAllResources()
                return
            }
            await initializationOperations.loadAvailableModels(model)
            await initializationOperations.loadAnalysisModels(model)
            if Task.isCancelled {
                model.cleanupAllResources()
            }
        }
        return model
    }

    // MARK: - Attach / detach

    @discardableResult
    func attachWebPresentation(
        sink: @escaping (MeetingBridgeEvent) -> Void,
        meterSink: @escaping (MeetingMeterPayload) -> Void
    ) -> MeetingPresentationToken {
        _ = ensureSession()
        let token = MeetingPresentationToken(id: UUID())
        presentations.insert(token)
        bridgePublisher?.attach(token: token, sink: sink, meterSink: meterSink)
        return token
    }

    /// Completes the React ready handshake for one WebKit presentation.
    /// Sending the authoritative snapshot here, rather than during attach,
    /// guarantees the page has installed `window.basilMeetingAssistant`
    /// before Swift evaluates the callback. The same method is called after a
    /// WebKit content-process reload, which resets that renderer to revision 0
    /// without changing the native meeting session.
    func webPresentationDidBecomeReady(_ token: MeetingPresentationToken) {
        guard presentations.contains(token) else { return }
        bridgePublisher?.sendSnapshot(to: token)
    }

    /// Detaches exactly one presentation. Only performs the shared
    /// `cleanupAllResources()` teardown after every WebKit presentation has
    /// detached, so closing one window cannot interrupt another.
    func detachPresentation(_ token: MeetingPresentationToken) {
        presentations.remove(token)
        bridgePublisher?.detach(token: token)
        if presentations.isEmpty {
            sessionInitializationTask?.cancel()
            sessionInitializationTask = nil
            viewModel?.cleanupAllResources()
            viewModel = nil
            bridgePublisher = nil
            detectedMeetingRecordingCancellable = nil
            detectedMeetingLaunchPending = false
        }
    }

    // MARK: - Show

    /// Default entry point: opens (or focuses) the WebKit meeting window.
    /// When the Board is currently authoritative (its Meetings tab already
    /// has a live embedded host and no standalone window is visible), this
    /// raises the Board's own window instead of opening a second,
    /// redundant window showing the same live session -- mirroring
    /// `AgentTaskResultPresentationRouter`'s "fold into whichever surface is
    /// authoritative" rule.
    func showWebMeeting() {
        if MeetingPresentationCoordinator.shared.activePresenter == .board {
            MeetingPresentationCoordinator.shared.activeEmbeddedHost?.bringHostWindowToFront()
            return
        }
        if let webWindowController {
            webWindowController.show()
            return
        }
        let controller = MeetingAssistantWindowController(coordinator: self)
        webWindowController = controller
        controller.onClosed = { [weak self] in
            self?.webWindowController = nil
        }
        controller.show()
    }

    /// Opens (or focuses/updates) the WebKit analysis-results window with the
    /// most recent result for the meeting currently attached to the session.
    /// Called by `LiveTranscriptionViewModel+Analysis`'s coordinator
    /// delegation, never by React directly.
    func showAnalysisResult(_ result: MeetingAnalysisResultDTO) {
        _ = ensureSession()
        let store = MeetingActionProposalStore(
            proposals: (result.suggestedActions ?? []).map(Self.proposalModel(from:)),
            meetingId: result.meetingId,
            filename: result.filename
        )
        bridgePublisher?.publishAnalysisResult(result, store: store)
        Task {
            await store.refreshLinkedWorkStatuses()
        }
        analysisWindowController().show(result: result)
    }

    func showAnalysisLoading() {
        _ = ensureSession()
        analysisWindowController().showLoading()
    }

    private func analysisWindowController() -> MeetingAnalysisWebWindowController {
        if let analysisWebWindowController {
            return analysisWebWindowController
        }
        let controller = MeetingAnalysisWebWindowController(coordinator: self)
        analysisWebWindowController = controller
        controller.onClosed = { [weak self] in
            self?.analysisWebWindowController = nil
        }
        return controller
    }

    private static func proposalModel(from dto: MeetingActionProposalDTO) -> MeetingActionProposal {
        MeetingActionProposal(
            id: dto.id,
            sourceActionItemIndex: dto.sourceActionItemIndex,
            sourceActionItemIndexes: dto.sourceActionItemIndexes,
            sourceTask: dto.sourceTask,
            sourceContext: dto.sourceContext,
            sourceTimestamp: dto.sourceTimestamp,
            sourceSpeaker: dto.sourceSpeaker,
            suggestedAgentTask: dto.suggestedAgentTask,
            capabilityType: dto.capabilityType,
            confidence: dto.confidence,
            whyBasilCanHelp: dto.whyBasilCanHelp,
            missingInformation: dto.missingInformation,
            requiresUserConfirmation: dto.requiresUserConfirmation,
            executionMode: dto.executionMode,
            workspaceSource: dto.workspaceSource,
            executionStatus: dto.executionStatus,
            submittedAgentTaskId: dto.submittedAgentTaskId,
            todoId: dto.todoId
        )
    }

    // MARK: - Entry-path delegation
    //
    // Every existing entry path (status-bar menu, meeting detection, calendar
    // context, meeting-end finalization, BasilBoard handoff) routes through
    // these methods so the WebKit presentation always reuses the same session
    // instead of re-implementing arming or selection.

    func showAndStart(arming meeting: DetectedMeetingInfo) {
        showWebMeeting()
        let model = ensureSession()
        if #available(macOS 14.0, *) {
            model.armAutoStart(
                bundleID: meeting.bundleID,
                pid: meeting.pid,
                enableMic: true,
                title: meeting.calendarTitle,
                participants: meeting.calendarAttendees
            )
        }
    }

    func showWithCalendarContext(_ meeting: DetectedMeetingInfo) {
        showWebMeeting()
        let model = ensureSession()
        if let title = meeting.calendarTitle, !title.isEmpty {
            model.meetingName = title
        }
        if !meeting.calendarAttendees.isEmpty {
            model.meetingParticipants = meeting.calendarAttendees.joined(separator: ", ")
        }
        model.enableMicrophone = true
        model.systemAudioCaptureMode = .globalOutput
        model.statusMessage = "Recording microphone and system audio. Join the call; remote audio will be captured once it starts playing."
        model.startRecording()
    }

    func selectMeeting(_ meetingId: String) async {
        showWebMeeting()
        await viewModel?.selectMeeting(meetingId)
    }

    @discardableResult
    func finalizeForEndedMeeting(bundleID: String) -> Bool {
        guard let viewModel,
              viewModel.isRecording,
              let started = viewModel.autoStartedBundleID,
              started == bundleID else {
            return false
        }
        viewModel.stopRecording()
        return true
    }

    var isSessionActive: Bool { viewModel != nil }
}
