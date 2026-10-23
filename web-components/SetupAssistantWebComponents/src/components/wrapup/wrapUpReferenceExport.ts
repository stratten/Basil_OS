import { jsPDF } from 'jspdf'

import { saveSetupReferencePdf } from '@/services/bridge'
import type { SetupWrapUpProposal } from '@/types'

const SETTINGS_POINTER = 'You can launch the Setup Assistant again any time from Settings > General > Application Setup.'
const DEFAULT_FILENAME = 'Basil Setup Reference'

interface WrapUpReferenceDocument {
  title: string
  recap: string
  recommendedNextSteps: Array<{
    label: string
    message: string
  }>
  optionalBreadth?: string | null
  settingsPointer: string
}

export function buildWrapUpReferenceMarkdown(proposal: SetupWrapUpProposal): string {
  const document = buildWrapUpReferenceDocument(proposal)
  const lines = [
    `# ${document.title}`,
    '',
    '## Where We Landed',
    document.recap,
  ]

  if (document.recommendedNextSteps.length > 0) {
    lines.push('', '## Recommended Next Steps')
    for (const step of document.recommendedNextSteps) {
      lines.push(`- **${step.label}**: ${step.message}`)
    }
  }

  if (document.optionalBreadth?.trim()) {
    lines.push('', '## You Can Come Back To', document.optionalBreadth.trim())
  }

  lines.push('', '## Resume Setup', document.settingsPointer)

  return `${lines.join('\n')}\n`
}

export async function copyWrapUpReferenceMarkdown(proposal: SetupWrapUpProposal): Promise<void> {
  const markdown = buildWrapUpReferenceMarkdown(proposal)
  await navigator.clipboard.writeText(markdown)
}

export async function downloadWrapUpReferencePdf(proposal: SetupWrapUpProposal): Promise<string> {
  const pdfBytes = createWrapUpReferencePdfBytes(buildWrapUpReferenceDocument(proposal))
  const suggestedFilename = `${DEFAULT_FILENAME}.pdf`
  const base64Pdf = arrayBufferToBase64(pdfBytes)

  try {
    const result = await saveSetupReferencePdf(base64Pdf, suggestedFilename)
    return result.message
  } catch {
    downloadBlob(
      new Blob([pdfBytes], { type: 'application/pdf' }),
      suggestedFilename,
    )
    return 'PDF downloaded.'
  }
}

function buildWrapUpReferenceDocument(proposal: SetupWrapUpProposal): WrapUpReferenceDocument {
  return {
    title: DEFAULT_FILENAME,
    recap: proposal.recap.trim(),
    recommendedNextSteps: proposal.recommended_next_steps.map(step => ({
      label: step.label.trim(),
      message: step.message.trim(),
    })).filter(step => step.label.length > 0 || step.message.length > 0),
    optionalBreadth: proposal.optional_breadth?.trim() || null,
    settingsPointer: SETTINGS_POINTER,
  }
}

function createWrapUpReferencePdfBytes(document: WrapUpReferenceDocument): ArrayBuffer {
  const pdf = new jsPDF({ unit: 'pt', format: 'letter' })
  const marginX = 64
  const marginBottom = 64
  const maxWidth = 612 - marginX * 2
  let cursorY = 72

  const ensureSpace = (height: number) => {
    if (cursorY + height <= 792 - marginBottom) return
    pdf.addPage()
    cursorY = 72
  }

  const addHeading = (text: string, size = 15) => {
    ensureSpace(32)
    pdf.setFont('helvetica', 'bold')
    pdf.setFontSize(size)
    pdf.setTextColor(0, 48, 135)
    pdf.text(text, marginX, cursorY)
    cursorY += size + 12
  }

  const addParagraph = (text: string, options?: { bullet?: boolean }) => {
    const lines = pdf.splitTextToSize(text, options?.bullet ? maxWidth - 18 : maxWidth)
    const lineHeight = 15
    ensureSpace(lines.length * lineHeight + 8)
    pdf.setFont('helvetica', 'normal')
    pdf.setFontSize(11)
    pdf.setTextColor(20, 24, 35)
    if (options?.bullet) {
      pdf.text('-', marginX, cursorY)
      pdf.text(lines, marginX + 18, cursorY)
    } else {
      pdf.text(lines, marginX, cursorY)
    }
    cursorY += lines.length * lineHeight + 8
  }

  addHeading(document.title, 20)
  addHeading('Where We Landed')
  addParagraph(document.recap)

  if (document.recommendedNextSteps.length > 0) {
    addHeading('Recommended Next Steps')
    for (const step of document.recommendedNextSteps) {
      const line = step.label && step.message
        ? `${step.label}: ${step.message}`
        : step.label || step.message
      addParagraph(line, { bullet: true })
    }
  }

  if (document.optionalBreadth) {
    addHeading('You Can Come Back To')
    addParagraph(document.optionalBreadth)
  }

  addHeading('Resume Setup')
  addParagraph(document.settingsPointer)

  return pdf.output('arraybuffer')
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  const chunkSize = 0x8000
  let binary = ''
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }
  return btoa(binary)
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
