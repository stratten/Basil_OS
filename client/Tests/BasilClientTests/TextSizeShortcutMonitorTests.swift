import AppKit
import XCTest
@testable import BasilClient

final class TextSizeShortcutResolutionTests: XCTestCase {
    func testCommandEqualsAndCommandPlusEnlarge() {
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "=", modifierFlags: [.command]), .larger)
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "+", modifierFlags: [.command, .shift]), .larger)
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "=", modifierFlags: [.command, .shift]), .larger)
    }

    func testCommandMinusShrinks() {
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "-", modifierFlags: [.command]), .smaller)
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "_", modifierFlags: [.command, .shift]), .smaller)
    }

    func testCommandZeroResetsButCommandShiftZeroDoesNot() {
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "0", modifierFlags: [.command]), .reset)
        XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: "0", modifierFlags: [.command, .shift]))
    }

    func testOptionAndControlNeverQualify() {
        for key in ["=", "+", "-", "_", "0"] {
            XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: key, modifierFlags: [.command, .option]), key)
            XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: key, modifierFlags: [.command, .control]), key)
        }
    }

    func testWithoutCommandNothingQualifies() {
        for key in ["=", "+", "-", "0"] {
            XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: key, modifierFlags: []), key)
            XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: key, modifierFlags: [.shift]), key)
        }
    }

    func testOtherKeysAndMissingCharactersDoNotQualify() {
        XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: "a", modifierFlags: [.command]))
        XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: "", modifierFlags: [.command]))
        XCTAssertNil(TextSizeShortcut.resolve(charactersIgnoringModifiers: nil, modifierFlags: [.command]))
    }

    func testCapsLockAndFunctionFlagsAreIgnored() {
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "=", modifierFlags: [.command, .capsLock]), .larger)
        XCTAssertEqual(TextSizeShortcut.resolve(charactersIgnoringModifiers: "0", modifierFlags: [.command, .numericPad]), .reset)
    }

    func testTargetsWalkTheOfferedSteps() {
        XCTAssertEqual(TextSizeShortcut.larger.target(from: 1.0), 1.1)
        XCTAssertEqual(TextSizeShortcut.larger.target(from: 1.4), 1.4)
        XCTAssertEqual(TextSizeShortcut.smaller.target(from: 1.0), 0.9)
        XCTAssertEqual(TextSizeShortcut.smaller.target(from: 0.9), 0.9)
        XCTAssertEqual(TextSizeShortcut.reset.target(from: 1.25), 1.0)
    }
}

@MainActor
final class TextSizeShortcutMonitorTests: XCTestCase {
    private struct SaveFailure: Error {}

    @MainActor
    private final class Harness {
        var settings: AppearanceSettings?
        var applied: [Double] = []
        var persisted: [Double] = []
        var draftConsumes = false
        var draftShortcuts: [TextSizeShortcut] = []
        var failSaves = false
        var monitor: TextSizeShortcutMonitor!

        init(startingScale: Double = 1.0, loaded: Bool = true, saveDelayNanoseconds: UInt64 = 20_000_000) {
            if loaded {
                var initial = AppearanceSettings()
                initial.textScale = startingScale
                settings = initial
            }
            monitor = TextSizeShortcutMonitor(
                currentSettings: { [unowned self] in self.settings },
                applySettings: { [unowned self] updated in
                    self.settings = updated
                    self.applied.append(updated.textScale)
                },
                persistSettings: { [unowned self] saved in
                    self.persisted.append(saved.textScale)
                    if self.failSaves { throw SaveFailure() }
                },
                applyToUnsavedDraft: { [unowned self] shortcut in
                    self.draftShortcuts.append(shortcut)
                    return self.draftConsumes
                },
                saveDelayNanoseconds: saveDelayNanoseconds
            )
        }
    }

    func testAPressAppliesTheNewSizeImmediatelyAndSavesItOnce() async {
        let harness = Harness()

        XCTAssertTrue(harness.monitor.handle(.larger))
        XCTAssertEqual(harness.applied, [1.1])
        XCTAssertEqual(harness.persisted, [])

        await harness.monitor.waitForPendingSave()
        XCTAssertEqual(harness.persisted, [1.1])
    }

