/** Shared zoom behavior, independent of a particular graph or image renderer. */
export function nextZoomScale(current, direction, min = 0.08, max = 4) {
  const scale = Number.isFinite(current) && current > 0 ? current : 1;
  const next = direction > 0 ? scale * 1.2 : direction < 0 ? scale / 1.2 : scale;
  return Math.min(max, Math.max(min, next));
}

export function fitImageScale(width, height, availableWidth, availableHeight, padding = 24) {
  if (!(width > 0 && height > 0)) return 1;
  return Math.max(0.08, Math.min(1, (availableWidth - 2 * padding) / width, (availableHeight - 2 * padding) / height));
}
