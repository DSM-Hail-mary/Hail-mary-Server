// Pure data-transform/formatting functions for the Hail-Mary dashboard
// (M11). No DOM, no fetch -- kept separate from app.js so they can be unit
// tested with the node:test runner (`node --test`). See format.test.js.

/**
 * Turn a GET /api/v1/occupancy/live response into a display-ready summary.
 * The endpoint returns:
 *   - null / [] when there is no data yet
 *   - a single object when called with ?zone_id=
 *   - an array of {zone_id, window_start, window_end, count} otherwise
 */
export function summarizeOccupancy(response) {
  if (response == null) return { hasData: false, total: 0, zones: [] };

  const rows = Array.isArray(response) ? response : [response];
  if (rows.length === 0) return { hasData: false, total: 0, zones: [] };

  const zones = rows
    .map((row) => ({ zone_id: row.zone_id, count: row.count }))
    .sort((a, b) => a.zone_id.localeCompare(b.zone_id));
  const total = zones.reduce((sum, z) => sum + z.count, 0);
  return { hasData: true, total, zones };
}

/**
 * Turn a GET /api/v1/forecast response (list of
 * {building_id, target_ts, with_occ_kwh, without_occ_kwh, actual_kwh})
 * into parallel arrays for charting. Nulls are preserved as gaps rather
 * than replaced with invented values.
 */
export function buildForecastChart(rows) {
  if (!rows || rows.length === 0) {
    return { hasData: false, labels: [], withOcc: [], withoutOcc: [], actual: [] };
  }
  return {
    hasData: true,
    labels: rows.map((r) => r.target_ts),
    withOcc: rows.map((r) => (r.with_occ_kwh == null ? null : r.with_occ_kwh)),
    withoutOcc: rows.map((r) => (r.without_occ_kwh == null ? null : r.without_occ_kwh)),
    actual: rows.map((r) => (r.actual_kwh == null ? null : r.actual_kwh)),
  };
}

/**
 * Turn a GET /api/v1/forecast/ablation response into a one-line summary.
 * Distinguishes three honest states rather than ever inventing a number:
 *   - no predicted/actual pairs at all (n === 0)
 *   - pairs exist, but none had an occupancy-aware forecast to compare
 *   - full data available -> report the MAE/RMSE improvement percentages
 */
export function formatAblation(a) {
  if (!a || a.n === 0) {
    return "데이터 없음 (예측-실측 쌍이 아직 없습니다)";
  }
  if (!a.with_occ_available_count) {
    return (
      `occupancy 반영 예측 없음 (n=${a.n}, without_occ MAE ${a.without_occ_mae.toFixed(1)}, ` +
      `RMSE ${a.without_occ_rmse.toFixed(1)})`
    );
  }
  const maePct = a.mae_improvement_pct == null ? "N/A" : `${a.mae_improvement_pct.toFixed(1)}%`;
  const rmsePct = a.rmse_improvement_pct == null ? "N/A" : `${a.rmse_improvement_pct.toFixed(1)}%`;
  return (
    `occupancy 반영 시 MAE ${maePct} / RMSE ${rmsePct} 개선 ` +
    `(with_occ 사용 가능 ${a.with_occ_available_count}/${a.n}건)`
  );
}

/**
 * Turn a GET /api/v1/savings response (list of reports, ordered by
 * period_start ascending) into the fields the savings card needs, picking
 * the most recently reported period.
 */
export function formatSavingsCard(reports) {
  if (!reports || reports.length === 0) return { hasData: false };
  const latest = reports[reports.length - 1];
  return {
    hasData: true,
    periodLabel: `${latest.period_start} ~ ${latest.period_end}`,
    savedKwhText: `${latest.saved_kwh.toFixed(2)} kWh`,
    savedPctText: `${latest.saved_pct.toFixed(1)}%`,
    co2Text: `${latest.co2_kg.toFixed(2)} kg`,
    treeText: `${latest.tree_equivalent.toFixed(1)} 그루`,
    raw: latest,
  };
}

/**
 * Combine several numeric series (e.g. actual/with_occ/without_occ) into one
 * {min, max}, ignoring nulls, so they can all be plotted on the same scale
 * instead of each independently stretching to fill the chart height (which
 * would hide how far apart they actually are). Falls back to a
 * non-degenerate range when every value is null/missing.
 */
export function computeSharedRange(seriesList) {
  const known = seriesList.flat().filter((v) => v != null);
  if (known.length === 0) return { min: 0, max: 1 };
  return { min: Math.min(...known), max: Math.max(...known) };
}

/**
 * Map a numeric series onto {x, y} canvas coordinates within
 * [padding, width-padding] x [padding, height-padding], preserving null
 * entries as null (a gap in the line) instead of interpolating them.
 *
 * By default the series is scaled to its own min/max. Pass `range`
 * (from computeSharedRange) to plot several series on one shared scale.
 */
export function projectSeriesToPoints(series, width, height, padding = 10, range = null) {
  if (!series || series.length === 0) return [];

  const { min, max } = range ?? computeSharedRange([series]);
  const span = max - min || 1; // avoid divide-by-zero on a flat series

  const innerWidth = Math.max(width - 2 * padding, 1);
  const innerHeight = Math.max(height - 2 * padding, 1);
  const step = series.length > 1 ? innerWidth / (series.length - 1) : 0;

  return series.map((value, i) => {
    if (value == null) return null;
    const x = padding + i * step;
    const y = padding + innerHeight - ((value - min) / span) * innerHeight;
    return { x, y };
  });
}

/** "2026-08-21T10:00:00Z" -> "2026-08-21 10:00:00"; passes through anything
 * else (empty string, already-plain text) unchanged. */
export function formatTimestamp(ts) {
  if (!ts) return "";
  return ts.replace("T", " ").replace("Z", "");
}
