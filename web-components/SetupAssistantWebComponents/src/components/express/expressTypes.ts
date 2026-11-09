// Mirrors backend/src/api/services/setup_assistant/express/models.py.

export type ComfortLevel = 'cautious' | 'balanced' | 'all_in'
export type ExpressItemGroup = 'downloads' | 'learning' | 'background' | 'hotkeys'
export type ExpressItemOutcome = 'started' | 'applied' | 'skipped' | 'failed'
export type ReceiptState = 'on' | 'partial' | 'off'

export interface ExpressDevice {
  total_ram_gb: number
  memory_tier: string
  chip_label: string | null
  is_apple_silicon: boolean
  free_disk_gb: number | null
  summary: string
}

export interface ExpressPreflightCheck {
  id: 'disk' | 'network'
  ok: boolean
  message: string
}

export interface ExpressItem {
  id: string
  group: ExpressItemGroup
  title: string
  summary: string
  caution: string | null
  comfort: ComfortLevel
  stays_on_this_mac: boolean
  permissions: string[]
  model_id: string | null
  model_name: string | null
  download_size_gb: number | null
  native: boolean
  already_done: boolean
  unavailable_reason: string | null
  selected: boolean
}

export interface ExpressPlan {
  comfort: ComfortLevel
  device: ExpressDevice
  preflight: ExpressPreflightCheck[]
  items: ExpressItem[]
  notes: string[]
  thinking_model_available: boolean
}

export interface ExpressItemResult {
  id: string
  outcome: ExpressItemOutcome
  message: string
}

export interface ExpressApplyResult {
  comfort: ComfortLevel
  results: ExpressItemResult[]
  thinking_model_id: string | null
}

export interface ReceiptItem {
  id: string
  group: ExpressItemGroup
  title: string
  state: ReceiptState
  detail: string
  where_to_change: string
}

export interface SetupReceipt {
  items: ReceiptItem[]
}

export const THINKING_ITEM_ID = 'download_thinking_model'
