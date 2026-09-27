import SwiftUI
import Combine

enum AudioEventType {
    case none
    case transient
    case sustained
    case decay
    case attack
}

class AudioSpring: ObservableObject {
    @Published var currentValue: Double = 0.0

    private var targetValue: Double = 0.0
    private var velocity: Double = 0.0

    var stiffness: Double = 300.0
    var damping: Double = 30.0
    var mass: Double = 1.0

    func update(target: Double, deltaTime: Double) {
        let safeTarget = target.isFinite ? min(max(target, 0.0), 4.0) : 0.0
        let safeDeltaTime = deltaTime.isFinite ? min(max(deltaTime, 0.0), 0.1) : 0.0
        self.targetValue = safeTarget
        let displacement = currentValue - targetValue
        let springForce = -stiffness * displacement
        let dampingForce = -damping * velocity
        let acceleration = (springForce + dampingForce) / mass

        velocity += acceleration * safeDeltaTime
        currentValue += velocity * safeDeltaTime

        guard currentValue.isFinite, velocity.isFinite else {
            currentValue = targetValue
            velocity = 0.0
            return
        }

        velocity = min(max(velocity, -20.0), 20.0)
        currentValue = min(max(currentValue, 0.0), 4.0)

        if abs(displacement) < 0.001 && abs(velocity) < 0.001 {
            currentValue = targetValue
            velocity = 0.0
        }
    }

    func adaptToAudioCharacteristics(
        bassLevel: Double,
        trebleLevel: Double,
        audioEvent: AudioEventType,
        audioVelocity: Double
    ) {
        var newStiffness = 200.0
        var newDamping = 25.0
        var newMass = 1.0

        newMass += bassLevel * 2.0
        newStiffness -= bassLevel * 50.0
        newMass = max(0.1, newMass - trebleLevel * 0.5)
        newStiffness += trebleLevel * 100.0

        switch audioEvent {
        case .transient:
            newStiffness += 150.0
            newDamping += 10.0
        case .sustained:
            newDamping += 20.0
            newStiffness -= 50.0
        case .attack:
            newStiffness += 100.0
        case .decay:
            newDamping += 30.0
        case .none:
            newDamping += 15.0
        }

        newStiffness += abs(audioVelocity) * 100.0
        stiffness = (stiffness * 0.6) + (newStiffness * 0.4)
        damping = (damping * 0.6) + (newDamping * 0.4)
        mass = (mass * 0.7) + (newMass * 0.3)

        stiffness = max(50.0, min(800.0, stiffness))
        damping = max(5.0, min(100.0, damping))
        mass = max(0.1, min(5.0, mass))
    }
}

@MainActor
class AudioLevelViewModel: ObservableObject {
    @Published var currentLevel: Double = 0.0
    @Published var isProcessing: Bool = false
    @Published var currentTime: Double = 0.0
    @Published var bubbleBaseColor: Color = Color(red: 0/255, green: 48/255, blue: 135/255)
    @Published var bubbleAccentColor: Color = .white

    private var animationTimer: AnyCancellable?
    private var audioLevelSubscription: AnyCancellable?
    private var smoothedLevel: Double = 0.0
    private var previousRawLevel: Double = 0.0
    private var previousSmoothedLevel: Double = 0.0

    @Published var bassLevel: Double = 0.0
    @Published var midLevel: Double = 0.0
    @Published var trebleLevel: Double = 0.0
    @Published var audioVelocity: Double = 0.0
    @Published var audioEventType: AudioEventType = .none

    private let baseSmoothingFactor: Double = 0.08
    private let adaptiveSmoothingFactor: Double = 0.25
    private let maxLevelJump: Double = 0.15
    private let noiseThreshold: Double = 0.008
    private var levelHistory: [Double] = []
    private let historySize = 5
    private var previousEventDetectionTime: Double = 0.0
    private let eventCooldown: Double = 0.1

    private var levelSpring = AudioSpring()
    private var opacitySpring = AudioSpring()
    private var sizeSpring = AudioSpring()
    private var blurSpring = AudioSpring()

    @Published var springLevel: Double = 0.0
    @Published var springOpacity: Double = 0.0
    @Published var springSize: Double = 0.0
    @Published var springBlur: Double = 0.0

    @Published var currentAnimationMode: AnimatedBubbleView.AnimationMode = .ambient
    private var targetAnimationMode: AnimatedBubbleView.AnimationMode = .ambient
    @Published var modeTransitionProgress: Double = 1.0
    private let modeTransitionSpeed: Double = 3.0

    var targetMode: AnimatedBubbleView.AnimationMode {
        targetAnimationMode
    }

    init(audioCaptureService: AudioCaptureService? = nil) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            guard let self else { return }

