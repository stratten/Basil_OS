# Basil Onboarding Web Components

React components for embedding polished, animated demos in the Basil Swift app's onboarding flow via WKWebView.

## Components Available

### Full Galleries
- **UseCaseGallery** - Interactive demo with email, Slack, research, etc.
- **WorkflowComparison** - "ChatGPT Shuffle" vs "With Basil" side-by-side
- **CompactFeatureCards** - Feature showcase with mini mockups

### Individual Mocks
- **AssistantSessionWidgetMock** - The Basil capture/response widget
- **MockEmailWindow** - Email client mock
- **MockBrowserWindow** - Browser with ChatGPT mock
- **MockChatInterface** - ChatGPT conversation mock
- **BasilWireframeWrapper** - Animated wireframe wrapper
- **DrawingWindow** - App window with drawing animation

### Context Mocks (App Scenarios)
- **EmailContext** - Email composition
- **SlackContext** - Slack message thread
- **IMessageContext** - iMessage conversation
- **ResearchContext** - Research/browser context
- **CalendarContext** - Calendar view
- **CodeEditorContext** - Code editing
- **DocumentContext** - Document editing

## Development

```bash
npm install
npm run dev
```

## Building for Swift Embedding

```bash
npm run build
```

Output goes to `dist/` - copy these files to the `client` target's Resources.

## Using in Swift

```swift
struct OnboardingDemoView: NSViewRepresentable {
    let demoName: String // e.g., "single-demo", "use-case-gallery"
    
    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.setValue(false, forKey: "drawsBackground")
        
        // Optionally inject config before loading
        let script = """
        window.basilDemoConfig = {
            context: 'email',
            requestText: 'Draft a reply...',
            outputText: 'Hi there...',
            autoPlay: true
        };
        """
        webView.evaluateJavaScript(script, completionHandler: nil)
        
        if let htmlURL = Bundle.main.url(forResource: demoName, 
                                          withExtension: "html",
                                          subdirectory: "OnboardingWebAssets") {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: htmlURL.deletingLastPathComponent())
        }
        return webView
    }
    
    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
```

## Drip-Feeding Demos

For progressive onboarding, use the `SingleDemo` component with different configs:

1. **First encounter**: Show email context with simple request
2. **Second step**: Show Slack context  
3. **Third step**: Show research context
4. **Power user**: Show full UseCaseGallery

Configure via `window.basilDemoConfig` before page load.
