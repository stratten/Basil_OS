import SwiftUI
import Foundation

// MARK: - Aesthetic System
// Centralized design system with user-configurable primary/secondary colors and font

struct AestheticSystem {
    
    // MARK: - User Configurable Preferences
    // These are loaded from user preferences via loadFromSettings(_:).
    private static var userBackgroundColor = Color(red: 0.0709251779736389, green: 0.10432000903519285, blue: 0.22791699626277573)  // Dark navy (default) - Duke Blue theme
    private static var userPrimaryColor = Color(red: 0.376, green: 0.647, blue: 0.98)        // Light sky blue (default) - Duke Blue theme, matches agentTask buttons
    private static var userSecondaryColor = Color(red: 0.21100852777444695, green: 0.4699344845863317, blue: 0.8893695758678611)  // Medium blue (default) - Duke Blue theme
    private static var userTextColor = Color(red: 0.9699399998499855, green: 0.9902393003857255, blue: 1.0)  // Near-white (default) - Duke Blue theme
    private static var userPreferredFont = "Helvetica-Light" // Default font
    private static var userSurfaceFinish = "flat"

    // Processing bubble colors. Royal Purple defaults (#7C3AED base /
    // #DDD6FE accent) are intentionally distinct from idle blue and from
    // success/active green so "Basil is working" reads as a unique state
    // across the entire app. The two literals on `Colors.defaultProcessingBase`
    // / `defaultProcessingAccent` below are the ONLY hand-edited processing-
    // color values in the entire repo. The build-time generator
    // `scripts/generate_processing_color_defaults.py` parses those literals
    // and regenerates Python and TypeScript defaults so backend prefs and
    // both React bundles stay in sync without manual updates.
    //
    // The user-facing accessors (`processingBase`, `processingAccent`,
    // `bubbleColors(for: .processing)`) read from the mutable `userProcessing*`
    // storage so `loadFromSettings(_:)` can swap in persisted user choices at
    // runtime. React surfaces receive the active value through the WKWebView
    // theme bridge.
    private static var userProcessingBase = Colors.defaultProcessingBase
    private static var userProcessingAccent = Colors.defaultProcessingAccent

    /// Last revision received from an `appearance_updated` backend event.
    private(set) static var currentAppearanceRevision = 0
    
    // MARK: - Typography
    struct Typography {
        
        // Font name variants based on user preference
        private static var baseFontName: String { userPreferredFont }
        private static var mediumFontName: String { 
            userPreferredFont == "Helvetica-Light" ? "Helvetica" : "\(userPreferredFont.replacingOccurrences(of: "-Light", with: ""))"
        }
        private static var boldFontName: String { 
            userPreferredFont == "Helvetica-Light" ? "Helvetica-Bold" : "\(userPreferredFont.replacingOccurrences(of: "-Light", with: "-Bold"))"
        }
        
        // Public access to font name
        static var preferredFontName: String { baseFontName }
        
        // Font creation with fallback
        private static func customFont(size: CGFloat, weight: Font.Weight = .light) -> Font {
            switch weight {
            case .bold:
                return .custom(boldFontName, size: size)
            case .medium, .semibold:
                return .custom(mediumFontName, size: size)
            default:
                return .custom(baseFontName, size: size)
            }
        }
        
        // Semantic Typography Scale
        //
        // These are computed properties (`static var`), not cached `static
        // let` constants. `customFont(...)` reads `userPreferredFont`, which
        // is a mutable var updated by `updatePreferredFont(_:)`. A cached
        // `static let` would freeze whichever font was current the first
        // time it was touched, so any later font change would silently stop
        // applying to newly created windows. Computed properties re-run
        // `customFont(...)` on every access, so a window created after a
        // font change always reflects the current preference. Callers are
        // unaffected: `AestheticSystem.Typography.body` reads identically
        // whether the underlying declaration is `let` or `var`.
        static var largeTitle: Font { customFont(size: 28, weight: .light) }
        static var title1: Font { customFont(size: 24, weight: .light) }
        static var title2: Font { customFont(size: 20, weight: .light) }
        static var title3: Font { customFont(size: 18, weight: .medium) }
        
