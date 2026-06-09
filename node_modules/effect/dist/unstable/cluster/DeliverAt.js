import { hasProperty } from "../../Predicate.js";
/**
 * Defines the property key used by values that provide a scheduled delivery time.
 *
 * **When to use**
 *
 * Use to implement the scheduled-delivery protocol on cluster message payloads
 * by defining a method at this property key.
 *
 * @category symbols
 * @since 4.0.0
 */
export const symbol = "~effect/cluster/DeliverAt";
/**
 * Returns `true` if the value implements the `DeliverAt` scheduled-delivery
 * protocol.
 *
 * @category guards
 * @since 4.0.0
 */
export const isDeliverAt = self => hasProperty(self, symbol);
/**
 * Returns the scheduled delivery time in epoch milliseconds when the value
 * implements `DeliverAt`, or `null` otherwise.
 *
 * @category accessors
 * @since 4.0.0
 */
export const toMillis = self => {
  if (isDeliverAt(self)) {
    return self[symbol]().epochMilliseconds;
  }
  return null;
};
//# sourceMappingURL=DeliverAt.js.map