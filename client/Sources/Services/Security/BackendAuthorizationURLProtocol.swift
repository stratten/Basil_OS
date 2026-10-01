import Foundation

/// Adds the host credential to backend requests sent through `URLSession.shared` by re-issuing them on a private session.
final class BackendAuthorizationURLProtocol: URLProtocol, URLSessionDataDelegate, @unchecked Sendable {
    static let handledPropertyKey = "BasilBackendAuthorizationHandled"
    private static let bodyReadChunkSize = 64 * 1024

    private var forwardingSession: URLSession?
    private var forwardingTask: URLSessionDataTask?
    private var clientRunLoop: CFRunLoop?
    private var clientRunLoopModes: [String] = [CFRunLoopMode.defaultMode.rawValue as String]

    static func canHandle(_ request: URLRequest, backendPort: Int) -> Bool {
        guard URLProtocol.property(forKey: handledPropertyKey, in: request) == nil,
              request.value(forHTTPHeaderField: BackendAuthorization.tokenHeader) == nil,
              let url = request.url,
              url.scheme?.lowercased() == "http" else {
            return false
        }
        return BackendAuthorization.isBackendURL(url, backendPort: backendPort)
    }

    override class func canInit(with request: URLRequest) -> Bool {
        canHandle(request, backendPort: APIClient.shared.currentPort)
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        clientRunLoop = CFRunLoopGetCurrent()
        if let currentMode = RunLoop.current.currentMode, currentMode != .default {
            clientRunLoopModes = [currentMode.rawValue, CFRunLoopMode.defaultMode.rawValue as String]
        }

        let forwardedRequest = Self.forwardedRequest(from: request)
        let configuration = URLSessionConfiguration.default
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        let task = session.dataTask(with: forwardedRequest)
        forwardingSession = session
        forwardingTask = task
        task.resume()
    }

    override func stopLoading() {
        forwardingTask?.cancel()
        forwardingTask = nil
        forwardingSession?.invalidateAndCancel()
        forwardingSession = nil
    }

    static func forwardedRequest(from original: URLRequest) -> URLRequest {
        guard let mutableRequest = (original as NSURLRequest).mutableCopy() as? NSMutableURLRequest else {
            return original
        }
        URLProtocol.setProperty(true, forKey: handledPropertyKey, in: mutableRequest)
        if mutableRequest.httpBody == nil, let bodyStream = mutableRequest.httpBodyStream {
            let body = readAll(from: bodyStream)
            mutableRequest.httpBodyStream = nil
            mutableRequest.httpBody = body
        }
        return BackendAuthorization.authorizedRequest(
            mutableRequest as URLRequest,
            credentialStore: .shared,
            backendPort: APIClient.shared.currentPort
        )
    }

    private static func readAll(from stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: bodyReadChunkSize)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 {
                break
            }
            body.append(buffer, count: count)
        }
        return body
    }

    private func performOnClientThread(_ block: @escaping () -> Void) {
        guard let clientRunLoop else {
            block()
            return
        }
        CFRunLoopPerformBlock(clientRunLoop, clientRunLoopModes as CFArray, block)
        CFRunLoopWakeUp(clientRunLoop)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        performOnClientThread { [weak self] in
            guard let self else { return }
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        performOnClientThread { [weak self] in
            guard let self else { return }
            self.client?.urlProtocol(self, didLoad: data)
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(
            BackendAuthorization.redirectRequest(
                request,
                credentialStore: .shared,
                backendPort: APIClient.shared.currentPort
            )
        )
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        performOnClientThread { [weak self] in
            guard let self else { return }
            if let error {
                self.client?.urlProtocol(self, didFailWithError: error)
            } else {
                self.client?.urlProtocolDidFinishLoading(self)
            }
        }
        session.finishTasksAndInvalidate()
    }
}