        static var headline: Font { customFont(size: 16, weight: .light) }
        static var subheadline: Font { customFont(size: 14, weight: .medium) }
        
        static var body: Font { customFont(size: 14, weight: .light) }
        static var bodyMedium: Font { customFont(size: 14, weight: .medium) }
        static var bodyEmphasized: Font { customFont(size: 14, weight: .bold) }
        
        static var callout: Font { customFont(size: 13, weight: .light) }
        static var calloutMedium: Font { customFont(size: 13, weight: .medium) }
        
        static var footnote: Font { customFont(size: 12, weight: .light) }
        static var footnoteMedium: Font { customFont(size: 12, weight: .medium) }
        
        static var button: Font { customFont(size: 14, weight: .medium) }
        static var buttonLarge: Font { customFont(size: 16, weight: .medium) }
        static var caption: Font { customFont(size: 12, weight: .light) }
        static var captionMedium: Font { customFont(size: 12, weight: .medium) }
        
        // Specialized fonts. `code`/`codeSmall` stay `static let`: they use
        // the fixed system monospaced font and do not depend on
        // `userPreferredFont`, so caching them is correct and cheaper.
        static let code = Font.system(size: 13, weight: .regular, design: .monospaced)
        static let codeSmall = Font.system(size: 11, weight: .regular, design: .monospaced)
        static var statusSmall: Font { customFont(size: 11, weight: .medium) }
        static var statusTiny: Font { customFont(size: 10, weight: .medium) }
        
        // NSFont variants for AppKit components
        struct NSFonts {
            static var body: NSFont { NSFont(name: baseFontName, size: 14) ?? NSFont.systemFont(ofSize: 14, weight: .light) }
            static var bodyMedium: NSFont { NSFont(name: mediumFontName, size: 14) ?? NSFont.systemFont(ofSize: 14, weight: .medium) }
            static var bodyBold: NSFont { NSFont(name: boldFontName, size: 14) ?? NSFont.systemFont(ofSize: 14, weight: .bold) }
            static var headline: NSFont { NSFont(name: mediumFontName, size: 16) ?? NSFont.systemFont(ofSize: 16, weight: .medium) }
            static var caption: NSFont { NSFont(name: baseFontName, size: 12) ?? NSFont.systemFont(ofSize: 12, weight: .light) }
            static let code = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        }
    }
    
    // MARK: - Colors
    struct Colors {
        
        // User-configurable colors
        static var backgroundPrimary: Color { userBackgroundColor }
        static var primary: Color { userPrimaryColor }
        static var secondary: Color { userSecondaryColor }
        static var textPrimary: Color { userTextColor }
        
        // Derived colors from user preferences
        static var primaryDark: Color { 
            Color(red: max(0, userPrimaryColor.components.red - 0.08),
                  green: max(0, userPrimaryColor.components.green - 0.08),
                  blue: max(0, userPrimaryColor.components.blue - 0.08))
        }
        
        // Fixed state colors (not user-configurable)
        static let recordingBase = Color(red: 139/255, green: 0/255, blue: 0/255)      // Dark red
        static let recordingAccent = Color(red: 255/255, green: 99/255, blue: 71/255) // Orange-red accent

        // Ready bubble colors. Green signals "Basil is ready / available to
        // receive input" across transcription, AgentTask, and AssistantSession bubbles.
        // Base matches the existing Basil leaf green (successBase) so the
        // ambient/ready state reads as healthy/available, with a light mint
        // accent for contrast. These are fixed (not user-configurable) to
        // keep the green=ready / red=listening / purple=working semantics
        // consistent across surfaces.
        static let readyBase = Color(red: 52/255, green: 135/255, blue: 56/255)        // Basil leaf green
        static let readyAccent = Color(red: 200/255, green: 240/255, blue: 203/255)    // Light mint accent
        
