import SwiftUI

struct AnimatedBubbleView: View {
    @ObservedObject var viewModel: AudioLevelViewModel

    enum AnimationMode {
        case audioResponsive
        case processing
        case ambient
    }

    let bubbleSize: CGFloat
    let animationMode: AnimationMode
    let numberOfCapsules = 8

    init(
        viewModel: AudioLevelViewModel,
        bubbleSize: CGFloat = 120,
        animationMode: AnimationMode = .audioResponsive
    ) {
        self.viewModel = viewModel
        self.bubbleSize = bubbleSize
        self.animationMode = animationMode
        viewModel.setAnimationMode(animationMode)
    }

    var body: some View {
        ZStack {
            Circle()
                .fill(viewModel.bubbleBaseColor)
                .animation(.easeInOut(duration: 0.5), value: viewModel.bubbleBaseColor)

            ForEach(0..<numberOfCapsules, id: \.self) { index in
                Capsule()
                    .fill(viewModel.bubbleAccentColor.opacity(capsuleOpacity(for: index)))
                    .frame(width: capsuleWidth(), height: capsuleHeight(for: index))
                    .blur(radius: capsuleBlurRadius(for: index))
                    .blendMode(.screen)
                    .animation(.easeInOut(duration: 0.5), value: viewModel.bubbleAccentColor)
                    .rotationEffect(capsuleRotationAngle(for: index))
                    .offset(x: capsuleOffsetX(for: index), y: capsuleOffsetY(for: index))
                    .animation(.linear(duration: 0.03), value: viewModel.currentTime)
            }
        }
        .frame(width: bubbleSize, height: bubbleSize)
        .clipShape(Circle())
        .scaleEffect(bubbleScaleEffect())
        .allowsHitTesting(false)
        .animation(.linear(duration: 0.03), value: viewModel.currentTime)
    }

    private func capsuleOpacity(for index: Int) -> Double {
        let baseOpacity = 0.2 + Double(index) * 0.05
        return blendedValue(
            for: { mode in
                opacity(for: mode, baseOpacity: baseOpacity, capsuleIndex: index)
            }
        )
    }

    private func opacity(
        for mode: AnimationMode,
        baseOpacity: Double,
        capsuleIndex: Int
    ) -> Double {
        switch mode {
        case .audioResponsive:
            let peakOpacity = min(1.0, baseOpacity + (viewModel.springOpacity * 1.44 * 0.96))
            return pow(peakOpacity, 0.4)
        case .processing:
            let phase = (viewModel.currentTime * 1.5) + Double(capsuleIndex) * 0.8
            return min(1.0, baseOpacity + (pow((sin(phase) + 1) / 2, 0.5) * 0.9))
        case .ambient:
            let phase = (viewModel.currentTime * 0.3) + Double(capsuleIndex) * 0.5
            return min(1.0, baseOpacity + (pow((sin(phase) + 1) / 2, 0.6) * 0.4))
        }
    }

    private func capsuleWidth() -> CGFloat {
        bubbleSize * 0.12
    }

    private func capsuleHeight(for index: Int) -> CGFloat {
        let baseHeight = bubbleSize * 0.18
        let primaryWave = (sin((viewModel.currentTime * 2.0) + Double(index) * 0.7) + 1) / 2
        let secondaryWave = (cos((viewModel.currentTime * 0.8) + Double(index) * 0.3) + 1) / 2
        let waveStretch = (primaryWave * 0.7) + (secondaryWave * 0.3)
        return baseHeight + (waveStretch * bubbleSize * 0.08)
            + blendedValue(for: { heightStretch(for: $0, capsuleIndex: index) })
    }

    private func heightStretch(for mode: AnimationMode, capsuleIndex: Int) -> Double {
        switch mode {
        case .audioResponsive:
            return (viewModel.springSize + (viewModel.bassLevel * 0.48) + (viewModel.trebleLevel * 0.36))
                * bubbleSize * 0.42
        case .processing:
            let phase = (viewModel.currentTime * 1.2) + Double(capsuleIndex) * 0.6
            return ((sin(phase) + 1) / 2) * bubbleSize * 0.25
        case .ambient:
            let phase = (viewModel.currentTime * 0.4) + Double(capsuleIndex) * 0.3
            return ((sin(phase) + 1) / 2) * bubbleSize * 0.1
        }
    }

