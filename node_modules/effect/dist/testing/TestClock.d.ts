import * as Clock from "../Clock.ts";
import * as Duration from "../Duration.ts";
import * as Effect from "../Effect.ts";
import * as Latch from "../Latch.ts";
import * as Layer from "../Layer.ts";
/**
 * A `TestClock` simplifies deterministic and efficient testing of effects that
 * involve the passage of time.
 *
 * **Details**
 *
 * Instead of waiting for actual time to pass, `sleep` and methods implemented
 * in terms of it schedule effects to take place at a given clock time. Use
 * `adjust` and `setTime` to move clock time, and all effects scheduled to take
 * place on or before that time will automatically run in order.
 *
 * **Gotchas**
 *
 * Calls to `sleep` and methods derived from it will semantically block until
 * the time is set to on or after the time they are scheduled to run. Fork the
 * effect being tested, then adjust the clock time, and finally verify that the
 * expected effects have been performed.
 *
 * **Example** (Testing timeouts deterministically)
 *
 * Tests `Effect.timeout` using `TestClock`.
 *
 * ```ts
 * import { Effect, Fiber, Option, pipe } from "effect"
 * import { TestClock } from "effect/testing"
 * import * as assert from "node:assert"
 *
 * Effect.gen(function*() {
 *   const fiber = yield* pipe(
 *     Effect.sleep("5 minutes"),
 *     Effect.timeout("1 minute"),
 *     Effect.forkChild
 *   )
 *   yield* TestClock.adjust("1 minute")
 *   const result = yield* Fiber.join(fiber)
 *   assert.deepStrictEqual(result, Option.none())
 * })
 * ```
 *
 * **Example** (Advancing time deterministically)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   let executed = false
 *
 *   // Fork an effect that sleeps for 1 hour
 *   const fiber = yield* Effect.gen(function*() {
 *     yield* Effect.sleep("1 hour")
 *     executed = true
 *   }).pipe(Effect.forkChild)
 *
 *   // Advance the test clock by 1 hour
 *   yield* TestClock.adjust("1 hour")
 *
 *   // The effect should now be executed
 *   console.log(executed) // true
 * })
 * ```
 *
 * @category models
 * @since 2.0.0
 */
export interface TestClock extends Clock.Clock {
    /**
     * Increments the current clock time by the specified duration. Any effects
     * that were scheduled to occur on or before the new time will be run in
     * order.
     */
    adjust(duration: Duration.Input): Effect.Effect<void>;
    /**
     * Sets the current clock time to the specified `timestamp`. Any effects that
     * were scheduled to occur on or before the new time will be run in order.
     */
    setTime(timestamp: number): Effect.Effect<void>;
    /**
     * Executes the specified effect with the live `Clock` instead of the
     * `TestClock`.
     */
    withLive<A, E, R>(effect: Effect.Effect<A, E, R>): Effect.Effect<A, E, R>;
}
/**
 * Namespace containing `TestClock` configuration and state types.
 *
 * **Example** (Configuring a test clock)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   // Create a TestClock with custom options
 *   const testClock = yield* TestClock.make({
 *     warningDelay: "5 seconds"
 *   })
 *
 *   // Access the current state
 *   const currentTime = testClock.currentTimeMillisUnsafe()
 *   console.log(currentTime) // 0 (starts at epoch)
 * })
 * ```
 *
 * @since 2.0.0
 */