        // Royal Purple processing-bubble defaults.
        //
        // THESE TWO LITERALS ARE THE SINGLE SOURCE OF TRUTH for the
        // processing color across the entire repo. They are parsed at build
        // time by `scripts/generate_processing_color_defaults.py`, which
        // regenerates matching Python and TypeScript constants used by the
        // backend preferences defaults and both React bundles. Edit only
        // these two lines, then run `scripts/build-agent-task-assets.sh` (or any pipeline that calls it) to propagate the change.
        //
        // Format constraint: the generator regex requires the exact shape
        // `defaultProcessing... = Color(red: R, green: G, blue: B)`. Do not
        // reformat across lines or swap to a different color initializer
        // without updating the generator.
        public static let defaultProcessingBase = Color(red: 0.486, green: 0.227, blue: 0.929)
        public static let defaultProcessingAccent = Color(red: 0.867, green: 0.839, blue: 0.996)

        // Configurable processing bubble colors. Read through computed
        // accessors so updates via loadFromSettings(_:) propagate without
        // requiring callers to hold references to specific Color instances.
        static var processingBase: Color { userProcessingBase }
        static var processingAccent: Color { userProcessingAccent }
        
        static let warningBase = Color(red: 255/255, green: 165/255, blue: 0/255)     // Orange
        static let errorBase = Color(red: 155/255, green: 28/255, blue: 28/255)       // Brick red (#9B1C1C), matches the long-standing Conversation delete-icon red
        static let successBase: Color = Color(red: 52/255, green: 135/255, blue: 56/255)    // Basil leaf green
        
        // Fixed semantic colors
        static let textSecondary = Color.secondary
        static let textTertiary = Color.gray
        
        static let backgroundSecondary = Color(.controlBackgroundColor)
        static let backgroundTertiary = Color(.textBackgroundColor)
        
        static let separatorColor = Color(.separatorColor)
        static let borderColor = Color.gray.opacity(0.3)
        /// Border for input fields/editors and tool cards. Mirrors the
        /// transcription area outline (Duke-blue `secondary` at 0.2, lineWidth 1)
        /// so field outlines read as a consistent, lightly-weighted blue rather
        /// than a heavy neutral gray, while staying more visible than the faint
        /// system `separatorColor`.
        static var fieldBorder: Color { secondary.opacity(0.2) }
        
        // MARK: - High-Contrast Onboarding Colors
        // Simple, readable pairings: black on white, blue on white, black on light gray
        // NOT vibrant - just actual contrast
        
        /// Pure white for card backgrounds
        static let onboardingCardBackground = Color.white
        /// Pure black for primary text
        static let onboardingTextPrimary = Color.black
        /// Dark gray for secondary text (still readable, not washed out)
        static let onboardingTextSecondary = Color.black.opacity(0.7)
        /// Light gray for section backgrounds (actual light, not mid-gray)
        static let onboardingBackgroundLight = Color(white: 0.95)
        /// Blue for links/interactive elements on white
        static let onboardingLink = Color(red: 0.0, green: 0.4, blue: 0.8)
        
        // Dynamic state-based colors.
        //
        // Bubble color semantics:
        //  - .idle     → ready green   (Basil is ready to receive input)
        //  - .recording → red          (Basil is actively listening)
        //  - .processing → Royal Purple (Basil is working on the request)
        //
        // NOTE: `.idle` is retained as the enum case name for source
        // compatibility, but it represents the ambient/ready bubble state,
        // not a disabled/off state. A follow-up cleanup may rename this to
        // `.ready` across the codebase.
        static func bubbleColors(for state: BubbleState) -> (base: Color, accent: Color) {
            switch state {
            case .idle:
                return (base: readyBase, accent: readyAccent)
            case .recording:
                return (base: recordingBase, accent: recordingAccent)
            case .processing:
                return (base: processingBase, accent: processingAccent)
            }
        }
        
        enum BubbleState {
            case idle, recording, processing
        }
    }

