import Combine
import Foundation
import AppKit
import SwiftUI

@MainActor
final class TranscriptionBridgeController {
    private let viewModel: TranscriptionWidgetViewModel
    private weak var output: TranscriptionBridgeOutput?
    private let showErrorPopover: (String) -> Void
    private var cancellables = Set<AnyCancellable>()
    private var revision = 0
    private var hasSentInitialSnapshot = false
    private var lastRevisionPayloadSignature: Data?

    init(
        viewModel: TranscriptionWidgetViewModel,
        output: TranscriptionBridgeOutput,
        showErrorPopover: @escaping (String) -> Void = { _ in }
    ) {
        self.viewModel = viewModel
        self.output = output
        self.showErrorPopover = showErrorPopover
        subscribeToViewModel()
    }

    func sendInitialSnapshot() {
        output?.sendInit(theme: currentThemeJSON())
        emitSnapshot(forceSnapshot: true)
    }

    func sendThemeChanged() {
        output?.sendThemeChanged(theme: currentThemeJSON())
    }

    func handle(intent: [String: Any]) {
        guard let type = intent["type"] as? String else { return }
        switch type {
        case "toggleRecording":
            Task { await viewModel.toggleRecording() }
        case "cancelRecording":
            Task { await viewModel.cancelRecording() }
        case "toggleMinimizedState":
            viewModel.toggleMinimizedState()
        case "close":
            // Mirrors the minimized close button's cancel-then-close guard
            // (TranscriptionWidget.swift lines 86-94), applied uniformly for
            // both widget states since the React shell has one close path.
            Task {
                if viewModel.isRecording || viewModel.isStartingRecording {
                    await viewModel.cancelRecording()
                }
                if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                    appDelegate.toggleTranscriptionWidget()
                }
            }
        case "clearTranscription":
            viewModel.clearTranscription()
        case "copyToClipboard":
            viewModel.copyToClipboard()
        case "selectTranscriptionModel":
            guard let modelId = intent["modelId"] as? String else { return }
            Task { await viewModel.swapTranscriptionModel(to: modelId) }
        case "showTranscriptionModelMenu":
            guard let rawAnchorRect = intent["anchorRect"] as? [String: Any],
                  let anchorRect = nativeAnchorRect(from: rawAnchorRect) else {
                return
            }
            output?.showTranscriptionModelPicker(
                models: viewModel.availableTranscriptionModels,
                selectedModelId: viewModel.currentTranscriptionModelId,
                anchorRect: anchorRect
            ) { [weak self] modelId in
                Task { await self?.viewModel.swapTranscriptionModel(to: modelId) }
            }
        case "openSystemMicrophoneSettings":
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
                NSWorkspace.shared.open(url)
            }
        case "showErrorPopover":
            guard let error = viewModel.error, !error.isEmpty else { return }
            showErrorPopover(error)
        case "requestResize":
            // Deliberate no-op: Transcription's minimized size is a fixed
            // constant and its full size is user-resizable via native
            // NSPanel drag, both driven by WindowChromeCollapse — React
            // never needs to request a resize for this surface. This is a
            // documented departure from AssistantSession's content-driven
            // sizing, not an oversight.
            break
        default:
            #if DEBUG
            DevLogger.shared.warning("[TRANSCRIPTION_WIDGET_BRIDGE] Unknown intent type: \(type)", context: "TranscriptionBridgeController")
            #endif
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

        viewModel.audioLevelPublisher
            .sink { [weak self] level in
                self?.output?.sendMeter(audioLevel: level)
            }
            .store(in: &cancellables)
    }

    private func emitSnapshot(forceSnapshot: Bool = false) {
        let payload = buildSnapshotPayload()
        var revisionPayload = payload
        revisionPayload.removeValue(forKey: "audioLevel")
        let signature = try? JSONSerialization.data(withJSONObject: revisionPayload, options: [.sortedKeys])
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
        let bubbleMode: String
        if viewModel.isRecording {
            bubbleMode = "audioResponsive"
        } else if viewModel.isProcessingRecording {
            bubbleMode = "processing"
        } else {
            bubbleMode = "ambient"
        }
        let bubbleColors = resolveBubbleColorsJSON(isRecording: viewModel.isRecording, isProcessing: viewModel.isProcessingRecording)

        return [
            "isRecording": viewModel.isRecording,
            "isStartingRecording": viewModel.isStartingRecording,
            "isProcessingRecording": viewModel.isProcessingRecording,
            "isConnected": viewModel.isConnected,
            "isModelReady": viewModel.isModelReady,
            "isModelLoading": viewModel.isModelLoading,
            "error": viewModel.error as Any? ?? NSNull(),
            "transcriptionText": viewModel.transcriptionText,
            "audioLevel": viewModel.audioLevel,
            "elapsedSeconds": viewModel.elapsedSeconds,
            "isMinimized": viewModel.isMinimized,
            "canToggleRecording": viewModel.canToggleRecording,
            "currentTranscriptionModelId": viewModel.currentTranscriptionModelId,
            "availableTranscriptionModels": viewModel.availableTranscriptionModels.map(modelInfoJSON),
            "isSwappingTranscriptionModel": viewModel.isSwappingTranscriptionModel,
            "hotkeyDisplayString": HotkeyService.shared.hotkeyBindings["transcribe_audio"]?.displayString as Any? ?? NSNull(),
            "bubbleMode": bubbleMode,
            "bubbleColors": bubbleColors,
        ]
    }

    private func modelInfoJSON(_ model: TranscriptionModelOption) -> [String: Any] {
        ["id": model.id, "displayName": model.displayName, "isApiModel": model.isApiModel]
    }

    private func nativeAnchorRect(from rawAnchorRect: [String: Any]) -> [String: CGFloat]? {
        let keys = ["x", "y", "width", "height"]
        var anchorRect: [String: CGFloat] = [:]
        for key in keys {
            guard let number = rawAnchorRect[key] as? NSNumber else {
                return nil
            }
            anchorRect[key] = CGFloat(truncating: number)
        }
        return anchorRect
    }

    private func resolveBubbleColorsJSON(isRecording: Bool, isProcessing: Bool) -> [String: String] {
        let colors: (base: Color, accent: Color)
        if isRecording {
            colors = AestheticSystem.Colors.bubbleColors(for: .recording)
        } else if isProcessing {
            colors = AestheticSystem.Colors.bubbleColors(for: .processing)
        } else {
            colors = AestheticSystem.Colors.bubbleColors(for: .idle)
        }
        return [
            "base": AestheticWebPayload.colorToHex(colors.base),
            "accent": AestheticWebPayload.colorToHex(colors.accent),
        ]
    }

    private func currentThemeJSON() -> [String: Any] {
        TranscriptionThemeSnapshot.currentJSON()
    }
}