export declare namespace TestClock {
    /**
     * Options used when constructing a `TestClock`. `warningDelay` controls how
     * long the live clock waits before logging a warning when a test uses time
     * without advancing the test clock.
     *
     * **Example** (Configuring the warning delay)
     *
     * ```ts
     * import { Effect } from "effect"
     * import { TestClock } from "effect/testing"
     *
     * const program = Effect.gen(function*() {
     *   // Create a TestClock with custom warning delay
     *   const testClock = yield* TestClock.make({
     *     warningDelay: "30 seconds"
     *   })
     *
     *   // Use the TestClock in your test
     *   yield* testClock.adjust("1 hour")
     * })
     * ```
     *
     * @category options
     * @since 4.0.0
     */
    interface Options {
        /**
         * The amount of time to wait before displaying a warning message when a
         * test is using time but is not advancing the `TestClock`.
         */
        readonly warningDelay?: Duration.Input;
    }
    /**
     * Represents the state tracked by a `TestClock`, including the current
     * millisecond timestamp and the sleeps scheduled to resume when the clock
     * reaches their target time.
     *
     * @category models
     * @since 4.0.0
     */
    interface State {
        readonly timestamp: number;
        readonly sleeps: ReadonlyArray<[number, Latch.Latch]>;
    }
}
/**
 * Creates a `TestClock` with optional configuration.
 *
 * **Example** (Creating a test clock)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   // Create a TestClock with default settings
 *   const testClock = yield* TestClock.make()
 *
 *   // Create a TestClock with custom warning delay
 *   const customTestClock = yield* TestClock.make({
 *     warningDelay: "10 seconds"
 *   })
 *
 *   // Use the TestClock to control time in tests
 *   yield* testClock.adjust("1 hour")
 *   const currentTime = testClock.currentTimeMillisUnsafe()
 *   console.log(currentTime) // Time advanced by 1 hour
 * })
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options?: TestClock.Options | undefined) => Effect.Effect<{
    currentTimeMillisUnsafe: () => number;
    currentTimeNanosUnsafe: () => bigint;
    currentTimeMillis: Effect.Effect<number, never, never>;
    currentTimeNanos: Effect.Effect<bigint, never, never>;
    adjust: (duration: Duration.Input) => Effect.Effect<void, never, never>;
    setTime: (timestamp: number) => Effect.Effect<void, never, never>;
    sleep: (duration: Duration.Duration) => Effect.Effect<void, never, never>;
    withLive: <A, E, R>(effect: Effect.Effect<A, E, R>) => Effect.Effect<A, E, Exclude<R, never>>;
}, never, import("../Scope.ts").Scope>;
/**
 * Creates a `Layer` which constructs a `TestClock`.
 *
 * **Example** (Providing a test clock layer)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * // Create a TestClock layer
 * const testClockLayer = TestClock.layer()
 *
 * // Create a TestClock layer with custom options
 * const customTestClockLayer = TestClock.layer({
 *   warningDelay: "5 seconds"
 * })
 *
 * const program = Effect.gen(function*() {
 *   // Use the layer in your program
 *   yield* TestClock.adjust("1 hour")
 * }).pipe(Effect.provide(testClockLayer))
 * ```
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: (options?: TestClock.Options) => Layer.Layer<TestClock>;
/**
 * Retrieves the `TestClock` service for this test and uses it to run the
 * specified workflow.
 *
 * **Example** (Accessing the test clock)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   // Use testClockWith to access the TestClock instance
 *   const currentTime = yield* TestClock.testClockWith((testClock) =>
 *     Effect.succeed(testClock.currentTimeMillisUnsafe())
 *   )
 *
 *   // Adjust time using the TestClock instance
 *   yield* TestClock.testClockWith((testClock) => testClock.adjust("2 hours"))
 *
 *   console.log(currentTime) // Initial time
 * })
 * ```
 *
 * @category testing
 * @since 2.0.0
 */
export declare const testClockWith: <A, E, R>(f: (testClock: TestClock) => Effect.Effect<A, E, R>) => Effect.Effect<A, E, R>;
/**
 * Accesses a `TestClock` instance in the context and increments the time
 * by the specified duration, running any actions scheduled for on or before
 * the new time in order.
 *
 * **Example** (Advancing the test clock)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   let executed = false
 *
 *   // Fork an effect that sleeps for 30 minutes
 *   const fiber = yield* Effect.gen(function*() {
 *     yield* Effect.sleep("30 minutes")
 *     executed = true
 *   }).pipe(Effect.forkChild)
 *
 *   // Advance the clock by 30 minutes
 *   yield* TestClock.adjust("30 minutes")
 *
 *   // The effect should now be executed
 *   console.log(executed) // true
 * })
 * ```
 *
 * @category testing
 * @since 2.0.0
 */
export declare const adjust: (duration: Duration.Input) => Effect.Effect<void>;
/**
 * Sets the current clock time to the specified `timestamp`. Any effects that
 * were scheduled to occur on or before the new time will be run in order.
 *
 * **Example** (Setting the test clock time)
 *
 * ```ts
 * import { Duration, Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   let executed = false
 *
 *   // Fork an effect that sleeps for 2 hours
 *   const fiber = yield* Effect.gen(function*() {
 *     yield* Effect.sleep("2 hours")
 *     executed = true
 *   }).pipe(Effect.forkChild)
 *
 *   // Set the clock to a specific timestamp (2 hours from epoch)
 *   const targetTime = Duration.toMillis(Duration.hours(2))
 *   yield* TestClock.setTime(targetTime)
 *
 *   // The effect should now be executed
 *   console.log(executed) // true
 * })
 * ```
 *
 * @category testing
 * @since 2.0.0
 */
export declare const setTime: (timestamp: number) => Effect.Effect<void>;
/**
 * Executes the specified effect with the live `Clock` instead of the
 * `TestClock`.
 *
 * **Example** (Running with the live clock)
 *
 * ```ts
 * import { Clock, Effect } from "effect"
 * import { TestClock } from "effect/testing"
 *
 * const program = Effect.gen(function*() {
 *   // Get the current test time (starts at epoch)
 *   const testTime = yield* Clock.currentTimeMillis
 *   console.log(testTime) // 0
 *
 *   // Get the actual system time using withLive
 *   const realTime = yield* TestClock.withLive(Clock.currentTimeMillis)
 *   console.log(realTime) // Actual system timestamp
 *
 *   // Advance test time
 *   yield* TestClock.adjust("1 hour")
 *
 *   // Test time is now 1 hour ahead
 *   const newTestTime = yield* Clock.currentTimeMillis
 *   console.log(newTestTime) // 3600000 (1 hour in milliseconds)
 * })
 * ```
 *
 * @category testing
 * @since 4.0.0
 */
export declare const withLive: <A, E, R>(effect: Effect.Effect<A, E, R>) => Effect.Effect<A, E, R>;
//# sourceMappingURL=TestClock.d.ts.map