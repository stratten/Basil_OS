import { UseCase } from './types';

const ResearchContext = () => (
  <div className="w-full bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col" style={{ height: '260px' }}>
    {/* Window chrome */}
    <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-100 border-b border-gray-200">
      <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
      <div className="ml-2 flex-1 bg-white rounded px-2 py-0.5 text-xs text-gray-500 border border-gray-200">
        docs.google.com/spreadsheets/d/series-a-benchmarks
      </div>
    </div>
    {/* Spreadsheet content */}
    <div className="flex-1 p-2 text-xs overflow-hidden bg-gray-50">
      <div className="bg-white border border-gray-200 rounded">
        <div className="grid grid-cols-4 text-[10px]">
          <div className="bg-gray-100 border-b border-r border-gray-200 p-1.5 font-medium">Metric</div>
          <div className="bg-gray-100 border-b border-r border-gray-200 p-1.5 font-medium">Our Co.</div>
          <div className="bg-gray-100 border-b border-r border-gray-200 p-1.5 font-medium">Target</div>
          <div className="bg-gray-100 border-b border-gray-200 p-1.5 font-medium">Benchmark?</div>
          
          <div className="border-b border-r border-gray-200 p-1.5">CAC</div>
          <div className="border-b border-r border-gray-200 p-1.5">$380</div>
          <div className="border-b border-r border-gray-200 p-1.5 bg-yellow-50">???</div>
          <div className="border-b border-gray-200 p-1.5 bg-yellow-50">Need data</div>
          
          <div className="border-b border-r border-gray-200 p-1.5">LTV:CAC</div>
          <div className="border-b border-r border-gray-200 p-1.5">4.2:1</div>
          <div className="border-b border-r border-gray-200 p-1.5 bg-yellow-50">???</div>
          <div className="border-b border-gray-200 p-1.5 bg-yellow-50">Need data</div>
          
          <div className="border-r border-gray-200 p-1.5">Payback</div>
          <div className="border-r border-gray-200 p-1.5">14 mo</div>
          <div className="border-r border-gray-200 p-1.5 bg-yellow-50">???</div>
          <div className="p-1.5 bg-yellow-50">Need data</div>
        </div>
      </div>
      <div className="mt-2 text-[10px] text-gray-500 italic">
        Preparing for board meeting — need Series A benchmarks
      </div>
    </div>
  </div>
);

export const researchUseCase: UseCase = {
  id: 'research',
  label: 'Quick Research',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
    </svg>
  ),
  requestText: "What are the Series A benchmarks for these metrics? I need to fill in the target column",
  outputText: `For Series A B2B SaaS, here are your benchmarks:

CAC:
• SMB: $200-$500
• Mid-market: $1,000-$3,000
• Your $380 is solid for SMB-focused

LTV:CAC Ratio:
• Minimum viable: 3:1
• Strong: 5:1+
• Your 4.2:1 is healthy

Payback Period:
• Target: 12-18 months
• Top quartile: <12 months
• Your 14 months is on track

Overall: You're performing well against benchmarks. The board will likely focus on how to improve payback period.`,
  duration: 19,
  contextComponent: <ResearchContext />,
};

export default ResearchContext;
