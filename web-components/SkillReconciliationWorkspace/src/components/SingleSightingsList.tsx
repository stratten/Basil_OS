import type { SkillCandidateSnapshot } from '../types';

interface SingleSightingsListProps {
  candidates: SkillCandidateSnapshot[];
  minObservations: number;
}

export function SingleSightingsList({ candidates, minObservations }: SingleSightingsListProps) {
  if (candidates.length === 0) {
    return (
      <div className="single-sightings-pane">
        <div className="single-sightings-note">
          No single-sighting candidates. Everything pending has been observed at least {minObservations} times.
        </div>
      </div>
    );
  }

  return (
    <div className="single-sightings-pane">
      <div className="single-sightings-note">
        These candidates have been observed fewer than {minObservations} times and are excluded from
        reconciliation review. They remain pending and will be considered once they recur.
      </div>
      {candidates.map((candidate) => (
        <div key={candidate.id} className="single-sighting-row">
          <span className="single-sighting-title">{candidate.title}</span>
          <span className="single-sighting-when">{candidate.when_to_use}</span>
          <span className="seen-badge">seen {candidate.observation_count}x</span>
        </div>
      ))}
    </div>
  );
}
