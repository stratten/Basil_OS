function escapeMarkdownText(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/([`*_{}[\]<>])/g, '\\$1');
}

export function plainTextToDisplayMarkdown(text: string): string {
  return escapeMarkdownText(text);
}

function inlineMarkdown(node: Node): string {
  if (node.nodeType === 3) return escapeMarkdownText(node.textContent || '');
  if (node.nodeType !== 1) return '';
  const element = node as HTMLElement;
  const content = Array.from(element.childNodes).map(inlineMarkdown).join('');
  switch (element.tagName.toLowerCase()) {
    case 'br': return '\n';
    case 'b':
    case 'strong': return `**${content}**`;
    case 'i':
    case 'em': return `*${content}*`;
    case 'u': return `<u>${content}</u>`;
    case 'code': return `\`${content.replace(/`/g, '\\`')}\``;
    default: return content;
  }
}

function listMarkdown(list: HTMLElement, indent = ''): string {
  const ordered = list.tagName.toLowerCase() === 'ol';
  return Array.from(list.children).filter((child) => child.tagName.toLowerCase() === 'li').map((item, index) => {
    const element = item as HTMLElement;
    const nested = Array.from(element.children).filter((child) => ['ol', 'ul'].includes(child.tagName.toLowerCase())) as HTMLElement[];
    const content = Array.from(element.childNodes).filter((child) => !nested.includes(child as HTMLElement)).map(inlineMarkdown).join('').trim();
    return `${indent}${ordered ? `${index + 1}.` : '-'} ${content}\n${nested.map((child) => listMarkdown(child, `${indent}  `)).join('')}`;
  }).join('');
}

function blockMarkdown(node: Node): string {
  if (node.nodeType === 3) return escapeMarkdownText(node.textContent || '');
  if (node.nodeType !== 1) return '';
  const element = node as HTMLElement;
  switch (element.tagName.toLowerCase()) {
    case 'pre': return `\`\`\`\n${element.textContent?.trim() || ''}\n\`\`\`\n\n`;
    case 'ul':
    case 'ol': return `${listMarkdown(element)}\n`;
    case 'div':
    case 'p': return `${Array.from(element.childNodes).map(inlineMarkdown).join('').trim()}\n\n`;
    default: return inlineMarkdown(element);
  }
}

export function editorHtmlToDisplayMarkdown(editor: HTMLElement): string {
  return Array.from(editor.childNodes).map(blockMarkdown).join('').replace(/\n{3,}/g, '\n\n').trim();
}
