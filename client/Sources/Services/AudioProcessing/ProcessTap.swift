import SwiftUI
import AudioToolbox
import OSLog
import AVFoundation

@Observable
@available(macOS 14.0, *)
final class ProcessTap {

    typealias InvalidationHandler = (ProcessTap) -> Void

    let process: AudioProcess
    let muteWhenRunning: Bool
    private let context: String

    private(set) var errorMessage: String? = nil

    init(process: AudioProcess, muteWhenRunning: Bool = false) {
        self.process = process
        self.muteWhenRunning = muteWhenRunning
        self.context = "\(String(describing: ProcessTap.self))(\(process.name))"
    }

    @ObservationIgnored
    private var processTapID: AudioObjectID = .unknown
    @ObservationIgnored
    private var aggregateDeviceID = AudioObjectID.unknown
    @ObservationIgnored
    private var deviceProcID: AudioDeviceIOProcID?
    @ObservationIgnored
    private(set) var tapStreamDescription: AudioStreamBasicDescription?
    @ObservationIgnored
    private var invalidationHandler: InvalidationHandler?

    @ObservationIgnored
    private(set) var activated = false

    @MainActor
    func activate() {
        guard !activated else { return }
        activated = true

        #if DEBUG
        DevLogger.shared.debug(#function, context: context)
        #endif

        self.errorMessage = nil

        do {
            if #available(macOS 14.2, *) {
                #if DEBUG
                DevLogger.shared.info("Setting up process tap for \(self.process.name)", context: context)
                #endif
                try prepare(for: process.objectID)
            } else {
                errorMessage = "Process audio tapping requires macOS 14.2 or later"
                #if DEBUG
                DevLogger.shared.error("Process audio tapping requires macOS 14.2 or later", context: context)
                #endif
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("\(error)", context: context)
            #endif
            self.errorMessage = error.localizedDescription
        }
    }

    func invalidate() {
        guard activated else { return }
        defer { activated = false }

        #if DEBUG
        DevLogger.shared.debug(#function, context: context)
        DevLogger.shared.info("Invalidating tap for process: \(self.process.name)", context: context)
        #endif

        invalidationHandler?(self)
        self.invalidationHandler = nil

        if aggregateDeviceID.isValid {
            #if DEBUG
            DevLogger.shared.info("Stopping aggregate device #\(self.aggregateDeviceID)", context: context)
            #endif
            var err = AudioDeviceStop(aggregateDeviceID, deviceProcID)
            if err != noErr { 
                #if DEBUG
                DevLogger.shared.warning("Failed to stop aggregate device: \(err)", context: context)
                #endif
            }

            if let deviceProcID {
                err = AudioDeviceDestroyIOProcID(aggregateDeviceID, deviceProcID)
                if err != noErr { 
                    #if DEBUG
                    DevLogger.shared.warning("Failed to destroy device I/O proc: \(err)", context: context)
                    #endif
                }
                self.deviceProcID = nil
            }

            #if DEBUG
            DevLogger.shared.info("Destroying aggregate device #\(self.aggregateDeviceID)", context: context)
            #endif
            err = AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
            if err != noErr {
                #if DEBUG
                DevLogger.shared.warning("Failed to destroy aggregate device: \(err)", context: context)
                #endif
            }
            aggregateDeviceID = .unknown
        }

        if processTapID.isValid {
            if #available(macOS 14.2, *) {
                #if DEBUG
                DevLogger.shared.info("Destroying process tap #\(self.processTapID)", context: context)
                #endif
                let err = AudioHardwareDestroyProcessTap(processTapID)
                if err != noErr {
                    #if DEBUG
                    DevLogger.shared.warning("Failed to destroy audio tap: \(err)", context: context)
                    #endif
                }
            } else {
                #if DEBUG
                DevLogger.shared.warning("Cannot destroy process tap on macOS < 14.2", context: context)
                #endif
            }
            self.processTapID = .unknown
        }
        
        #if DEBUG
        DevLogger.shared.info("Tap invalidation complete for \(self.process.name)", context: context)
        #endif
    }

    @available(macOS 14.2, *)
    private func prepare(for objectID: AudioObjectID) throws {
        errorMessage = nil

        let tappedObjectIDs = processObjectIDsForTap(selectedObjectID: objectID)
        #if DEBUG
        DevLogger.shared.info("Creating tap description for object IDs: \(tappedObjectIDs)", context: context)
        #endif
        let tapDescription = CATapDescription(stereoMixdownOfProcesses: tappedObjectIDs)
        let tapUUID = UUID()
        tapDescription.uuid = tapUUID
        tapDescription.muteBehavior = self.muteWhenRunning ? .mutedWhenTapped : .unmuted
        #if DEBUG
        DevLogger.shared.info("Tap UUID: \(tapUUID.uuidString), mute behavior: \(self.muteWhenRunning ? "muted" : "unmuted")", context: context)
        #endif
        
        var tapID: AUAudioObjectID = .unknown
        #if DEBUG
        DevLogger.shared.info("Creating process tap via AudioHardwareCreateProcessTap", context: context)
        #endif
        var err = AudioHardwareCreateProcessTap(tapDescription, &tapID)

        guard err == noErr else {
            let errorMsg = "Process tap creation failed with error \(err)"
            #if DEBUG
            DevLogger.shared.error(errorMsg, context: context)
            #endif
            errorMessage = errorMsg
            return
        }

        #if DEBUG
        DevLogger.shared.info("Created process tap #\(tapID)", context: context)
        #endif
        self.processTapID = tapID

        #if DEBUG
        DevLogger.shared.info("Reading default system output device", context: context)
        #endif
        let systemOutputID = try AudioDeviceID.readDefaultSystemOutputDevice()
        #if DEBUG
        DevLogger.shared.info("Found system output device: #\(systemOutputID)", context: context)
        #endif

        #if DEBUG
        DevLogger.shared.info("Reading device UID for device #\(systemOutputID)", context: context)
        #endif
        let outputUID = try systemOutputID.readDeviceUID()
        #if DEBUG
        DevLogger.shared.info("Device UID: \(outputUID)", context: context)
        #endif

        let aggregateUID = UUID().uuidString
        #if DEBUG
        DevLogger.shared.info("Creating aggregate device with UID: \(aggregateUID)", context: context)
        #endif

        let description: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Tap-\(process.id)",
            kAudioAggregateDeviceUIDKey: aggregateUID,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [
                [
                    kAudioSubDeviceUIDKey: outputUID
                ]
            ],
            kAudioAggregateDeviceTapListKey: [
                [
                    kAudioSubTapDriftCompensationKey: true,
                    kAudioSubTapUIDKey: tapDescription.uuid.uuidString
                ]
            ]
        ]

        #if DEBUG
        DevLogger.shared.info("Reading audio tap stream description", context: context)
        #endif
        self.tapStreamDescription = try tapID.readAudioTapStreamBasicDescription()
        if let desc = self.tapStreamDescription {
            #if DEBUG
            DevLogger.shared.info("Stream format: \(desc.mSampleRate) Hz, \(desc.mChannelsPerFrame) channels, \(desc.mBytesPerFrame) bytes per frame", context: context)
            #endif
        }

        aggregateDeviceID = AudioObjectID.unknown
        #if DEBUG
        DevLogger.shared.info("Creating aggregate device", context: context)
        #endif
        err = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregateDeviceID)
        guard err == noErr else {
            let errorMsg = "Failed to create aggregate device: \(err)"
            #if DEBUG
            DevLogger.shared.error(errorMsg, context: context)
            #endif
            throw errorMsg
        }

