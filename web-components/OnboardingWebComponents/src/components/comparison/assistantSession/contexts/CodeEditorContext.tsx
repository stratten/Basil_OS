import { UseCase } from './types';

const CodeEditorContext = () => (
  <div className="w-full bg-[#1e1e1e] rounded-lg shadow-sm border border-gray-700 overflow-hidden flex flex-col" style={{ height: '280px' }}>
    {/* Window chrome */}
    <div className="flex items-center gap-1.5 px-3 py-2 bg-[#323233] border-b border-gray-700">
      <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
      <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
      <span className="ml-2 text-xs text-gray-400">useAutoSave.ts</span>
    </div>
    {/* Code content */}
    <div className="flex-1 p-3 font-mono text-[10px] overflow-hidden leading-relaxed">
      <div className="flex">
        <div className="text-gray-600 pr-2 select-none text-right" style={{ minWidth: '1.5rem' }}>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(n => (
            <div key={n}>{n}</div>
          ))}
        </div>
        <div className="flex-1 text-gray-300">
          <div><span className="text-purple-400">const</span> <span className="text-blue-300">useAutoSave</span> = <span className="text-yellow-300">(</span>data, onSave<span className="text-yellow-300">)</span> <span className="text-purple-400">=&gt;</span> <span className="text-yellow-300">{'{'}</span></div>
          <div className="pl-3"><span className="text-purple-400">const</span> [isSaving, setIsSaving] = <span className="text-blue-300">useState</span><span className="text-yellow-300">(</span><span className="text-orange-400">false</span><span className="text-yellow-300">)</span>;</div>
          <div className="pl-3"> </div>
          <div className="pl-3"><span className="text-blue-300">useEffect</span><span className="text-yellow-300">(()</span> <span className="text-purple-400">=&gt;</span> <span className="text-yellow-300">{'{'}</span></div>
          <div className="pl-6"><span className="text-purple-400">const</span> interval = <span className="text-blue-300">setInterval</span><span className="text-yellow-300">(()</span> <span className="text-purple-400">=&gt;</span> <span className="text-yellow-300">{'{'}</span></div>
          <div className="pl-9">setIsSaving<span className="text-yellow-300">(</span><span className="text-orange-400">true</span><span className="text-yellow-300">)</span>;</div>
          <div className="pl-9"><span className="text-blue-300">onSave</span><span className="text-yellow-300">(</span>data<span className="text-yellow-300">)</span>.<span className="text-blue-300">then</span><span className="text-yellow-300">(()</span> <span className="text-purple-400">=&gt;</span> setIsSaving<span className="text-yellow-300">(</span><span className="text-orange-400">false</span><span className="text-yellow-300">))</span>;</div>
          <div className="pl-6"><span className="text-yellow-300">{'}'}</span>, <span className="text-orange-400">30000</span><span className="text-yellow-300">)</span>;</div>
          <div className="pl-6"><span className="text-purple-400">return</span> <span className="text-yellow-300">()</span> <span className="text-purple-400">=&gt;</span> <span className="text-blue-300">clearInterval</span><span className="text-yellow-300">(</span>interval<span className="text-yellow-300">)</span>;</div>
          <div className="pl-3"><span className="text-yellow-300">{'}'}</span>, []<span className="text-yellow-300">)</span>; <span className="text-gray-500">// exhaustive-deps warning</span></div>
          <div className="pl-3"><span className="text-purple-400">return</span> isSaving;</div>
          <div><span className="text-yellow-300">{'}'}</span>;</div>
        </div>
      </div>
    </div>
  </div>
);

export const codeUseCase: UseCase = {
  id: 'code',
  label: 'Code Review',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
    </svg>
  ),
  requestText: "This autosave hook isn't working right. What am I missing?",
  outputText: `Classic stale closure bug. Here's what's happening:

The Problem:
Your useEffect has an empty dependency array [], so the closure captures the initial values of data and onSave. Every 30 seconds, you're saving the original data, not the current data.

Why the lint warning matters:
The exhaustive-deps warning is telling you exactly this — data and onSave are used inside the effect but aren't in the dependency array.

The Fix:
useEffect(() => {
  const interval = setInterval(() => {
    setIsSaving(true);
    onSave(data).then(() => setIsSaving(false));
  }, 30000);
  return () => clearInterval(interval);
}, [data, onSave]);

But wait — this creates a new interval every time data changes, which isn't what you want either.

Better pattern:
Use a ref to hold the current data:
const dataRef = useRef(data);
useEffect(() => { dataRef.current = data; }, [data]);

Then reference dataRef.current in the interval. This way the interval stays stable but always saves fresh data.`,
  duration: 25,
  contextComponent: <CodeEditorContext />,
};

export default CodeEditorContext;
