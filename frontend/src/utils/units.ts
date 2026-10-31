export const MM_PER_INCH = 25.4

/** Printheads have 6, 8, 12 or 24 dots per mm; "300 dpi" is really 12 dots/mm (304.8 dpi). */
export function dotsPerMm(dpi: number): number {
  return Math.max(1, Math.round(dpi / MM_PER_INCH))
}

export function mmToDots(mm: number, dpi: number): number {
  return Math.round(mm * dotsPerMm(dpi))
}

export function dotsToMm(dots: number, dpi: number, decimals = 1): number {
  const factor = 10 ** decimals
  return Math.round((dots / dotsPerMm(dpi)) * factor) / factor
}

/** Inches per second (the unit of ^PR) to millimetres per second. */
export function ipsToMmPerSecond(ips: number): number {
  return Math.round(ips * MM_PER_INCH)
}
