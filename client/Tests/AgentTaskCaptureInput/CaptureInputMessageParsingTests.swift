import XCTest
@testable import BasilClient

final class AgentTaskCaptureInputMessageParsingTests: XCTestCase {
    func testParsesReady() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "captureInputReady"]), .captureInputReady)
    }

    func testParsesRequestSnapshot() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "requestSnapshot"]), .requestSnapshot)
    }

    func testParsesRequestCaptureResizeWithNumericWidthAndHeight() {
        // Boxed as NSNumber, not a bare Swift Int/Double literal, because a
        // real WKScriptMessage body bridges JS numbers to NSNumber, and only
        // NSNumber (not a native Swift Int/Double stored in Any) successfully
        // satisfies `as? CGFloat` via Objective-C runtime bridging. A bare
        // `Any` holding a native Swift Int/Double does not dynamically cast
        // to CGFloat with `as?`.
        let parsed = CaptureInputMessage.parse(body: [
            "type": "requestCaptureResize",
            "width": NSNumber(value: 360),
            "height": NSNumber(value: 280),
        ])
        XCTAssertEqual(parsed, .requestCaptureResize(width: 360, height: 280))
    }

    func testParsesFinitePositiveCaptureHeaderExtent() {
        XCTAssertEqual(
            CaptureInputMessage.parse(body: [
                "type": "captureHeaderExtent",
                "height": NSNumber(value: 44),
            ]),
            .captureHeaderExtent(height: 44)
        )
    }

    func testRejectsInvalidCaptureHeaderExtent() {
        for height in [NSNumber(value: 0), NSNumber(value: -1), NSNumber(value: Double.nan)] {
            XCTAssertEqual(
                CaptureInputMessage.parse(body: ["type": "captureHeaderExtent", "height": height]),
                .unknown(rawType: "captureHeaderExtent")
            )
        }
    }

    func testParsesEnterVoiceMode() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "enterVoiceMode"]), .enterVoiceMode)
    }

    func testParsesEnterTextEntryMode() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "enterTextEntryMode"]), .enterTextEntryMode)
    }

    func testParsesUpdateTextDraft() {
        let parsed = CaptureInputMessage.parse(body: ["type": "updateTextDraft", "text": "hello"])
        XCTAssertEqual(parsed, .updateTextDraft(text: "hello"))
    }

    func testParsesSubmitTextPromptWithModelId() {
        let parsed = CaptureInputMessage.parse(body: ["type": "submitTextPrompt", "text": "hello", "modelId": "gpt-5.6-terra-high"])
        XCTAssertEqual(parsed, .submitTextPrompt(text: "hello", modelId: "gpt-5.6-terra-high"))
    }

    func testParsesSubmitTextPromptWithoutModelId() {
        let parsed = CaptureInputMessage.parse(body: ["type": "submitTextPrompt", "text": "hello"])
        XCTAssertEqual(parsed, .submitTextPrompt(text: "hello", modelId: nil))
    }

    func testParsesSelectedModelAndExplicitClear() {
        XCTAssertEqual(
            CaptureInputMessage.parse(body: ["type": "setSelectedModel", "modelId": "reasoning-model-123"]),
            .setSelectedModel(modelId: "reasoning-model-123")
        )
        XCTAssertEqual(
            CaptureInputMessage.parse(body: ["type": "setSelectedModel", "modelId": NSNull()]),
            .setSelectedModel(modelId: nil)
        )
    }

    func testParsesNativeModelPicker() {
        let parsed = CaptureInputMessage.parse(body: [
            "type": "showNativeModelPicker",
            "models": [["id": "local-reasoning", "displayName": "Local Reasoning", "category": "local"]],
            "selectedModelId": NSNull(),
            "anchorRect": [
                "x": NSNumber(value: 134),
                "y": NSNumber(value: 161),
                "width": NSNumber(value: 14),
                "height": NSNumber(value: 14),
            ],
        ])

        XCTAssertEqual(
            parsed,
            .showNativeModelPicker(
                models: [CaptureModelPickerOption(id: "local-reasoning", displayName: "Local Reasoning", category: "local")],
                selectedModelId: nil,
                anchorRect: CaptureModelPickerAnchorRect(x: 134, y: 161, width: 14, height: 14)
            )
        )
    }

    func testRejectsMalformedNativeModelPicker() {
        let valid: [String: Any] = [
            "type": "showNativeModelPicker",
            "models": [["id": "local-reasoning", "displayName": "Local Reasoning", "category": "local"]],
            "selectedModelId": NSNull(),
            "anchorRect": [
                "x": NSNumber(value: 134),
                "y": NSNumber(value: 161),
                "width": NSNumber(value: 14),
                "height": NSNumber(value: 14),
            ],
        ]
        var missingDisplayName = valid
        missingDisplayName["models"] = [["id": "local-reasoning", "category": "local"]]
        var unsupportedCategory = valid
        unsupportedCategory["models"] = [["id": "local-reasoning", "displayName": "Local Reasoning", "category": "other"]]
        let nonArrayModels: [String: Any] = [
            "type": "showNativeModelPicker",
            "models": "not an array",
        ]
        var missingAnchorField = valid
        missingAnchorField["anchorRect"] = [
            "x": NSNumber(value: 134),
            "width": NSNumber(value: 14),
            "height": NSNumber(value: 14),
        ]
        var nonnumericAnchor = valid
        nonnumericAnchor["anchorRect"] = [
            "x": "not a number",
            "y": NSNumber(value: 161),
            "width": NSNumber(value: 14),
            "height": NSNumber(value: 14),
        ]

        for body in [missingDisplayName, unsupportedCategory, nonArrayModels, missingAnchorField, nonnumericAnchor] {
            XCTAssertEqual(CaptureInputMessage.parse(body: body), .unknown(rawType: "showNativeModelPicker"))
        }
    }

    func testParsesCancelCapture() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "cancelCapture"]), .cancelCapture)
    }

    func testParsesPickReferenceFiles() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "pickReferenceFiles"]), .pickReferenceFiles)
    }

    func testParsesRemoveReferencePath() {
        // `Any` holding a native Swift Int literal casts fine to `Int` with
        // `as?` (same concrete type, no bridging needed) — unlike the
        // CGFloat case above, no NSNumber boxing is required here.
        let parsed = CaptureInputMessage.parse(body: ["type": "removeReferencePath", "index": 2])
        XCTAssertEqual(parsed, .removeReferencePath(index: 2))
    }

    func testParsesOpenReferencePath() {
        let parsed = CaptureInputMessage.parse(body: ["type": "openReferencePath", "path": "/tmp/report.pdf"])
        XCTAssertEqual(parsed, .openReferencePath(path: "/tmp/report.pdf"))
    }

    func testParsesFilesDropped() {
        let parsed = CaptureInputMessage.parse(body: ["type": "filesDropped", "paths": ["/tmp/a.pdf", "/tmp/b.pdf"]])
        XCTAssertEqual(parsed, .filesDropped(paths: ["/tmp/a.pdf", "/tmp/b.pdf"]))
    }

    func testParsesSetDraggingOver() {
        let parsed = CaptureInputMessage.parse(body: ["type": "setDraggingOver", "isDraggingOver": true])
        XCTAssertEqual(parsed, .setDraggingOver(isDraggingOver: true))
    }

    func testParsesShowHistory() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "showHistory"]), .showHistory)
    }

    func testReturnsNilForMissingType() {
        XCTAssertNil(CaptureInputMessage.parse(body: ["text": "hello"]))
    }

    func testReturnsNilForNonDictionaryBody() {
        XCTAssertNil(CaptureInputMessage.parse(body: "not a dictionary"))
    }

    func testReturnsUnknownRatherThanNilForAnUnrecognizedType() {
        // `.unknown(rawType:)`, not `nil`, is the malformed-intent contract
        // once a string `type` field is present at all (05_Bridge_Contract_
        // And_Types.md section 5.6) — `nil` is reserved for bodies that are
        // not shaped like a bridge message in the first place (missing/non-
        // string `type`, or a non-dictionary body), covered above.
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "notARealIntent"]), .unknown(rawType: "notARealIntent"))
    }

    func testReturnsUnknownWhenARequiredFieldIsMissing() {
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "updateTextDraft"]), .unknown(rawType: "updateTextDraft"))
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "removeReferencePath"]), .unknown(rawType: "removeReferencePath"))
        XCTAssertEqual(CaptureInputMessage.parse(body: ["type": "openReferencePath"]), .unknown(rawType: "openReferencePath"))
    }

    func testReturnsUnknownWhenARequiredFieldHasTheWrongType() {
        XCTAssertEqual(
            CaptureInputMessage.parse(body: ["type": "requestCaptureResize", "width": "not a number", "height": NSNumber(value: 280)]),
            .unknown(rawType: "requestCaptureResize")
        )
        XCTAssertEqual(
            CaptureInputMessage.parse(body: ["type": "removeReferencePath", "index": "not a number"]),
            .unknown(rawType: "removeReferencePath")
        )
        XCTAssertEqual(
            CaptureInputMessage.parse(body: ["type": "setSelectedModel", "modelId": 42]),
            .unknown(rawType: "setSelectedModel")
        )
    }
}