            self.animationTimer = Timer.publish(every: 0.03, on: .main, in: .common)
                .autoconnect()
                .sink { [weak self] _ in
                    guard let self else { return }
                    self.currentTime = Date().timeIntervalSinceReferenceDate
                    self.updateSpringPhysics()
                }
        }

        if let captureService = audioCaptureService {
            setupAudioCaptureSubscription(captureService)
        }
    }

    deinit {
        animationTimer?.cancel()
        audioLevelSubscription?.cancel()
    }

    func ingestAudioLevel(_ rawLevel: Double) {
        let safeLevel = rawLevel.isFinite ? min(max(rawLevel, 0.0), 1.0) : 0.0
        analyzeAudioFrequencies(safeLevel)
        calculateAudioVelocity(safeLevel)
        detectAudioEvents(safeLevel)
        smoothedLevel = applyAdvancedSmoothing(safeLevel)
        currentLevel = smoothedLevel
    }

    private func setupAudioCaptureSubscription(_ captureService: AudioCaptureService) {
        audioLevelSubscription = captureService.$audioLevel
            .receive(on: DispatchQueue.main)
            .sink { [weak self] level in
                self?.ingestAudioLevel(Double(level))
            }
    }

    private func analyzeAudioFrequencies(_ rawLevel: Double) {
        let levelChange = abs(rawLevel - previousRawLevel)
        let bassTarget = rawLevel * 0.8 + (rawLevel > 0.3 ? 0.2 : 0.0)
        bassLevel = (bassLevel * 0.85) + (bassTarget * 0.15)

        let midTarget = rawLevel * 0.9
        midLevel = (midLevel * 0.75) + (midTarget * 0.25)

        let trebleTarget = min(1.0, levelChange * 3.0 + rawLevel * 0.3)
        trebleLevel = (trebleLevel * 0.6) + (trebleTarget * 0.4)
    }

    private func calculateAudioVelocity(_ rawLevel: Double) {
        levelHistory.append(rawLevel)
        if levelHistory.count > historySize {
            levelHistory.removeFirst()
        }

        if levelHistory.count >= 2 {
            let recentChange = levelHistory.last! - levelHistory[levelHistory.count - 2]
            let smoothedVelocity = (audioVelocity * 0.7) + (recentChange * 0.3)
            audioVelocity = max(-1.0, min(1.0, smoothedVelocity))
        }
    }

    private func detectAudioEvents(_ rawLevel: Double) {
        let currentTime = Date().timeIntervalSinceReferenceDate
        guard currentTime - previousEventDetectionTime > eventCooldown else { return }

        let levelChange = rawLevel - previousRawLevel
        let velocityMagnitude = abs(audioVelocity)

        if velocityMagnitude > 0.3 && levelChange > 0.15 {
            audioEventType = .transient
            previousEventDetectionTime = currentTime
        } else if rawLevel > 0.4 && velocityMagnitude < 0.1 {
            audioEventType = .sustained
            previousEventDetectionTime = currentTime
        } else if levelChange < -0.1 && rawLevel < previousRawLevel {
            audioEventType = .decay
            previousEventDetectionTime = currentTime
        } else if velocityMagnitude > 0.2 && levelChange > 0.05 {
            audioEventType = .attack
            previousEventDetectionTime = currentTime
        } else if velocityMagnitude < 0.05 && rawLevel < 0.1 {
            audioEventType = .none
        }
    }

    func setProcessingState(_ state: Bool) {
        isProcessing = state
    }

    func connectToAudioService(_ captureService: AudioCaptureService) {
        audioLevelSubscription?.cancel()
        setupAudioCaptureSubscription(captureService)
    }

    func setAnimationMode(_ newMode: AnimatedBubbleView.AnimationMode) {
        if newMode != targetAnimationMode {
            targetAnimationMode = newMode
            modeTransitionProgress = 0.0
        }
    }

    private func updateModeTransition(deltaTime: Double) {
        if modeTransitionProgress < 1.0 {
            modeTransitionProgress = min(1.0, modeTransitionProgress + (modeTransitionSpeed * deltaTime))
            if modeTransitionProgress >= 1.0 {
                currentAnimationMode = targetAnimationMode
            }
        }
    }

    private func applyAdvancedSmoothing(_ rawLevel: Double) -> Double {
        let levelDifference = rawLevel - previousRawLevel
        let clampedLevel: Double

        if abs(levelDifference) > maxLevelJump {
            let direction = levelDifference > 0 ? 1.0 : -1.0
            clampedLevel = previousRawLevel + (maxLevelJump * direction)
        } else {
            clampedLevel = rawLevel
        }

        let filteredLevel: Double
        if abs(clampedLevel - smoothedLevel) < noiseThreshold {
            filteredLevel = smoothedLevel
        } else {
            filteredLevel = clampedLevel
        }

        let changeMagnitude = abs(filteredLevel - smoothedLevel)
        let dynamicSmoothingFactor = changeMagnitude > 0.1
            ? adaptiveSmoothingFactor
            : baseSmoothingFactor
        let newSmoothedLevel = (dynamicSmoothingFactor * filteredLevel)
            + ((1 - dynamicSmoothingFactor) * smoothedLevel)

        previousRawLevel = rawLevel
        return newSmoothedLevel
    }

    private func updateSpringPhysics() {
        let deltaTime = 0.03
        updateModeTransition(deltaTime: deltaTime)

        levelSpring.adaptToAudioCharacteristics(
            bassLevel: bassLevel,
            trebleLevel: trebleLevel,
            audioEvent: audioEventType,
            audioVelocity: audioVelocity
        )
        opacitySpring.adaptToAudioCharacteristics(
            bassLevel: bassLevel,
            trebleLevel: trebleLevel,
            audioEvent: audioEventType,
            audioVelocity: audioVelocity
        )
        sizeSpring.adaptToAudioCharacteristics(
            bassLevel: bassLevel,
            trebleLevel: trebleLevel,
            audioEvent: audioEventType,
            audioVelocity: audioVelocity
        )
        blurSpring.adaptToAudioCharacteristics(
            bassLevel: bassLevel,
            trebleLevel: trebleLevel,
            audioEvent: audioEventType,
            audioVelocity: audioVelocity
        )

        levelSpring.update(target: smoothedLevel, deltaTime: deltaTime)
        opacitySpring.update(target: smoothedLevel * 2.0, deltaTime: deltaTime)
        sizeSpring.update(target: smoothedLevel * 1.5, deltaTime: deltaTime)
        blurSpring.update(target: trebleLevel * 2.5, deltaTime: deltaTime)

        springLevel = levelSpring.currentValue
        springOpacity = opacitySpring.currentValue
        springSize = sizeSpring.currentValue
        springBlur = blurSpring.currentValue
    }
}