    // MARK: - Effective Color Scheme
    /// Derives the SwiftUI `ColorScheme` a retained native window should
    /// present, based on the user's configured background color's luminance
    /// -- not the system's Light/Dark Mode setting. Mirrors the derivation
    /// used for WKWebView hosts in `AestheticWebPayload.semanticAppearance(for:)`,
    /// so native SwiftUI windows and WebView-hosted surfaces resolve to the
    /// same light/dark reading for the same background. Callers should read
    /// this fresh at window-presentation time (do not cache the result) so a
    /// window created after an appearance change reflects the current
    /// background.
    static var effectiveColorScheme: ColorScheme {
        guard let rgbColor = NSColor(Colors.backgroundPrimary).usingColorSpace(.sRGB) else {
            return .light
        }
        let luminance = (0.2126 * rgbColor.redComponent) + (0.7152 * rgbColor.greenComponent) + (0.0722 * rgbColor.blueComponent)
        return luminance < 0.5 ? .dark : .light
    }

    /// Surface treatment for web-hosted panels. "flat" preserves solid-color
    /// surfaces; "metal" adds a palette-derived brushed-metal sheen.
    static var surfaceFinish: String { userSurfaceFinish }
    
    // MARK: - Fixed Layout Constants
    struct Layout {
        static let cornerRadiusSmall: CGFloat = 6
        static let cornerRadiusMedium: CGFloat = 8
        static let cornerRadiusLarge: CGFloat = 16
        
        static let paddingXS: CGFloat = 4
        static let paddingS: CGFloat = 8
        static let paddingM: CGFloat = 12
        static let paddingL: CGFloat = 16
        static let paddingXL: CGFloat = 20
        
        static let borderThin: CGFloat = 1
        static let borderMedium: CGFloat = 2
        
        static let shadowLight = Color.black.opacity(0.03)
        static let shadowMedium = Color.black.opacity(0.05)
        static let shadowDark = Color.black.opacity(0.1)
    }
    
