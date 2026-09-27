import { UseCase } from './types';

const CalendarContext = () => (
  <div className="w-full bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col" style={{ height: '300px' }}>
    {/* Window chrome */}
    <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-100 border-b border-gray-200">
      <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
      <span className="ml-2 text-xs text-gray-500">Calendar</span>
    </div>
    {/* Meeting details */}
    <div className="flex-1 p-4 text-sm overflow-hidden">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-3 h-3 rounded bg-blue-500" />
          <span className="font-semibold text-gray-900">Q4 Renewal Discussion</span>
        </div>
        <div className="text-xs text-gray-600 space-y-1">
          <div className="flex items-center gap-2">
            <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>In 10 minutes (3:00 PM)</span>
          </div>
          <div className="flex items-center gap-2">
            <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span>Marcus Webb, Julia Torres</span>
          </div>
          <div className="flex items-center gap-2">
            <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            <span>Meridian Partners ($48k ARR)</span>
          </div>
        </div>
      </div>
      <div className="text-xs text-gray-500">
        <div className="font-medium text-gray-700 mb-1">Notes from last meeting:</div>
        <p>Demoed analytics features. Sarah mentioned budget concerns for Q4. They asked about annual discount options.</p>
      </div>
    </div>
  </div>
);

export const meetingUseCase: UseCase = {
  id: 'meeting',
  label: 'Meeting Prep',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  requestText: "Quick — prep me for this call. What do I need to know?",
  outputText: `Meridian Partners - Quick Prep:

From your CRM:
• $48k ARR, contract renews Dec 15 (5 weeks out)
• Julia Torres is your champion; Marcus is final decision-maker
• 3 support tickets last month — all resolved, but watch for frustration

From your email (yesterday):
Julia mentioned they're evaluating a competitor (looks like Lattice based on context). She asked if you could "sharpen the pencil" on pricing.

From Slack #deals:
Sarah closed a similar account last week at 18% annual discount. Template in the channel.

From your last meeting notes:
They loved the analytics demo but want SSO before expanding to more teams. Engineering said Q1 for SSO.

Suggested approach:
1. Acknowledge the competitor eval — don't be defensive
2. Lead with the SSO timeline (shows you remember)
3. If pricing comes up, you can go to 18% with annual commit

Opening line: "Before we dive in, I wanted to follow up on the SSO question from last time — I have an update."`,
  duration: 27,
  contextComponent: <CalendarContext />,
};

export default CalendarContext;
