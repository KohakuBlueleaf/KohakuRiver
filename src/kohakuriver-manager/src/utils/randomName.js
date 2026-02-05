/**
 * Random friendly name generator using friendly-words library.
 * Generates names like "sunny-meadow", "happy-penguin", etc.
 */

import { predicates, objects } from 'friendly-words'

/**
 * Pick a random element from an array.
 */
function randomPick(array) {
  return array[Math.floor(Math.random() * array.length)]
}

/**
 * Generate a random friendly name.
 * Format: predicate-object (e.g., "sunny-meadow")
 */
export function generateRandomName() {
  const predicate = randomPick(predicates)
  const object = randomPick(objects)
  return `${predicate}-${object}`
}

/**
 * Generate multiple random names.
 */
export function generateRandomNames(count = 5) {
  return Array.from({ length: count }, () => generateRandomName())
}
