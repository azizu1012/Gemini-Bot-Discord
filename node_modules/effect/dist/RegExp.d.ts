/**
 * Exposes the JavaScript regular expression constructor from `globalThis`.
 *
 * **When to use**
 *
 * Use to construct JavaScript regular expressions through the Effect module
 * namespace.
 *
 * **Example** (Creating a regular expression)
 *
 * ```ts
 * import { RegExp } from "effect"
 *
 * // Create a regular expression using Effect's RegExp constructor
 * const pattern = new RegExp.RegExp("hello", "i")
 *
 * // Test the pattern
 * console.log(pattern.test("Hello World")) // true
 * console.log(pattern.test("goodbye")) // false
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const RegExp: RegExpConstructor;
/**
 * Checks whether a value is a `RegExp`.
 *
 * **When to use**
 *
 * Use to validate unknown input before treating it as a regular expression.
 *
 * **Example** (Checking for regular expressions)
 *
 * ```ts
 * import { RegExp } from "effect"
 * import * as assert from "node:assert"
 *
 * assert.deepStrictEqual(RegExp.isRegExp(/a/), true)
 * assert.deepStrictEqual(RegExp.isRegExp("a"), false)
 * ```
 *
 * @category guards
 * @since 3.9.0
 */
export declare const isRegExp: (input: unknown) => input is RegExp;
/**
 * Escapes special characters in a regular expression pattern.
 *
 * **When to use**
 *
 * Use to turn literal text into a safe regular expression pattern fragment.
 *
 * **Example** (Escaping a pattern string)
 *
 * ```ts
 * import { RegExp } from "effect"
 * import * as assert from "node:assert"
 *
 * assert.deepStrictEqual(RegExp.escape("a*b"), "a\\*b")
 * ```
 *
 * @category RegExp
 * @since 2.0.0
 */
export declare const escape: (string: string) => string;
//# sourceMappingURL=RegExp.d.ts.map