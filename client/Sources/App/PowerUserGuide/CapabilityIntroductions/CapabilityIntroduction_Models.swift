import SwiftUI

@MainActor
struct CapabilityIntroduction_Models: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "cpu.fill")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text("Models")
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("Basil can think locally on your Mac or use faster cloud models. The choice mostly comes down to privacy, speed, and cost.")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                
                HStack(alignment: .top, spacing: 14) {
                    ModelIntroCard(
                        icon: "mic.fill",
                        title: "Speech-to-text",
                        accent: AestheticSystem.Colors.primary,
                        bullets: [
                            "Small local models start quickly and work well for casual dictation.",
                            "Larger local models handle noisy rooms, accents, and important text better.",
                            "You can switch later; this choice is not permanent."
                        ]
                    )
                    
                    ModelIntroCard(
                        icon: "brain.head.profile",
                        title: "Thinking models",
                        accent: AestheticSystem.Colors.successBase,
                        bullets: [
                            "Local models are free, private, offline, and run on your Mac.",
                            "Cloud models are faster and better at hard requests, but each request costs money.",
                            "Basil does not track or store request contents."
                        ]
                    )
                }
                
                HStack(alignment: .top, spacing: 14) {
                    ModelIntroCard(
                        icon: "creditcard",
                        title: "Cloud pricing",
                        accent: AestheticSystem.Colors.primary,
                        bullets: [
                            "Basil Cloud requires a Basil account with a payment method before usage.",
                            "Model providers charge Basil for cloud requests; Basil passes that cost through with a small markup.",
                            "If you bring your own provider account, that provider bills you directly."
                        ]
                    )
                    
                    ModelIntroCard(
                        icon: "slider.horizontal.3",
                        title: "Advanced options",
                        accent: AestheticSystem.Colors.onboardingTextSecondary,
                        bullets: [
                            "Download GGUF models from HuggingFace by pasting a repo link.",
                            "Use existing models from disk, LM Studio, or Ollama.",
                            "Connect OpenAI-, Anthropic-, or Gemini-compatible providers from Settings."
                        ],
                        isSecondary: true
                    )
                }
                
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "lock.shield.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(AestheticSystem.Colors.successBase)
                        .frame(width: 24)
                    
                    Text("Privacy note: local models stay on your Mac. Cloud requests are sent only to the model provider needed to answer.")
                        .font(AestheticSystem.Typography.body)
                        .foregroundColor(AestheticSystem.Colors.onboardingTextPrimary)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(14)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(AestheticSystem.Colors.successBase.opacity(0.08))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(AestheticSystem.Colors.successBase.opacity(0.18), lineWidth: 1)
                )
            }
            .padding(32)
        }
    }
}

private struct ModelIntroCard: View {
    let icon: String
    let title: String
    let accent: Color
    let bullets: [String]
    var isSecondary: Bool = false
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundColor(accent)
                    .frame(width: 24)
                
                Text(title)
                    .font(AestheticSystem.Typography.headline)
                    .foregroundColor(AestheticSystem.Colors.onboardingTextPrimary)
            }
            
            VStack(alignment: .leading, spacing: 9) {
                ForEach(bullets, id: \.self) { bullet in
                    HStack(alignment: .top, spacing: 8) {
                        Circle()
                            .fill(isSecondary ? AestheticSystem.Colors.onboardingTextSecondary.opacity(0.45) : accent)
                            .frame(width: 6, height: 6)
                            .padding(.top, 7)
                        
                        Text(bullet)
                            .font(AestheticSystem.Typography.body)
                            .foregroundColor(isSecondary ? AestheticSystem.Colors.onboardingTextSecondary : AestheticSystem.Colors.onboardingTextPrimary)
                            .lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(AestheticSystem.Colors.onboardingCardBackground)
                .shadow(color: .black.opacity(0.05), radius: 3, x: 0, y: 2)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(accent.opacity(isSecondary ? 0.10 : 0.16), lineWidth: 1)
        )
    }
}

struct CapabilityIntroduction_Models_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_Models()
            .frame(width: 680, height: 520)
    }
}


