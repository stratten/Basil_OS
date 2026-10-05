import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { BASIL_TEAM } from './teamIdentity';

const swiftCatalog = readFileSync('../../client/Sources/Support/BasilTeamIdentity.swift', 'utf8');

describe('BASIL_TEAM identity catalog', () => {
  it('pairs every friendly name with its descriptor as a parenthetical', () => {
    for (const member of Object.values(BASIL_TEAM)) {
      expect(member.pairedName).toBe(`${member.displayName} (${member.descriptor})`);
    }
  });

  it('matches the Swift catalog for Dill and Paprika', () => {
    for (const member of [BASIL_TEAM.assistantSession, BASIL_TEAM.agentTask]) {
      expect(swiftCatalog).toContain(`displayName: "${member.displayName}"`);
      expect(swiftCatalog).toContain(`descriptor: "${member.descriptor}"`);
    }
  });

  it('never exposes internal capability identifiers', () => {
    for (const member of Object.values(BASIL_TEAM)) {
      expect(member.pairedName).not.toMatch(/AssistantSession|AgentTask/);
    }
  });
});
