interface MeetingSwitchProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Extra class names appended to the shared `meeting-switch-control` label, for example a font-size modifier. */
  className?: string;
}

/** The Notetaker's single switch control (label, hidden checkbox, styled track) shared by the recording controls, the tools card and the Companion. */
export default function MeetingSwitch({ label, checked, onChange, disabled, className }: MeetingSwitchProps) {
  return (
    <label className={className ? `meeting-switch-control ${className}` : 'meeting-switch-control'}>
      <span>{label}</span>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span className="meeting-switch-track" aria-hidden="true" />
    </label>
  );
}