        #if DEBUG
        DevLogger.shared.info("Created aggregate device #\(self.aggregateDeviceID)", context: context)
        #endif
    }

    private func processObjectIDsForTap(selectedObjectID: AudioObjectID) -> [AudioObjectID] {
        guard let selectedBundleID = selectedObjectID.readProcessBundleID() else {
            return [selectedObjectID]
        }

        let selectedParentBundleID = parentBundleIDForProcessTap(from: selectedBundleID)
        guard let processObjectIDs = try? AudioObjectID.readProcessList() else {
            return [selectedObjectID]
        }

        let relatedObjectIDs = processObjectIDs.filter { objectID in
            guard objectID.readProcessIsRunningOutput(),
                  let bundleID = objectID.readProcessBundleID() else {
                return false
            }

            return parentBundleIDForProcessTap(from: bundleID) == selectedParentBundleID
        }

        var result = relatedObjectIDs
        if !result.contains(selectedObjectID) {
            result.append(selectedObjectID)
        }

        return result.isEmpty ? [selectedObjectID] : result
    }

    private func parentBundleIDForProcessTap(from bundleID: String) -> String {
        let parts = bundleID.split(separator: ".").map(String.init)
        if let helperIndex = parts.firstIndex(where: { $0.lowercased().contains("helper") }),
           helperIndex > 0 {
            return parts[..<helperIndex].joined(separator: ".")
        }

        return AudioAppNameResolver.parentBundleID(from: bundleID)
    }

    func run(on queue: DispatchQueue, ioBlock: @escaping AudioDeviceIOBlock, invalidationHandler: @escaping InvalidationHandler) throws {
        assert(activated, "\(#function) called with inactive tap!")
        assert(self.invalidationHandler == nil, "\(#function) called with tap already active!")

        errorMessage = nil

        #if DEBUG
        DevLogger.shared.info("Running tap for process: \(self.process.name)", context: context)
        #endif

        self.invalidationHandler = invalidationHandler

        #if DEBUG
        DevLogger.shared.info("Creating I/O proc for device #\(self.aggregateDeviceID)", context: context)
        #endif
        var err = AudioDeviceCreateIOProcIDWithBlock(&deviceProcID, aggregateDeviceID, queue, ioBlock)
        guard err == noErr else { 
            let errorMsg = "Failed to create device I/O proc: \(err)"
            #if DEBUG
            DevLogger.shared.error(errorMsg, context: context)
            #endif
            throw errorMsg 
        }

        #if DEBUG
        DevLogger.shared.info("Starting audio device #\(self.aggregateDeviceID)", context: context)
        #endif
        err = AudioDeviceStart(aggregateDeviceID, deviceProcID)
        guard err == noErr else { 
            let errorMsg = "Failed to start audio device: \(err)"
            #if DEBUG
            DevLogger.shared.error(errorMsg, context: context)
            #endif
            throw errorMsg
        }
        
        #if DEBUG
        DevLogger.shared.info("Audio tap running for \(self.process.name)", context: context)
        #endif
    }

    deinit { 
        #if DEBUG
        DevLogger.shared.info("Tap for \(self.process.name) being deinitialized", context: context)
        #endif
        invalidate() 
    }

}