    func testABurstOfPressesSavesOnlyTheFinalSize() async {
        let harness = Harness()

        harness.monitor.handle(.larger)
        harness.monitor.handle(.larger)
        harness.monitor.handle(.larger)
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.applied, [1.1, 1.25, 1.4])
        XCTAssertEqual(harness.persisted, [1.4])
    }

    func testConsecutivePressesAccumulateFromTheLatestAppliedSize() async {
        let harness = Harness(startingScale: 1.25)

        harness.monitor.handle(.smaller)
        harness.monitor.handle(.smaller)
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.settings?.textScale, 1.0)
        XCTAssertEqual(harness.persisted, [1.0])
    }

    func testResetReturnsToOneHundredPercent() async {
        let harness = Harness(startingScale: 1.4)

        XCTAssertTrue(harness.monitor.handle(.reset))
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.applied, [1.0])
        XCTAssertEqual(harness.persisted, [1.0])
    }

    func testAtTheLimitsThePressIsConsumedWithoutApplyingOrSaving() async {
        let largest = Harness(startingScale: 1.4)
        XCTAssertTrue(largest.monitor.handle(.larger))
        await largest.monitor.waitForPendingSave()
        XCTAssertEqual(largest.applied, [])
        XCTAssertEqual(largest.persisted, [])

        let atDefault = Harness(startingScale: 1.0)
        XCTAssertTrue(atDefault.monitor.handle(.reset))
        await atDefault.monitor.waitForPendingSave()
        XCTAssertEqual(atDefault.applied, [])
        XCTAssertEqual(atDefault.persisted, [])
    }

    func testAnUnsavedSettingsDraftTakesThePressInsteadOfTheSavedSettings() async {
        let harness = Harness()
        harness.draftConsumes = true

        XCTAssertTrue(harness.monitor.handle(.larger))
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.draftShortcuts, [.larger])
        XCTAssertEqual(harness.applied, [])
        XCTAssertEqual(harness.persisted, [])
        XCTAssertEqual(harness.settings?.textScale, 1.0)
    }

    func testAPressFallsBackToTheSavedSettingsWhenThereIsNoDraft() async {
        let harness = Harness()

        XCTAssertTrue(harness.monitor.handle(.larger))
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.draftShortcuts, [.larger])
        XCTAssertEqual(harness.applied, [1.1])
        XCTAssertEqual(harness.persisted, [1.1])
    }

    func testPressesAreLeftAloneBeforeTheSettingsAreLoaded() async {
        let harness = Harness(loaded: false)

        XCTAssertFalse(harness.monitor.handle(.larger))
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.applied, [])
        XCTAssertEqual(harness.persisted, [])
    }

    func testAFailedSaveKeepsTheAppliedSizeAndAllowsTheNextPress() async {
        let harness = Harness()
        harness.failSaves = true

        harness.monitor.handle(.larger)
        await harness.monitor.waitForPendingSave()
        XCTAssertEqual(harness.settings?.textScale, 1.1)
        XCTAssertEqual(harness.persisted, [1.1])

        harness.failSaves = false
        harness.monitor.handle(.larger)
        await harness.monitor.waitForPendingSave()
        XCTAssertEqual(harness.persisted, [1.1, 1.25])
    }

    func testOtherAppearanceSettingsAreCarriedUnchangedIntoTheSave() async {
        let harness = Harness()
        harness.settings?.preferredFont = "Menlo"

        harness.monitor.handle(.larger)
        await harness.monitor.waitForPendingSave()

        XCTAssertEqual(harness.settings?.preferredFont, "Menlo")
    }

    func testAnUnmarkedResponderIsNotComposingText() {
        XCTAssertFalse(TextSizeShortcutMonitor.isComposingText(in: nil))
        XCTAssertFalse(TextSizeShortcutMonitor.isComposingText(in: NSResponder()))
    }
}
