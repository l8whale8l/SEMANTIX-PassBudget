import type { RunResult, ScheduledSession } from '../../shared/api/types'

/** The identity after the layer prefix: "geometric/<ID>" / "scheduled/<ID>" -> "<ID>". */
export function keyIdentity(stableKey: string): string {
  const slash = stableKey.indexOf('/')
  return slash === -1 ? stableKey : stableKey.slice(slash + 1)
}

/**
 * Find the scheduled session for a geometric access by EXACT shared identity, not by suffix
 * (defect 3): a substring/endsWith match could pick a session whose id merely ends with this
 * access's id (e.g. "...0905" vs "...905").
 */
export function findScheduledForAccess(
  result: RunResult,
  accessKey: string,
): ScheduledSession | null {
  const identity = keyIdentity(accessKey)
  return (
    result.scheduled_sessions.find((s) => keyIdentity(s.candidate_stable_key) === identity) ?? null
  )
}
