import { describe, expect, it } from 'vitest';
import { editorHtmlToDisplayMarkdown } from './requestMarkdown';

type FakeNode = {
  nodeType: number;
  textContent?: string;
  tagName?: string;
  childNodes?: FakeNode[];
  children?: FakeNode[];
};

const text = (value: string): FakeNode => ({ nodeType: 3, textContent: value });
const element = (tagName: string, childNodes: FakeNode[] = []): FakeNode => ({
  nodeType: 1,
  tagName,
  childNodes,
  children: childNodes.filter(child => child.nodeType === 1),
  textContent: childNodes.map(child => child.textContent || '').join(''),
});

function editor(nodes: FakeNode[]) {
  return { childNodes: nodes } as unknown as HTMLElement;
}

describe('editorHtmlToDisplayMarkdown', () => {
  it('preserves supported inline formatting and blocks', () => {
    const markdown = editorHtmlToDisplayMarkdown(editor([
      element('div', [
        text('Draft '),
        element('strong', [text('this')]),
        text(' with '),
        element('em', [text('care')]),
        text(' and '),
        element('u', [text('underline')]),
        text('.'),
      ]),
      element('ul', [
        element('li', [text('First item')]),
        element('li', [text('Second item')]),
      ]),
      element('pre', [text('const answer = 42;')]),
    ]));

    expect(markdown).toBe(
      'Draft **this** with *care* and <u>underline</u>.\n\n- First item\n- Second item\n\n```\nconst answer = 42;\n```'
    );
  });

  it('falls back to escaped plain text for unsupported elements', () => {
    const markdown = editorHtmlToDisplayMarkdown(editor([
      element('span', [text('Use *literal* punctuation')]),
    ]));

    expect(markdown).toBe('Use \\*literal\\* punctuation');
  });
});
