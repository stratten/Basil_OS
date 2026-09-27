import SwiftUI
import AppKit

enum ProfileEditorMode: String {
    case memoryFile = "memory_file"
    case skill
    case memoryProposal = "memory_proposal"
    case skillCandidate = "skill_candidate"
}

enum ProfileEditorRequest {
    case memoryFile(name: String)
    case skill(slug: String)
    case memoryProposal(id: String)
    case skillCandidate(id: String)

    var mode: ProfileEditorMode {
        switch self {
        case .memoryFile: return .memoryFile
        case .skill: return .skill
        case .memoryProposal: return .memoryProposal
        case .skillCandidate: return .skillCandidate
        }
    }

    var identifier: String {
        switch self {
        case .memoryFile(let name): return name
        case .skill(let slug): return slug
        case .memoryProposal(let id): return id
        case .skillCandidate(let id): return id
        }
    }

    var windowKey: String {
        "\(mode.rawValue):\(identifier)"
    }

    var title: String {
        switch self {
        case .memoryFile(let name): return "Edit \(name)"
        case .skill: return "Edit Skill"
        case .memoryProposal: return "Review Memory"
        case .skillCandidate: return "Review Skill"
        }
    }
}

@MainActor
final class ProfileEditorWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    private var completion: ((Bool) -> Void)?
    private var didComplete = false
    private let closeRelay: ProfileEditorCloseRelay
    private weak var profileEditorCoordinator: ProfileEditorWebView.Coordinator?

    init(request: ProfileEditorRequest, completion: ((Bool) -> Void)?) {
        self.completion = completion
        let closeRelay = ProfileEditorCloseRelay()
        self.closeRelay = closeRelay
        let hostingView = NSHostingView(rootView: AnyView(EmptyView()))
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 620),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = request.title
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true
        window.contentView = hostingView
        WebKitWindowChromeAppearance.apply(to: window)
        window.center()
        super.init(window: window)

        let contentView = ProfileEditorWebView(request: request) { [weak closeRelay] didChange in
            closeRelay?.close(didChange: didChange)
        } onMinimize: { [weak closeRelay] in
            closeRelay?.minimize()
        } onOpenSourceTask: { taskId in
            Task { @MainActor in
                AgentTaskResultPresentationRouter.showExistingAgentTask(agentTaskId: taskId)
                NSApp.activate(ignoringOtherApps: true)
            }
        } onCoordinatorReady: { [weak self] coordinator in
            self?.profileEditorCoordinator = coordinator
            if let self {
                AppearanceRefreshCoordinator.shared.register(self)
            }
        }
        hostingView.rootView = AnyView(contentView)
        window.delegate = self
        closeRelay.onClose = { [weak self] didChange in
            self?.finish(didChange: didChange)
        }
        closeRelay.onMinimize = { [weak window] in
            window?.miniaturize(nil)
        }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func show() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        finish(didChange: false)
    }

    func refreshAppearance() {
        profileEditorCoordinator?.sendThemeChanged()
    }

    private func finish(didChange: Bool) {
        if didComplete { return }
        didComplete = true
        completion?(didChange)
        completion = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        window?.close()
    }
}

private final class ProfileEditorCloseRelay {
    var onClose: ((Bool) -> Void)?
    var onMinimize: (() -> Void)?

    func close(didChange: Bool) {
        onClose?(didChange)
    }

    func minimize() {
        onMinimize?()
    }
}
