import { dual } from "./Function.js";
import * as Reducer_ from "./Reducer.js";
/**
 * Reverses the ordering of the input Ordering.
 * This is useful for creating descending sort orders from ascending ones.
 *
 * **When to use**
 *
 * Use to flip an ordering result when reversing sort direction or comparison
 * priority.
 *
 * **Example** (Reversing comparison order)
 *
 * ```ts
 * import { Ordering } from "effect"
 *
 * // Basic reversal
 * console.log(Ordering.reverse(1)) // -1 (greater becomes less)
 * console.log(Ordering.reverse(-1)) // 1 (less becomes greater)
 * console.log(Ordering.reverse(0)) // 0 (equal stays equal)
 *
 * // Creating descending sort from ascending comparison
 * const compareNumbers = (a: number, b: number): Ordering.Ordering =>
 *   a < b ? -1 : a > b ? 1 : 0
 *
 * const compareDescending = (a: number, b: number): Ordering.Ordering =>
 *   Ordering.reverse(compareNumbers(a, b))
 *
 * const numbers = [3, 1, 4, 1, 5]
 * numbers.sort(compareNumbers) // [1, 1, 3, 4, 5] (ascending)
 * numbers.sort(compareDescending) // [5, 4, 3, 1, 1] (descending)
 *
 * // Useful for toggling sort direction
 * const createSorter = (ascending: boolean) => (a: number, b: number) => {
 *   const ordering = compareNumbers(a, b)
 *   return ascending ? ordering : Ordering.reverse(ordering)
 * }
 * ```
 *
 * @category transforming
 * @since 2.0.0
 */
export const reverse = o => o === -1 ? 1 : o === 1 ? -1 : 0;
/**
 * Matches an `Ordering` value and returns the branch selected by that ordering.
 *
 * **When to use**
 *
 * Use to branch on the three possible comparison outcomes in one expression.
 *
 * **Example** (Pattern matching on orderings)
 *
 * ```ts
 * import { Function, Ordering } from "effect"
 * import * as assert from "node:assert"
 *
 * const toMessage = Ordering.match({
 *   onLessThan: Function.constant("less than"),
 *   onEqual: Function.constant("equal"),
 *   onGreaterThan: Function.constant("greater than")
 * })
 *
 * assert.deepStrictEqual(toMessage(-1), "less than")
 * assert.deepStrictEqual(toMessage(0), "equal")
 * assert.deepStrictEqual(toMessage(1), "greater than")
 * ```
 *
 * @category pattern matching
 * @since 2.0.0
 */
export const match = /*#__PURE__*/dual(2, (self, {
  onEqual,
  onGreaterThan,
  onLessThan
}) => self === -1 ? onLessThan() : self === 0 ? onEqual() : onGreaterThan());
/**
 * Reducer for combining `Ordering`s.
 *
 * **When to use**
 *
 * Use to combine multiple comparison results in priority order, such as
 * checking secondary criteria only when earlier criteria compare as equal.
 *
 * **Details**
 *
 * If any of the `Ordering`s is non-zero, the result is the first non-zero `Ordering`.
 * If all the `Ordering`s are zero, the result is zero.
 *
 * **Gotchas**
 *
 * `combineAll` stops consuming the iterable as soon as it finds a non-zero
 * `Ordering`.
 *
 * @category ordering
 * @since 4.0.0
 */
export const Reducer = /*#__PURE__*/Reducer_.make((self, that) => self !== 0 ? self : that, 0, collection => {
  let ordering = 0;
  for (ordering of collection) {
    if (ordering !== 0) {
      return ordering;
    }
  }
  return ordering;
});
//# sourceMappingURL=Ordering.js.map