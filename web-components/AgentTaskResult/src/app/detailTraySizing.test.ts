import { describe, expect, it } from 'vitest';
import {
  clampDetailTrayWidth,
  detailTrayPreferredWidth,
  DETAIL_TRAY_DETAIL_WIDTH,
  DETAIL_TRAY_MIN_WIDTH,
  DETAIL_TRAY_OVERVIEW_WIDTH,
  DETAIL_TRAY_PREVIEW_WIDTH,
  STANDALONE_COLLAPSED_DEFAULT_WIDTH,
  STANDALONE_COLLAPSED_MINIMUM_WIDTH,
  standaloneDefaultWidth,
  standaloneMinimumWidth,
} from './detailTraySizing';

describe('detailTraySizing', () => {
  it('clamps invalid and sub-minimum widths while allowing widths above the former cap', () => {
    expect(clampDetailTrayWidth(Number.NaN)).toBe(DETAIL_TRAY_DETAIL_WIDTH);
    expect(clampDetailTrayWidth(Number.POSITIVE_INFINITY)).toBe(DETAIL_TRAY_DETAIL_WIDTH);
    expect(clampDetailTrayWidth(DETAIL_TRAY_MIN_WIDTH - 1)).toBe(DETAIL_TRAY_MIN_WIDTH);
    expect(clampDetailTrayWidth(319.6)).toBe(320);
    expect(clampDetailTrayWidth(600)).toBe(600);
    expect(clampDetailTrayWidth(720.4)).toBe(720);
  });

  it('uses the prescribed overview, raw detail, and preview widths', () => {
    expect(detailTrayPreferredWidth('overview')).toBe(DETAIL_TRAY_OVERVIEW_WIDTH);
    expect(detailTrayPreferredWidth('detail')).toBe(DETAIL_TRAY_DETAIL_WIDTH);
    expect(detailTrayPreferredWidth('preview')).toBe(DETAIL_TRAY_PREVIEW_WIDTH);
  });

  it('uses the collapsed rail for the standalone default and raises requirements only for expanded surfaces', () => {
    expect(STANDALONE_COLLAPSED_DEFAULT_WIDTH).toBe(444);
    expect(STANDALONE_COLLAPSED_MINIMUM_WIDTH).toBe(444);
    expect(standaloneDefaultWidth(false)).toBe(444);
    expect(standaloneDefaultWidth(true)).toBe(444);
    expect(standaloneMinimumWidth(false)).toBe(444);
    expect(standaloneMinimumWidth(true)).toBe(636);
    expect(standaloneMinimumWidth(false, DETAIL_TRAY_OVERVIEW_WIDTH)).toBe(680);
    expect(standaloneMinimumWidth(false, DETAIL_TRAY_DETAIL_WIDTH)).toBe(720);
    expect(standaloneMinimumWidth(false, DETAIL_TRAY_PREVIEW_WIDTH)).toBe(800);
    expect(standaloneMinimumWidth(true, DETAIL_TRAY_OVERVIEW_WIDTH)).toBe(872);
    expect(standaloneMinimumWidth(true, DETAIL_TRAY_DETAIL_WIDTH)).toBe(912);
    expect(standaloneMinimumWidth(true, DETAIL_TRAY_PREVIEW_WIDTH)).toBe(992);
  });
});
