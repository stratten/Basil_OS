import type {
  ApprovalExplanation,
  ApprovalToolPolicyScope,
  ApprovalWhitelistAdvice,
  ApprovalWhitelistStatus,
} from '../types';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonEmptyText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function parseAdvice(value: unknown): ApprovalWhitelistAdvice | null {
  if (!isRecord(value) || typeof value.recommend !== 'boolean') return null;
  const reason = nonEmptyText(value.reason);
  if (!reason) return null;
  return { recommend: value.recommend, reason, downgraded: value.downgraded === true };
}

function parseToolPolicy(value: unknown): ApprovalToolPolicyScope | undefined {
  if (!isRecord(value)) return undefined;
  const connectionId = nonEmptyText(value.connection_id);
  const toolName = nonEmptyText(value.tool_name);
  if (!connectionId || !toolName) return undefined;
  return {
    connection_id: connectionId,
    connection_name: typeof value.connection_name === 'string' ? value.connection_name : '',
    tool_name: toolName,
    destructive: value.destructive === true,
  };
}

function parseWhitelist(value: unknown): ApprovalWhitelistStatus | undefined {
  if (!isRecord(value) || typeof value.eligible !== 'boolean') return undefined;
  const status: ApprovalWhitelistStatus = {
    eligible: value.eligible,
    reason: typeof value.reason === 'string' ? value.reason : '',
    advice: parseAdvice(value.advice),
  };
  const pattern = nonEmptyText(value.pattern);
  if (pattern) status.pattern = pattern;
  if (value.broad === true) status.broad = true;
  const toolPolicy = parseToolPolicy(value.tool_policy);
  if (toolPolicy) status.tool_policy = toolPolicy;
  return status;
}

/**
 * Reads the explanation fields the backend puts in an approval's `context`, for both the live
 * `execution_approval_request` event and a recovered pending approval, so the two render alike.
 * Older backends omit every field; the result is then empty and the card looks as it always did.
 */
export function approvalExplanationFromContext(context: unknown): ApprovalExplanation {
  if (!isRecord(context)) return {};
  const explanation: ApprovalExplanation = {};
  const purpose = nonEmptyText(context.purpose);
  if (purpose) {
    explanation.purpose = purpose;
    if (context.purpose_source === 'basil') explanation.purpose_source = 'basil';
  }
  if (context.purpose_missing === true && !purpose) explanation.purpose_missing = true;
  const whitelist = parseWhitelist(context.whitelist);
  if (whitelist) explanation.whitelist = whitelist;
  const scriptPath = nonEmptyText(context.script_path);
  if (scriptPath) explanation.script_path = scriptPath;
  const scriptNotice = nonEmptyText(context.script_notice);
  if (scriptNotice) explanation.script_notice = scriptNotice;
  return explanation;
}