    private func capsuleBlurRadius(for index: Int) -> CGFloat {
        let baseBlur = 2 + CGFloat(index) * 0.8
        return baseBlur + blendedValue(for: { blur(for: $0, capsuleIndex: index) })
    }

    private func blur(for mode: AnimationMode, capsuleIndex: Int) -> Double {
        switch mode {
        case .audioResponsive:
            return viewModel.springOpacity * 2.4
        case .processing:
            let phase = (viewModel.currentTime * 1.0) + Double(capsuleIndex) * 0.5
            return ((sin(phase) + 1) / 2) * 3
        case .ambient:
            let phase = (viewModel.currentTime * 0.2) + Double(capsuleIndex) * 0.4
            return ((sin(phase) + 1) / 2) * 1.5
        }
    }

    private func capsuleRotationAngle(for index: Int) -> Angle {
        let continuousRotation = viewModel.currentTime * 5.0
        let primaryRotation = sin((viewModel.currentTime * 2.0) + Double(index) * 0.7) * 30.0
        let secondaryRotation = cos((viewModel.currentTime * 1.2) + Double(index) * 0.5) * 15.0
        return .degrees(continuousRotation + primaryRotation + secondaryRotation + Double(index) * 10)
    }

    private func capsuleOffsetX(for index: Int) -> CGFloat {
        let angle = capsuleInitialAngle(for: index)
        return capsuleRadialDistance(for: index) * cos(angle.radians)
    }

    private func capsuleOffsetY(for index: Int) -> CGFloat {
        let angle = capsuleInitialAngle(for: index)
        return capsuleRadialDistance(for: index) * sin(angle.radians)
    }

    private func capsuleInitialAngle(for index: Int) -> Angle {
        .degrees((Double(index) * (360.0 / Double(numberOfCapsules))) + (Double(index) * 7.3))
    }

    private func capsuleRadialDistance(for index: Int) -> CGFloat {
        let baseDistance = bubbleSize * 0.05
        let primaryWave = (sin((viewModel.currentTime * 2.0) + Double(index) * 0.7) + 1) / 2
        let secondaryWave = (cos((viewModel.currentTime * 0.9) + Double(index) * 0.4) + 1) / 2
        let combinedWave = (primaryWave * 0.6) + (secondaryWave * 0.4)
        let springInfluence = viewModel.springLevel * bubbleSize * 0.24
        let bassInfluence = viewModel.bassLevel * bubbleSize * 0.18
        return baseDistance + (combinedWave * bubbleSize * 0.1) + springInfluence + bassInfluence
    }

    private func bubbleScaleEffect() -> CGFloat {
        let scale = blendedValue(for: scale(for:))
        guard scale.isFinite else {
            return 1.0
        }
        return min(max(scale, 0.96), 1.18)
    }

    private func scale(for mode: AnimationMode) -> CGFloat {
        switch mode {
        case .audioResponsive:
            let baseScale = 1.0 + sin(viewModel.currentTime * 0.5) * 0.02
            let springScale = viewModel.springSize * 0.144
            let velocityScale = abs(viewModel.audioVelocity) * 0.048
            let eventScale: Double
            switch viewModel.audioEventType {
            case .transient: eventScale = 0.048
            case .sustained: eventScale = 0.024
            case .attack: eventScale = 0.036
            case .decay: eventScale = 0.012
            case .none: eventScale = 0.0
            }
            return baseScale + springScale + velocityScale + eventScale
        case .processing:
            return 1.0 + sin(viewModel.currentTime * 0.8) * 0.04
        case .ambient:
            return 1.0 + sin(viewModel.currentTime * 0.3) * 0.01
        }
    }

    private func blendedValue<T: BinaryFloatingPoint>(
        for value: (AnimationMode) -> T
    ) -> T {
        guard viewModel.modeTransitionProgress < 1.0 else {
            return value(viewModel.currentAnimationMode)
        }
        let oldValue = value(viewModel.currentAnimationMode)
        let newValue = value(viewModel.targetMode)
        return (oldValue * T(1.0 - viewModel.modeTransitionProgress))
            + (newValue * T(viewModel.modeTransitionProgress))
    }

    func setAnimationMode(_ newMode: AnimationMode) {
        viewModel.setAnimationMode(newMode)
    }
}

struct AnimatedBubbleView_Previews: PreviewProvider {
    static var previews: some View {
        AnimatedBubbleView(viewModel: AudioLevelViewModel())
            .previewLayout(.sizeThatFits)
            .padding()
            .background(Color.gray.opacity(0.2))
    }
}
