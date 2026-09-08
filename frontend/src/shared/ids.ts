// A process-local monotonic id source for editable list items (e.g. ground-station draft rows).
//
// React row keys and new-item naming must not be derived from the array index or length: adding,
// deleting a middle item, then adding again can collide when the id is `list.length + 1`
// (correction 3). A never-reused counter avoids that; it identifies the editable row, and is
// distinct from the user-facing stable_key (the domain relationship key).

let counter = 0

export function nextEditId(prefix = 'row'): string {
  counter += 1
  return `${prefix}-${counter}`
}

/**
 * A stable_key not already present in `existing`, of the form `<prefix>-<n>` with the smallest n
 * that does not collide. Unlike a `length + 1` scheme, this is safe under add -> delete middle ->
 * add again (correction 3).
 */
export function uniqueStableKey(existing: ReadonlySet<string>, prefix = 'SYN-GS-NEW'): string {
  let n = 1
  let key = `${prefix}-${n}`
  while (existing.has(key)) {
    n += 1
    key = `${prefix}-${n}`
  }
  return key
}