    // MARK: - User Preference Management
    static func updateBackgroundColor(_ color: Color) {
        userBackgroundColor = color
        // Force refresh of any computed properties that depend on this
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    static func updatePrimaryColor(_ color: Color) {
        userPrimaryColor = color
        // Force refresh of any computed properties that depend on this
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    static func updateSecondaryColor(_ color: Color) {
        userSecondaryColor = color
        // Force refresh of any computed properties that depend on this
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    static func updateTextColor(_ color: Color) {
        userTextColor = color
        // Force refresh of any computed properties that depend on this
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    static func updatePreferredFont(_ fontName: String) {
        userPreferredFont = fontName
        // Force refresh of any computed properties that depend on this
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    static func recordRemoteAppearanceRevision(_ revision: Int) {
        currentAppearanceRevision = revision
    }

    // Initialize from settings (called at app startup)
    static func loadFromSettings(_ settings: AppearanceSettings) {
        userBackgroundColor = settings.backgroundColor
        userPrimaryColor = settings.primaryColor
        userSecondaryColor = settings.secondaryColor
        userTextColor = settings.textColor
        userProcessingBase = settings.processingColor
        userProcessingAccent = settings.processingAccentColor
        userPreferredFont = settings.preferredFont
        userSurfaceFinish = settings.surfaceFinish
        
        #if DEBUG
        DevLogger.shared.info("✅ AestheticSystem loaded from settings: font=\(userPreferredFont)", context: "AestheticSystem")
        #endif
        
        // Post notification to update UI
        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)
    }
    
    // Available font options for user selection
    static let availableFonts = [
        "Helvetica-Light",
        "Arial",
        "Avenir-Light",
        "SF Pro Text",
        "Menlo"
    ]
}

// MARK: - Color Extension for RGB Components
extension Color {
    var components: (red: Double, green: Double, blue: Double, alpha: Double) {
        #if canImport(UIKit)
        typealias NativeColor = UIColor
        #elseif canImport(AppKit)
        typealias NativeColor = NSColor
        #endif
        
        var r: CGFloat = 0
        var g: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        
        NativeColor(self).getRed(&r, green: &g, blue: &b, alpha: &a)
        
        return (Double(r), Double(g), Double(b), Double(a))
    }
}

// MARK: - Convenience Extensions

extension Text {
    func headlineStyle() -> some View {
        self.font(AestheticSystem.Typography.headline)
    }
    
    func bodyStyle() -> some View {
        self.font(AestheticSystem.Typography.body)
    }
    
    func bodyMediumStyle() -> some View {
        self.font(AestheticSystem.Typography.bodyMedium)
    }
    
    func captionStyle() -> some View {
        self.font(AestheticSystem.Typography.caption)
    }
    
    func buttonTextStyle() -> some View {
        self.font(AestheticSystem.Typography.button)
    }
    
    func codeStyle() -> some View {
        self.font(AestheticSystem.Typography.code)
    }
}

extension View {
    func primaryButtonStyle() -> some View {
        self
            .font(AestheticSystem.Typography.button)
            .padding(.horizontal, AestheticSystem.Layout.paddingL)
            .padding(.vertical, AestheticSystem.Layout.paddingS)
            .background(AestheticSystem.Colors.primary)
            .foregroundColor(.white)
            .cornerRadius(AestheticSystem.Layout.cornerRadiusMedium)
    }
    
    func secondaryButtonStyle() -> some View {
        self
            .font(AestheticSystem.Typography.button)
            .padding(.horizontal, AestheticSystem.Layout.paddingL)
            .padding(.vertical, AestheticSystem.Layout.paddingS)
            .background(AestheticSystem.Colors.secondary)
            .foregroundColor(.white)
            .cornerRadius(AestheticSystem.Layout.cornerRadiusMedium)
    }
    
    func cardStyle() -> some View {
        self
            .background(AestheticSystem.Colors.backgroundPrimary)
            .cornerRadius(AestheticSystem.Layout.cornerRadiusLarge)
            .overlay(
                RoundedRectangle(cornerRadius: AestheticSystem.Layout.cornerRadiusLarge)
                    .stroke(AestheticSystem.Colors.primary.opacity(0.3), lineWidth: AestheticSystem.Layout.borderThin)
            )
    }
    
    func lightShadow() -> some View {
        self.shadow(color: AestheticSystem.Layout.shadowLight, radius: 1, x: 0, y: 1)
    }
    
    func mediumShadow() -> some View {
        self.shadow(color: AestheticSystem.Layout.shadowMedium, radius: 2, x: 0, y: 1)
    }
}

// MARK: - Preview
#if DEBUG
struct AestheticSystemPreview: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Aesthetic System Preview")
                    .font(AestheticSystem.Typography.title2)
                    .foregroundColor(AestheticSystem.Colors.primary)
                
                Group {
                    Text("Typography Examples")
                        .font(AestheticSystem.Typography.headline)
                    
                    Text("Body text using user's preferred font")
                        .bodyStyle()
                    
                    Text("Caption text for small details")
                        .captionStyle()
                }
                
                Divider()
                
                Group {
                    Text("Color Examples")
                        .font(AestheticSystem.Typography.headline)
                    
                    HStack(spacing: 12) {
                        Rectangle()
                            .fill(AestheticSystem.Colors.primary)
                            .frame(width: 60, height: 40)
                            .cornerRadius(AestheticSystem.Layout.cornerRadiusSmall)
                        
                        Rectangle()
                            .fill(AestheticSystem.Colors.secondary)
                            .frame(width: 60, height: 40)
                            .cornerRadius(AestheticSystem.Layout.cornerRadiusSmall)
                    }
                }
                
                Divider()
                
                Group {
                    Text("Component Examples")
                        .font(AestheticSystem.Typography.headline)
                    
                    Button("Primary Button") {}
                        .primaryButtonStyle()
                    
                    Button("Secondary Button") {}
                        .secondaryButtonStyle()
                    
                    VStack {
                        Text("Card Component")
                            .headlineStyle()
                        Text("Uses consistent styling")
                            .bodyStyle()
                            .foregroundColor(AestheticSystem.Colors.textSecondary)
                    }
                    .padding(AestheticSystem.Layout.paddingL)
                    .cardStyle()
                    .mediumShadow()
                }
            }
            .padding(AestheticSystem.Layout.paddingXL)
        }
        .frame(width: 400, height: 600)
    }
}

struct AestheticSystemPreview_Previews: PreviewProvider {
    static var previews: some View {
        AestheticSystemPreview()
    }
}
#endif 

// MARK: - Notification Names
extension Notification.Name {
    static let aestheticSystemUpdated = Notification.Name("aestheticSystemUpdated")
} 