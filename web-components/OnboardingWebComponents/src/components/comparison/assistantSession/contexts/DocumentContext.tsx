import { UseCase } from './types';

const DocumentContext = () => (
  <div className="w-full bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col" style={{ height: '300px' }}>
    {/* Window chrome */}
    <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-100 border-b border-gray-200">
      <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
      <span className="ml-2 text-xs text-gray-500">landing-page-v3.md</span>
    </div>
    {/* Document content */}
    <div className="flex-1 p-4 font-mono text-sm overflow-hidden">
      <div className="text-gray-400 text-xs mb-3"># Hero Section</div>
      <div className="mb-4">
        <span className="text-purple-600">## </span>
        <span className="text-gray-900">Headline</span>
      </div>
      <div className="bg-yellow-50 border-l-2 border-yellow-400 pl-3 py-2 mb-4">
        <p className="text-gray-700 leading-relaxed">
          Our platform provides users with the ability to leverage AI-powered automation to streamline their daily workflows and increase productivity.
        </p>
        <div className="text-xs text-yellow-600 mt-2">← needs work</div>
      </div>
      <div className="text-gray-400 text-xs mb-2"># Features</div>
      <div className="text-gray-600 text-xs">
        <p>- Automated task management</p>
        <p>- Smart scheduling</p>
        <p>- Team collaboration</p>
      </div>
    </div>
  </div>
);

export const writingUseCase: UseCase = {
  id: 'writing',
  label: 'Writing Help',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
    </svg>
  ),
  requestText: "This highlighted paragraph is too corporate. Make it punchy",
  outputText: `Here's a rewrite:

Before:
"Our platform provides users with the ability to leverage AI-powered automation to streamline their daily workflows and increase productivity."

After:
"AI that actually does things. Not another chat window — a teammate that handles your busywork while you focus on what matters."

What I changed:
• Cut the jargon ("leverage", "streamline", "workflows")
• Made it concrete: "does things" vs. abstract promises
• Added contrast: "Not another chat window"
• Made it personal: "your busywork", "what matters"

This matches the direct tone in your Features section.`,
  duration: 20,
  contextComponent: <DocumentContext />,
};

export default DocumentContext;
