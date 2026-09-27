import Foundation
@preconcurrency import WebKit

extension AgentTaskResultWebView {
    // MARK: - WKNavigationDelegate
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        DevLogger.shared.info("[AgentTaskResultWebView \(instanceId)] Page loaded, sending init", context: "AgentTaskCapture")
        #endif
        
        forceInitRetry()
    }
    
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.navigationType == .linkActivated,
           let url = navigationAction.request.url,
           let scheme = url.scheme, (scheme == "http" || scheme == "https") {
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[AgentTaskResultWebView \(instanceId)] Navigation failed: \(error.localizedDescription)", context: "AgentTaskCapture")
        #endif
    }
    
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[AgentTaskResultWebView \(instanceId)] Provisional navigation failed: \(error.localizedDescription)", context: "AgentTaskCapture")
        #endif
    }
}

