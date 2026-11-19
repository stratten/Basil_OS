import type { ReactNode } from 'react'

export function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="custom-models-form-section">
      <h3 className="custom-models-form-section-title">{title}</h3>
      <div className="custom-models-form-section-body">{children}</div>
    </section>
  )
}

export function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="custom-models-form-field">
      <label className="custom-models-form-field-label">{label}</label>
      {children}
      {hint && <p className="custom-models-form-field-hint">{hint}</p>}
    </div>
  )
}
