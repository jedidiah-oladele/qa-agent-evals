export type RoundingMode = "half-up" | "half-even" | "floor" | "ceil";

/**
 * Round `value` to an integer.
 *
 * Inputs usually come from multiplying minor units by a rate, so they carry
 * binary floating point noise (1.005 * 100 === 100.49999999999999). The value
 * is first normalised to 12 significant digits so that such noise does not
 * flip a half-way decision. "half-up" rounds halves away from zero.
 */
export function roundToInteger(value: number, mode: RoundingMode = "half-up"): number {
  if (!Number.isFinite(value)) {
    throw new RangeError(`cannot round ${value}`);
  }
  const normalized = Number(value.toPrecision(12));
  switch (mode) {
    case "floor":
      return Math.floor(normalized) + 0;
    case "ceil":
      return Math.ceil(normalized) + 0;
    case "half-up": {
      const rounded = Math.sign(normalized) * Math.round(Math.abs(normalized));
      return rounded + 0;
    }
    case "half-even": {
      const floor = Math.floor(normalized);
      const diff = normalized - floor;
      const EPS = 1e-9;
      if (Math.abs(diff - 0.5) < EPS) {
        return (floor % 2 === 0 ? floor : floor + 1) + 0;
      }
      return Math.round(normalized) + 0;
    }
  }
}
