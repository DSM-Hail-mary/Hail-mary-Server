// Unit tests for dashboard/format.js pure functions.
// Run with: node --test Hail_Mary/dashboard/format.test.js
// (no mocking -- every test feeds real input shapes the actual API returns
// and asserts on the real output of the real function.)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  summarizeOccupancy,
  buildForecastChart,
  formatAblation,
  formatSavingsCard,
  projectSeriesToPoints,
  computeSharedRange,
  formatTimestamp,
} from "./format.js";

// ---- summarizeOccupancy ----

test("summarizeOccupancy: null/empty input is reported as no data, not zero", () => {
  assert.deepEqual(summarizeOccupancy(null), { hasData: false, total: 0, zones: [] });
  assert.deepEqual(summarizeOccupancy([]), { hasData: false, total: 0, zones: [] });
});

test("summarizeOccupancy: single zone_id filter returns one object, not an array", () => {
  const result = summarizeOccupancy({
    zone_id: "hall_main",
    window_start: "2026-08-21T10:00:00Z",
    window_end: "2026-08-21T10:01:00Z",
    count: 3,
  });
  assert.deepEqual(result, { hasData: true, total: 3, zones: [{ zone_id: "hall_main", count: 3 }] });
});

test("summarizeOccupancy: sums counts across zones and sorts by zone_id", () => {
  const rows = [
    { zone_id: "hall_side", window_start: "t", window_end: "t", count: 1 },
    { zone_id: "hall_main", window_start: "t", window_end: "t", count: 3 },
  ];
  const result = summarizeOccupancy(rows);
  assert.equal(result.hasData, true);
  assert.equal(result.total, 4);
  assert.deepEqual(result.zones, [
    { zone_id: "hall_main", count: 3 },
    { zone_id: "hall_side", count: 1 },
  ]);
});

// ---- buildForecastChart ----

test("buildForecastChart: empty rows -> hasData false", () => {
  assert.deepEqual(buildForecastChart([]), { hasData: false, labels: [], withOcc: [], withoutOcc: [], actual: [] });
});

test("buildForecastChart: preserves nulls (missing with_occ_kwh) instead of inventing values", () => {
  const rows = [
    { building_id: "b1", target_ts: "2017-01-06T09:00:00", with_occ_kwh: null, without_occ_kwh: 20.0, actual_kwh: 19.5 },
    { building_id: "b1", target_ts: "2017-01-06T10:00:00", with_occ_kwh: 21.0, without_occ_kwh: 22.0, actual_kwh: null },
  ];
  const result = buildForecastChart(rows);
  assert.equal(result.hasData, true);
  assert.deepEqual(result.labels, ["2017-01-06T09:00:00", "2017-01-06T10:00:00"]);
  assert.deepEqual(result.withOcc, [null, 21.0]);
  assert.deepEqual(result.withoutOcc, [20.0, 22.0]);
  assert.deepEqual(result.actual, [19.5, null]);
});

// ---- formatAblation ----

test("formatAblation: n=0 is reported honestly as no data", () => {
  const text = formatAblation({
    n: 0, without_occ_mae: null, without_occ_rmse: null, with_occ_mae: null,
    with_occ_rmse: null, mae_improvement_pct: null, rmse_improvement_pct: null,
    with_occ_available_count: 0,
  });
  assert.match(text, /데이터 없음/);
});

test("formatAblation: with_occ never available is reported distinctly from n=0", () => {
  const text = formatAblation({
    n: 10, without_occ_mae: 5.2, without_occ_rmse: 6.1, with_occ_mae: null,
    with_occ_rmse: null, mae_improvement_pct: null, rmse_improvement_pct: null,
    with_occ_available_count: 0,
  });
  assert.match(text, /occupancy 반영 예측 없음/);
  assert.match(text, /5\.2/);
});

test("formatAblation: full data renders the improvement percentage to 1 decimal", () => {
  const text = formatAblation({
    n: 45, without_occ_mae: 5.234, without_occ_rmse: 6.789, with_occ_mae: 4.111,
    with_occ_rmse: 5.222, mae_improvement_pct: 21.4783, rmse_improvement_pct: 23.061,
    with_occ_available_count: 30,
  });
  assert.match(text, /21\.5%/);
  assert.match(text, /23\.1%/);
  assert.match(text, /30\/45/);
});

