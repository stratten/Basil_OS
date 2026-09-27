import Combine
import Foundation
import AppKit
import UniformTypeIdentifiers

@MainActor
final class AudioFileUploadBridgeController {
    private let viewModel: AudioFileUploadViewModel
    private weak var output: AudioFileUploadBridgeOutput?
    private weak var window: NSWindow?
    private weak var collapseController: WindowCollapseController?
    private var cancellables = Set<AnyCancellable>()
    private var revision = 0
    private var hasSentInitialSnapshot = false
    private var lastRevisionPayloadSignature: Data?

    private let supportedTypes: [UTType] = [
        .audiovisualContent,
        UTType(filenameExtension: "mp3") ?? .audio,
        UTType(filenameExtension: "wav") ?? .audio,
        UTType(filenameExtension: "m4a") ?? .audio,
        UTType(filenameExtension: "aac") ?? .audio,
        UTType(filenameExtension: "flac") ?? .audio,
    ]

    init(viewModel: AudioFileUploadViewModel, output: AudioFileUploadBridgeOutput, window: NSWindow, collapseController: WindowCollapseController) {
        self.viewModel = viewModel
        self.output = output
        self.window = window
        self.collapseController = collapseController
        subscribeToViewModel()
    }

    func sendInitialSnapshot() {
        output?.sendInit(theme: currentThemeJSON())
        emitSnapshot(forceSnapshot: true)
    }

    func sendThemeChanged() {
        output?.sendInit(theme: currentThemeJSON())
    }

    func handle(intent: [String: Any]) {
        guard let type = intent["type"] as? String else { return }
        switch type {
        case "selectAudioFile":
            presentOpenPanel()
        case "clearSelectedFile":
            viewModel.selectedFileURL = nil
        case "setDescription":
            guard let value = intent["value"] as? String else { return }
            viewModel.description = value
        case "setLanguage":
            guard let value = intent["value"] as? String else { return }
            viewModel.selectedLanguage = value
        case "upload":
            Task { await viewModel.uploadFile() }
        case "copyTranscriptionResult":
            guard let text = viewModel.transcriptionResult else { return }
            let rules = APIClient.shared.getCachedTranscriptionSettings().textReplacements
            let normalized = TranscriptionOutputTextNormalizer.apply(text, rules: rules)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(normalized, forType: .string)
        case "dismissError":
            viewModel.showError = false
            viewModel.errorMessage = ""
        case "cancel":
            window?.close()
        case "minimize":
            window?.miniaturize(nil)
        case "collapse":
            collapseController?.setCollapsed(true)
        case "expand":
            collapseController?.setCollapsed(false)
        default:
            #if DEBUG
            DevLogger.shared.warning("[AUDIO_UPLOAD_BRIDGE] Unknown intent type: \(type)", context: "AudioFileUploadBridgeController")
            #endif
        }
    }

    private func presentOpenPanel() {
        guard let window else { return }
        let openPanel = NSOpenPanel()
        openPanel.allowsMultipleSelection = false
        openPanel.canChooseDirectories = false
        openPanel.canChooseFiles = true
        openPanel.allowedContentTypes = supportedTypes
        openPanel.title = "Select Audio File"
        openPanel.prompt = "Select"
        openPanel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let url = openPanel.url, let self else { return }
            self.viewModel.selectedFileURL = url
            self.viewModel.loadFileDetails()
        }
    }

    private func subscribeToViewModel() {
        viewModel.objectWillChange
            .receive(on: DispatchQueue.main)
            .debounce(for: .milliseconds(16), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async {
                    self?.emitSnapshot()
                }
            }
            .store(in: &cancellables)
    }

    private func emitSnapshot(forceSnapshot: Bool = false) {
        let payload = buildSnapshotPayload()
        let signature = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        if !forceSnapshot, signature == lastRevisionPayloadSignature {
            return
        }
        lastRevisionPayloadSignature = signature
        revision += 1
        if forceSnapshot || !hasSentInitialSnapshot {
            hasSentInitialSnapshot = true
            output?.sendSnapshot(revision: revision, payload: payload)
        } else {
            output?.sendDelta(revision: revision, payload: payload)
        }
    }

    private func buildSnapshotPayload() -> [String: Any] {
        [
            "hasSelectedFile": viewModel.selectedFileURL != nil,
            "selectedFileName": viewModel.selectedFileURL?.lastPathComponent as Any? ?? NSNull(),
            "fileSizeDisplay": viewModel.fileSize as Any? ?? NSNull(),
            "fileDurationDisplay": formattedDuration(viewModel.fileDuration) as Any? ?? NSNull(),
            "description": viewModel.description,
            "selectedLanguage": viewModel.selectedLanguage,
            "isUploading": viewModel.isUploading,
            "uploadStatus": viewModel.uploadStatus,
            "transcriptionResult": viewModel.transcriptionResult as Any? ?? NSNull(),
            "canUpload": viewModel.canUpload,
            "errorMessage": (viewModel.showError ? viewModel.errorMessage : nil) as Any? ?? NSNull(),
        ]
    }

    private func formattedDuration(_ seconds: Double?) -> String? {
        guard let seconds, seconds > 0 else { return nil }
        let formatter = DateComponentsFormatter()
        formatter.allowedUnits = [.hour, .minute, .second]
        formatter.unitsStyle = .abbreviated
        return formatter.string(from: seconds)
    }

    private func currentThemeJSON() -> [String: Any] {
        AestheticWebPayload.themePayload()
    }
}
