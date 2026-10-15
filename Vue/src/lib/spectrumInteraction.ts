/** Presentation-only lookup. Indices always refer to original, sorted source nodes. */
export interface PeakCurve { id: string; ys: readonly number[]; peaks: readonly number[] }
export interface HoverSelection { index: number; curveId: string; snapped: boolean }
export interface PlotSpace { low: number; high: number; left: number; top: number; width: number; height: number; yMaximum: number }

function lowerBound(xs: readonly number[], x: number, afterEqual = false) {
  let a = 0, b = xs.length
  while (a < b) { const m = (a + b) >>> 1; if (xs[m]! < x || afterEqual && xs[m] === x) a = m + 1; else b = m }
  return a
}
export function nearestNode(xs: readonly number[], x: number): number | null {
  if (!xs.length || !Number.isFinite(x)) return null
  const i = Math.min(xs.length - 1, lowerBound(xs, x))
  return i > 0 && x - xs[i - 1]! < xs[i]! - x ? i - 1 : i
}
export function localPeakIndices(ys: readonly number[]): number[] {
  if (ys.length < 2) return []
  const peaks: number[] = []
  for (let i = 0; i < ys.length;) {
    const value = ys[i]!; let end = i + 1
    while (end < ys.length && ys[end] === value) end++
    const left = i > 0 ? ys[i - 1]! : -Infinity, right = end < ys.length ? ys[end]! : -Infinity
    if (Number.isFinite(value) && (i > 0 || end < ys.length) && value > left && value > right) peaks.push(Math.floor((i + end - 1) / 2))
    i = end
  }
  return peaks
}
export function selectHoverNode(xs: readonly number[], curves: readonly PeakCurve[], plot: PlotSpace, px: number, py: number, radius = 10): HoverSelection | null {
  if (!curves.length || !xs.length || !Number.isFinite(px + py + plot.low + plot.high) || plot.width <= 0 || plot.height <= 0 || plot.high <= plot.low || !Number.isFinite(plot.yMaximum) || plot.yMaximum <= 0) return null
  if (px < plot.left || px > plot.left + plot.width || py < plot.top || py > plot.top + plot.height) return null
  const x = plot.low + (px - plot.left) / plot.width * (plot.high - plot.low)
  const first = lowerBound(xs, plot.low), last = lowerBound(xs, plot.high, true) - 1
  if (first > last || first >= xs.length) return null
  const nearest = nearestNode(xs, x)!
  const index = Math.max(first, Math.min(last, nearest))
  const xPosition = (i: number) => plot.left + (xs[i]! - plot.low) / (plot.high - plot.low) * plot.width
  const yPosition = (value: number) => plot.top + plot.height - value / plot.yMaximum * plot.height
  let result: HoverSelection | null = null, closest = Infinity, distance = Math.max(0, Math.min(12, radius)) ** 2
  const tolerance = Math.sqrt(distance) / plot.width * (plot.high - plot.low)
  for (const curve of curves) {
    const value = curve.ys[index]
    if (value !== undefined && Number.isFinite(value) && Math.abs(yPosition(value) - py) < closest) { closest = Math.abs(yPosition(value) - py); result = { index, curveId: curve.id, snapped: false } }
    // Binary-search the cached peak indices; do not rescan every source node on pointermove.
    let a = 0, b = curve.peaks.length
    while (a < b) { const m = (a + b) >>> 1; if (xs[curve.peaks[m]!]! < x - tolerance) a = m + 1; else b = m }
    for (let n = a; n < curve.peaks.length; n++) {
      const candidate = curve.peaks[n]!, wavelength = xs[candidate]!
      if (wavelength > x + tolerance) break
      if (candidate < first || candidate > last) continue
      const y = curve.ys[candidate]
      if (y === undefined || !Number.isFinite(y)) continue
      const dx = xPosition(candidate) - px, dy = yPosition(y) - py, squared = dx * dx + dy * dy
      if (squared <= distance) { distance = squared; result = { index: candidate, curveId: curve.id, snapped: true } }
    }
    // A later fallback must never replace an already selected nearby peak.
    if (result?.snapped) closest = -Infinity
  }
  return result
}