// ---- formatSavingsCard ----

test("formatSavingsCard: empty reports list is reported as no data", () => {
  assert.deepEqual(formatSavingsCard([]), { hasData: false });
});

test("formatSavingsCard: picks the most recent report and rounds for display", () => {
  const reports = [
    { period_start: "2026-08-01", period_end: "2026-08-07", saved_kwh: 10.111, saved_pct: 5.555, co2_kg: 4.9, tree_equivalent: 0.7 },
    { period_start: "2026-08-08", period_end: "2026-08-14", saved_kwh: 20.222, saved_pct: 8.888, co2_kg: 9.8, tree_equivalent: 1.4 },
  ];
  const card = formatSavingsCard(reports);
  assert.equal(card.hasData, true);
  assert.equal(card.periodLabel, "2026-08-08 ~ 2026-08-14");
  assert.equal(card.savedKwhText, "20.22 kWh");
  assert.equal(card.savedPctText, "8.9%");
  assert.equal(card.co2Text, "9.80 kg");
  assert.equal(card.treeText, "1.4 그루");
});

// ---- projectSeriesToPoints ----

test("projectSeriesToPoints: maps a flat series to a horizontal line and skips nulls", () => {
  const points = projectSeriesToPoints([1, 1, 1], 100, 50, 10);
  assert.equal(points.length, 3);
  points.forEach((p) => assert.ok(p !== null));
  // flat series -> all y equal
  assert.equal(points[0].y, points[1].y);
  assert.equal(points[1].y, points[2].y);
});

test("projectSeriesToPoints: null values produce null points (gap in the line)", () => {
  const points = projectSeriesToPoints([1, null, 3], 100, 50, 10);
  assert.equal(points[1], null);
  assert.notEqual(points[0], null);
  assert.notEqual(points[2], null);
});

test("projectSeriesToPoints: higher values map to smaller y (canvas origin is top-left)", () => {
  const points = projectSeriesToPoints([0, 10], 100, 50, 0);
  assert.ok(points[1].y < points[0].y);
});

test("projectSeriesToPoints: empty/all-null series returns empty array without throwing", () => {
  assert.deepEqual(projectSeriesToPoints([], 100, 50, 10), []);
  const allNull = projectSeriesToPoints([null, null], 100, 50, 10);
  assert.deepEqual(allNull, [null, null]);
});

// ---- computeSharedRange ----

test("computeSharedRange: spans the min/max across multiple series, ignoring nulls", () => {
  const range = computeSharedRange([
    [18.0, 18.2, 18.4],
    [20.0, null, 20.6],
    [null, null, null],
  ]);
  assert.deepEqual(range, { min: 18.0, max: 20.6 });
});

test("computeSharedRange: all-null input falls back to a non-degenerate range", () => {
  assert.deepEqual(computeSharedRange([[null, null], []]), { min: 0, max: 1 });
});

// ---- projectSeriesToPoints with a shared range ----

test("projectSeriesToPoints: an explicit range separates two series that would otherwise both fill the chart", () => {
  const range = computeSharedRange([[18.0, 18.4], [20.0, 20.6]]);
  const low = projectSeriesToPoints([18.0, 18.4], 100, 100, 0, range);
  const high = projectSeriesToPoints([20.0, 20.6], 100, 100, 0, range);
  // Higher-valued series must sit strictly above (smaller y) the lower one
  // once both are placed on the same scale.
  assert.ok(high[0].y < low[0].y);
  assert.ok(high[1].y < low[1].y);
});

// ---- formatTimestamp ----

test("formatTimestamp: passes through a non-ISO or empty value unchanged", () => {
  assert.equal(formatTimestamp(""), "");
  assert.equal(formatTimestamp(null), "");
});

test("formatTimestamp: renders an ISO timestamp as space-separated date/time", () => {
  assert.equal(formatTimestamp("2026-08-21T10:00:00Z"), "2026-08-21 10:00:00");
});
