import { useEffect, useState } from 'react';
import TokenizedSelect from '../../../shared/TokenizedSelect';
import { approveMemoryProposal, declineMemoryProposal, getMemoryProposal } from '../services/api';
import { notifyDeclined, notifySaved } from '../services/bridge';

interface Props {
  apiBaseUrl: string;
  proposalId: string;
}

const MEMORY_FILES = ['essentials.md', 'now.md', 'recent.md', 'user.md'];

export function MemoryProposalEditor({ apiBaseUrl, proposalId }: Props) {
  const [entry, setEntry] = useState('');
  const [targetFile, setTargetFile] = useState('user.md');
  const [why, setWhy] = useState('');
  const [confidence, setConfidence] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMemoryProposal(apiBaseUrl, proposalId)
      .then((proposal) => {
        if (!proposal) throw new Error('Proposal not found');
        setEntry(proposal.entry);
        setTargetFile(proposal.target_file_name);
        setWhy(proposal.why ?? '');
        setConfidence(proposal.confidence ?? '');
      })
      .catch((err) => setError(String(err)));
  }, [apiBaseUrl, proposalId]);

  async function approve() {
    await approveMemoryProposal(apiBaseUrl, proposalId, entry, targetFile);
    notifySaved(true);
  }

  async function decline() {
    await declineMemoryProposal(apiBaseUrl, proposalId);
    notifyDeclined();
  }

  return (
    <section className="editor-panel">
      {error && <div className="editor-error">{error}</div>}
      <TokenizedSelect
        className="editor-input"
        value={targetFile}
        ariaLabel="Memory file"
        onValueChange={setTargetFile}
        options={MEMORY_FILES.map((fileName) => ({ value: fileName, label: fileName }))}
      />
      {(why || confidence) && (
        <div className="editor-context">
          {why && <p><strong>Why:</strong> {why}</p>}
          {confidence && <p><strong>Confidence:</strong> {confidence}</p>}
        </div>
      )}
      <textarea className="editor-textarea" value={entry} onChange={(event) => setEntry(event.target.value)} />
      <div className="editor-footer">
        <button className="editor-danger-button" onClick={decline}>Decline</button>
        <button className="editor-primary-button" onClick={approve}>Approve</button>
      </div>
    </section>
  );
}
