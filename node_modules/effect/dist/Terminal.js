import * as Context from "./Context.js";
import * as Predicate from "./Predicate.js";
import * as Schema from "./Schema.js";
const TypeId = "~effect/platform/Terminal";
const QuitErrorTypeId = "effect/platform/Terminal/QuitError";
/**
 * Represents an error that occurs when a user attempts to
 * quit out of a `Terminal` prompt for input (usually by entering `ctrl`+`c`).
 *
 * **When to use**
 *
 * Use when implementing terminal input or prompts that need to signal
 * user-requested cancellation through the typed error channel.
 *
 * @see {@link isQuitError} for checking unknown errors when handling terminal cancellation
 *
 * @category QuitError
 * @since 4.0.0
 */
export class QuitError extends /*#__PURE__*/Schema.ErrorClass("QuitError")({
  _tag: /*#__PURE__*/Schema.tag("QuitError")
}) {
  /**
   * Marks this value as a terminal quit error for runtime guards.
   *
   * @since 4.0.0
   */
  [QuitErrorTypeId] = QuitErrorTypeId;
}
/**
 * Returns `true` if the provided value is a `Terminal.QuitError`.
 *
 * **When to use**
 *
 * Use to narrow unknown failures to `QuitError` when handling terminal input
 * cancellation.
 *
 * **Details**
 *
 * Returns `true` when the value carries the `QuitError` runtime marker and
 * narrows it to `QuitError`.
 *
 * @see {@link QuitError} for the error value produced when terminal input is quit
 *
 * @category guards
 * @since 4.0.0
 */
export const isQuitError = u => Predicate.hasProperty(u, QuitErrorTypeId);
/**
 * Service tag for command-line input and output services.
 *
 * **When to use**
 *
 * Use to access or provide platform terminal capabilities such as reading
 * input, writing output, and inspecting terminal dimensions.
 *
 * @category services
 * @since 4.0.0
 */
export const Terminal = /*#__PURE__*/Context.Service("effect/platform/Terminal");
/**
 * Creates a `Terminal` service implementation.
 *
 * **When to use**
 *
 * Use to construct a custom `Terminal` service implementation from concrete
 * terminal capabilities when writing a platform adapter, test implementation,
 * or custom runtime service.
 *
 * **Details**
 *
 * The implementation object supplies `columns`, `rows`, `readInput`,
 * `readLine`, and `display`; `make` attaches the `Terminal` service marker so
 * the result can be provided through the `Terminal` context service.
 *
 * @category constructors
 * @since 4.0.0
 */
export const make = impl => Terminal.of({
  ...impl,
  [TypeId]: TypeId
});
//# sourceMappingURL=Terminal.js.map