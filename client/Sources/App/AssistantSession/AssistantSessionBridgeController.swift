import Combine
import Foundation
import AppKit
import SwiftUI

@MainActor
final class AssistantSessionBridgeController {
    private let viewModel: AssistantSessionViewModel
    private weak var output: AssistantSessionBridgeOutput?
    private var cancellables = Set<AnyCancellable>()
    private var revision = 0
    private var hasSentInitialSnapshot = false
    private var lastRevisionPayloadSignature: Data?

    init(viewModel: AssistantSessionViewModel, output: AssistantSessionBridgeOutput) {
        self.viewModel = viewModel
        self.output = output
        subscribeToViewModel()
    }

    func sendInitialSnapshot() {
        output?.sendInit(theme: currentThemeJSON())
        emitSnapshot(forceSnapshot: true)
        Task { await viewModel.loadModelsIfNeeded() }
    }

    func sendThemeChanged() {
        output?.sendThemeChanged(theme: currentThemeJSON())
    }

    func handle(intent: [String: Any]) {
        guard let type = intent["type"] as? String else { return }
        switch type {
        case "cancelOperation":
            viewModel.cancelOperation()
        case "minimizeWidget":
            viewModel.minimizeWidget()
        case "toggleResultCollapse":
            viewModel.setResultChromeCollapsed(!viewModel.isResultChromeCollapsed)
        case "switchInputMode":
            guard let raw = intent["mode"] as? String,
                  let mode = AssistantSessionInputMode(rawValue: raw) else { return }
            Task { await viewModel.switchInputMode(to: mode) }
        case "submitTypedInstruction":
            guard let text = intent["text"] as? String else { return }
            viewModel.typedInstruction = text
            // A typed submission has no transcription stage, so claim the
            // same processing state that the voice path reaches after audio
            // transcription. This is set before the commit latch releases
            // the suspended main flow, preventing its temporary reset of
            // inputCommitted from re-rendering the editable typed surface.
            viewModel.assistantSessionStatus = .running
            viewModel.typedInputSubmissionRequested = true
            viewModel.inputCommitted = true
        case "stopRecording":
            viewModel.stopRecording()
        case "selectModel":
            guard let modelId = intent["modelId"] as? String else { return }
            viewModel.selectModel(modelId)
        case "enterEditMode":
            viewModel.enterEditMode()
        case "cancelEditMode":
            viewModel.cancelEditMode()
        case "applyEdits":
            guard let content = intent["content"] as? String else { return }
            viewModel.editableContent = content
            viewModel.applyEdits()
        case "saveAsSample":
            let content = intent["content"] as? String
            viewModel.saveAsSample(explicitContent: content)
        case "enterVoiceRefinement":
            viewModel.enterRefinementMode()
            Task { await viewModel.startRefinementRecording() }
        case "enterTypedRefinement":
            viewModel.enterRefinementMode()
        case "cancelTypedRefinement":
            viewModel.assistantSessionStatus = .completed
            if viewModel.iterationCount == 0 {
                viewModel.isRefinementMode = false
                viewModel.showRefinementIndicator = false
            }
        case "submitTypedRefinement":
            guard let text = intent["text"] as? String else { return }
            Task { await viewModel.processRefinementText(text) }
        case "stopRefinementRecording":
            viewModel.stopRecording()
        case "copyRichText":
            copyRichTextToClipboard()
        case "copyMarkdown":
            copyMarkdownToClipboard()
        case "openExternalUrl":
            guard let rawURL = intent["url"] as? String,
                  let url = URL(string: rawURL),
                  url.scheme == "https" || url.scheme == "http" else { return }
            NSWorkspace.shared.open(url)
        case "openHistory":
            AssistantOutputHistoryWindowController.show(anchorFrame: AssistantSessionWindowController.sharedController?.window?.frame)
        default:
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION_BRIDGE] Unknown intent type: \(type)", context: "AssistantSessionBridgeController")
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

        viewModel.$audioLevel
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
        let canSubmit = viewModel.ocrText != nil && !(viewModel.ocrText?.isEmpty ?? true)
        let isProcessing = viewModel.ocrStatus == .running
            || viewModel.transcriptionStatus == .running
            || viewModel.assistantSessionStatus == .running
        let bubbleMode: String
        if viewModel.isRecording {
            bubbleMode = "audioResponsive"
        } else if isProcessing {
            bubbleMode = "processing"
        } else {
            bubbleMode = "ambient"
        }
        let bubbleColors = resolveBubbleColorsJSON(isRecording: viewModel.isRecording, isProcessing: isProcessing)

        return [
            "ocrStatus": viewModel.ocrStatus.rawValue,
            "transcriptionStatus": viewModel.transcriptionStatus.rawValue,
            "assistantSessionStatus": viewModel.assistantSessionStatus.rawValue,
            "errorMessage": viewModel.errorMessage as Any? ?? NSNull(),
            "assistantOutput": viewModel.assistantOutput,
            "thinkingContent": viewModel.thinkingContent as Any? ?? NSNull(),
            "isRecording": viewModel.isRecording,
            "audioLevel": viewModel.audioLevel,
            "elapsedSeconds": viewModel.elapsedSeconds,
            "transcriptionText": viewModel.transcriptionText,
            "transcriptionProgressMessage": viewModel.transcriptionProgressMessage as Any? ?? NSNull(),
            "transcriptionProgressFraction": viewModel.transcriptionProgressFraction as Any? ?? NSNull(),
            "shouldPersistUI": viewModel.shouldPersistUI,
            "isResultChromeCollapsed": viewModel.isResultChromeCollapsed,
            "hasTextSelection": viewModel.hasTextSelection,
            "selectedText": viewModel.selectionContext?.selectedText as Any? ?? NSNull(),
            "detectedApplicationName": (viewModel.detectedApplicationName ?? viewModel.selectionContext?.applicationName) as Any? ?? NSNull(),
            "isRefinementMode": viewModel.isRefinementMode,
            "iterationCount": viewModel.iterationCount,
            "showRefinementIndicator": viewModel.showRefinementIndicator,
            "inputMode": viewModel.inputMode.rawValue,
            "inputCommitted": viewModel.inputCommitted,
            "typedInstruction": viewModel.typedInstruction,
            "ocrText": viewModel.ocrText as Any? ?? NSNull(),
            "canSubmitTypedInstruction": canSubmit,
            "selectedModelId": viewModel.selectedModelId as Any? ?? NSNull(),
            "availableModels": viewModel.availableModels.map(modelInfoJSON),
            "localModels": viewModel.localModels.map(modelInfoJSON),
            "apiModels": viewModel.apiModels.map(modelInfoJSON),
            "useApiModels": viewModel.useApiModels,
            "isLoadingModels": viewModel.isLoadingModels,
            "sampleSaved": viewModel.sampleSaved,
            "savingSample": viewModel.savingSample,
            "isEditMode": viewModel.isEditMode,
            "editableContentSeed": viewModel.isEditMode ? viewModel.editableContent : viewModel.assistantOutput,
            "hotkeyDisplayString": HotkeyService.shared.hotkeyBindings["assistantSession"]?.displayString as Any? ?? NSNull(),
            "bubbleMode": bubbleMode,
            "bubbleColors": bubbleColors,
        ]
    }

    private func modelInfoJSON(_ model: ModelServiceInfo) -> [String: Any] {
        ["id": model.id, "displayName": model.displayName, "isApiModel": model.isApiModel]
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
        AssistantSessionThemeSnapshot.currentJSON()
    }

    private func copyMarkdownToClipboard() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(viewModel.assistantOutput, forType: .string)
    }

    private func copyRichTextToClipboard() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        let attributedString = MarkdownUtils.markdownToAttributedString(viewModel.assistantOutput)
        pasteboard.setString(attributedString.string, forType: .string)
        if MarkdownUtils.containsMarkdown(viewModel.assistantOutput) {
            if let rtfData = attributedString.rtf(from: NSRange(location: 0, length: attributedString.length), documentAttributes: [:]) {
                pasteboard.setData(rtfData, forType: .rtf)
            }
        }
    }
}
