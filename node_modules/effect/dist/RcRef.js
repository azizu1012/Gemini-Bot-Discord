import * as internal from "./internal/rcRef.js";
const TypeId = "~effect/RcRef";
/**
 * Creates an `RcRef` from an acquire effect.
 *
 * **When to use**
 *
 * Use to create a lazily acquired, reference-counted resource from an acquire
 * effect.
 *
 * **Details**
 *
 * The resource is acquired lazily on the first `get` and shared by subsequent
 * gets while it remains cached. Each `get` adds a reference to the current
 * `Scope`. When the last reference is released, the resource is closed
 * immediately by default, or after `idleTimeToLive` when that option is
 * provided.
 *
 * **Example** (Creating a reference-counted resource)
 *
 * ```ts
 * import { Effect, RcRef } from "effect"
 *
 * Effect.gen(function*() {
 *   const ref = yield* RcRef.make({
 *     acquire: Effect.acquireRelease(
 *       Effect.succeed("foo"),
 *       () => Effect.log("release foo")
 *     )
 *   })
 *
 *   // will only acquire the resource once, and release it
 *   // when the scope is closed
 *   yield* RcRef.get(ref).pipe(
 *     Effect.andThen(RcRef.get(ref)),
 *     Effect.scoped
 *   )
 * })
 * ```
 *
 * @category constructors
 * @since 3.5.0
 */
export const make = internal.make;
/**
 * Gets the value from an `RcRef`, acquiring it first if needed.
 *
 * **When to use**
 *
 * Use to borrow the current resource within a `Scope`, acquiring it first if
 * necessary.
 *
 * **Details**
 *
 * The reference count is incremented for the current `Scope`, and a release
 * finalizer is added to that scope. When the current scope closes, the
 * reference is released; the resource is closed when the final reference is
 * released, subject to any configured idle time-to-live.
 *
 * **Example** (Sharing one acquired value)
 *
 * ```ts
 * import { Effect, RcRef } from "effect"
 *
 * const program = Effect.gen(function*() {
 *   // Create an RcRef with a resource
 *   const ref = yield* RcRef.make({
 *     acquire: Effect.acquireRelease(
 *       Effect.succeed("shared resource"),
 *       (resource) => Effect.log(`Releasing ${resource}`)
 *     )
 *   })
 *
 *   // Get the value from the RcRef
 *   const value1 = yield* RcRef.get(ref)
 *   const value2 = yield* RcRef.get(ref)
 *
 *   // Both values are the same instance
 *   console.log(value1 === value2) // true
 *
 *   return value1
 * })
 * ```
 *
 * @category combinators
 * @since 3.5.0
 */
export const get = internal.get;
/**
 * Invalidates the currently cached resource, if one has been acquired.
 *
 * **When to use**
 *
 * Use to force future `RcRef.get` calls to acquire a fresh resource when the
 * currently cached resource should no longer be reused.
 *
 * **Details**
 *
 * After invalidation, the next `get` acquires a fresh resource.
 *
 * **Gotchas**
 *
 * Invalidation does not revoke resources already borrowed by active scopes;
 * those remain usable until their scopes close.
 *
 * @see {@link get} for acquiring the current cached resource or the fresh resource after invalidation
 *
 * @category combinators
 * @since 3.19.6
 */
export const invalidate = internal.invalidate;
//# sourceMappingURL=RcRef.js.map