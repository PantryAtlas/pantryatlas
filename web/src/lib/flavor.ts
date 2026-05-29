/** Threshold above which a recipe earns the "great pairing" badge.
 *  ~top quartile of the blended cohesion+affinity distribution; tunable. */
export const FLAVOR_BADGE_THRESHOLD = 0.3

export function shouldShowPairingBadge(flavor: number | undefined): boolean {
  return typeof flavor === 'number' && flavor >= FLAVOR_BADGE_THRESHOLD
}
