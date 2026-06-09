import { evaluate, makePrimitiveProto } from "./internal/core.js";
/**
 * Create a low-level `Effect` prototype.
 *
 * **When to use**
 *
 * Use when you need to create a custom Effect-like value without extending a
 * class, by providing a label and an evaluate function that receives the
 * current fiber.
 *
 * **Details**
 *
 * When the effect is evaluated, it calls `evaluate` with the current fiber.
 *
 * @see {@link Class} for a class-based approach to defining custom Effect values
 *
 * @category prototypes
 * @since 4.0.0
 */
export const Prototype = options => makePrimitiveProto({
  op: options.label,
  [evaluate]: options.evaluate
});
const Base = /*#__PURE__*/(() => {
  const Base = function () {};
  Base.prototype = /*#__PURE__*/Prototype({
    label: "Effectable",
    evaluate(_) {
      return this;
    }
  });
  return Base;
})();
/**
 * Provides an abstract class that can be extended to create an `Effect`.
 *
 * **When to use**
 *
 * Use as an abstract base class to define custom classes whose instances behave
 * as `Effect` values.
 *
 * @see {@link Prototype} for a lower-level primitive approach to creating custom Effect-like values without a class
 * @category constructors
 * @since 2.0.0
 */
export class Class extends Base {}
//# sourceMappingURL=Effectable.js.map