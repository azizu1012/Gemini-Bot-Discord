/**
 * Low-level helpers for adapting push-based SQL row sources into Effect
 * streams.
 *
 * SQL drivers often expose large query results through cursors, event emitters,
 * or driver-specific streams that push rows as they arrive. This module
 * provides the small interop layer used by SQL integrations to turn those
 * producers into `Stream` values for `Statement.stream` and
 * `Connection.executeStream`, so callers can process large result sets
 * incrementally instead of materializing every row in memory.
 *
 * The adapter is scoped: driver cursors, query streams, or reserved
 * connections should be acquired in the registration effect and released with
 * finalizers. The internal queue is bounded and calls the producer's
 * `onPause`/`onResume` hooks when downstream consumption falls behind, but the
 * underlying driver still has to honor those hooks for backpressure to be
 * effective. Slow consumers may keep a database cursor and connection open for
 * the lifetime of the stream, so integrations should close or destroy driver
 * resources on interruption, failure, or normal completion and should signal
 * terminal events with `fail` or `end` exactly once.
 *
 * @since 4.0.0
 */
import * as Cause from "../../Cause.js";
import * as Effect from "../../Effect.js";
import * as Queue from "../../Queue.js";
import * as Stream from "../../Stream.js";
/**
 * Creates a stream from a callback-style producer with pause and resume
 * callbacks that are triggered when the internal queue applies backpressure.
 *
 * @category constructors
 * @since 4.0.0
 */
export const asyncPauseResume = (register, bufferSize = 128) => Stream.callback(queue => Effect.suspend(() => {
  let cbs;
  let paused = false;
  const offer = arr => {
    if (arr.length === 0) return;
    const isFull = Queue.isFullUnsafe(queue);
    if (!isFull || isFull && paused) {
      return Effect.runFork(Queue.offerAll(queue, arr));
    }
    paused = true;
    cbs.onPause();
    return Queue.offerAll(queue, arr).pipe(Effect.tap(() => Effect.sync(() => {
      cbs.onResume();
      paused = false;
    })), Effect.runFork);
  };
  return Effect.map(register({
    single: item => offer([item]),
    array: chunk => offer(chunk),
    fail: error => Queue.failCauseUnsafe(queue, Cause.fail(error)),
    end: () => Queue.endUnsafe(queue)
  }), _ => {
    cbs = _;
  });
}), {
  bufferSize
});
//# sourceMappingURL=SqlStream.js.map