import { UseCase } from './types';

const EmailContext = () => (
  <div className="w-full bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col" style={{ height: '320px' }}>
    {/* Window chrome */}
    <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-100 border-b border-gray-200">
      <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
      <span className="ml-2 text-xs text-gray-500">Mail</span>
    </div>
    {/* Email content */}
    <div className="flex-1 p-4 text-sm overflow-hidden">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="font-semibold text-gray-900">Sarah Chen</div>
          <div className="text-xs text-gray-500">sarah.chen@figma.com</div>
        </div>
        <div className="text-xs text-gray-400">Today, 2:34 PM</div>
      </div>
      <div className="text-gray-700 leading-relaxed">
        <p className="mb-2">Hey!</p>
        <p className="mb-2">Great chatting at the conference last week. Would love to grab coffee and continue our conversation about the design systems work you mentioned.</p>
        <p className="mb-2">Are you free Thursday? I know a few spots near your office.</p>
        <p>Let me know!</p>
        <p className="mt-2 text-gray-500">Sarah</p>
      </div>
      {/* Reply area */}
      <div className="mt-4 pt-3 border-t border-gray-200">
        <div className="text-xs text-gray-400 mb-2">Reply</div>
        <div className="h-16 bg-gray-50 rounded border border-gray-200 flex items-center justify-center">
          <span className="text-gray-400 text-xs">Click to compose or use Basil...</span>
        </div>
      </div>
    </div>
  </div>
);

export const emailUseCase: UseCase = {
  id: 'email',
  label: 'Email Reply',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  ),
  requestText: "Reply yes to coffee Thursday, suggest Stumptown on West 8th — it's cozy",
  outputText: `Hey Sarah!

Thursday works perfectly. How about Stumptown on West 8th around 2pm? It's got a cozy vibe — good for longer conversations.

Really looking forward to diving deeper into the design systems conversation — I have some thoughts on the token architecture you mentioned.

See you Thursday!`,
  duration: 17,
  contextComponent: <EmailContext />,
};

export default EmailContext;
