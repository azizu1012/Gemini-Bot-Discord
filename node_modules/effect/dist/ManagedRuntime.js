import * as Effect from "./Effect.js";
import * as Exit from "./Exit.js";
import * as Fiber from "./Fiber.js";
import * as Layer from "./Layer.js";
import { hasProperty } from "./Predicate.js";
import * as Scope from "./Scope.js";
const TypeId = "~effect/ManagedRuntime";
/**
 * Checks whether the provided argument is a `ManagedRuntime`.
 *
 * **When to use**
 *
 * Use to narrow an unknown value before treating it as a `ManagedRuntime`.
 *
 * **Details**
 *
 * The guard checks the internal `ManagedRuntime` marker property. It does not
 * build the layer or inspect the runtime's services.
 *
 * **Gotchas**
 *
 * Disposed runtimes still carry the marker, so this guard does not prove the
 * runtime is still usable.
 *
 * @see {@link make} for creating managed runtimes this guard recognizes
 *
 * @category guards
 * @since 3.9.0
 */
export const isManagedRuntime = input => hasProperty(input, TypeId);
/**
 * Creates a `ManagedRuntime` from a layer.
 *
 * **When to use**
 *
 * Use to create a reusable runtime from a `Layer` for application entry points
 * or integration code that runs many effects without rebuilding services.
 *
 * **Details**
 *
 * The layer is built lazily on first use and its context is cached for
 * subsequent runs. Resources acquired by the layer are owned by the runtime and
 * are released when `dispose` or `disposeEffect` is run. `options.memoMap` can
 * be used to share layer memoization with other layer builds.
 *
 * **Gotchas**
 *
 * Dispose the runtime when it is no longer needed. A runtime cannot be reused
 * after disposal.
 *
 * **Example** (Creating a managed runtime)
 *
 * ```ts
 * import { Context, Effect, Layer, ManagedRuntime } from "effect"
 *
 * class Notifications extends Context.Service<Notifications, {
 *   readonly notify: (message: string) => Effect.Effect<void>
 * }>()("Notifications") {
 *   static readonly layer = Layer.succeed(this)({
 *     notify: Effect.fn("Notifications.notify")((message) =>
 *       Effect.sync(() => console.log(message))
 *     )
 *   })
 * }
 *
 * const runtime = ManagedRuntime.make(Notifications.layer)
 *
 * const program = Effect.flatMap(
 *   Notifications,
 *   (_) => _.notify("Hello, world!")
 * ).pipe(Effect.ensuring(runtime.disposeEffect))
 *
 * runtime.runPromise(program)
 * // Hello, world!
 * ```
 *
 * @see {@link ManagedRuntime} for the returned runtime interface
 * @see {@link Layer.MemoMap} for shared layer memoization
 * @see {@link Layer.build} for lower-level scoped layer construction
 *
 * @category runtime class
 * @since 2.0.0
 */
export const make = (layer, options) => {
  const memoMap = options?.memoMap ?? Layer.makeMemoMapUnsafe();
  const scope = Scope.makeUnsafe("parallel");
  const layerScope = Scope.forkUnsafe(scope, "sequential");
  const defaultRunOptions = {
    onFiberStart: Fiber.runIn(scope)
  };
  const mergeRunOptions = options => options ? {
    ...options,
    onFiberStart: options.onFiberStart ? fiber => {
      defaultRunOptions.onFiberStart(fiber);
      options.onFiberStart(fiber);
    } : defaultRunOptions.onFiberStart
  } : defaultRunOptions;
  let buildFiber;
  const contextEffect = Effect.withFiber(fiber => {
    if (!buildFiber) {
      buildFiber = Effect.runFork(Effect.tap(Layer.buildWithMemoMap(layer, memoMap, layerScope), context => Effect.sync(() => {
        self.cachedContext = context;
      })), {
        ...defaultRunOptions,
        scheduler: fiber.currentScheduler
      });
    }
    return Effect.flatten(Fiber.await(buildFiber));
  });
  const self = {
    [TypeId]: TypeId,
    memoMap,
    scope,
    contextEffect: contextEffect,
    cachedContext: undefined,
    context() {
      return self.cachedContext === undefined ? Effect.runPromise(self.contextEffect) : Promise.resolve(self.cachedContext);
    },
    dispose() {
      return Effect.runPromise(self.disposeEffect);
    },
    disposeEffect: Effect.suspend(() => {
      ;
      self.contextEffect = Effect.die("ManagedRuntime disposed");
      self.cachedContext = undefined;
      return Scope.close(self.scope, Exit.void);
    }),
    runFork(effect, options) {
      return self.cachedContext === undefined ? Effect.runFork(provide(self, effect), mergeRunOptions(options)) : Effect.runForkWith(self.cachedContext)(effect, mergeRunOptions(options));
    },
    runCallback(effect, options) {
      return self.cachedContext === undefined ? Effect.runCallback(provide(self, effect), mergeRunOptions(options)) : Effect.runCallbackWith(self.cachedContext)(effect, mergeRunOptions(options));
    },
    runSyncExit(effect) {
      return self.cachedContext === undefined ? Effect.runSyncExit(provide(self, effect)) : Effect.runSyncExitWith(self.cachedContext)(effect);
    },
    runSync(effect) {
      return self.cachedContext === undefined ? Effect.runSync(provide(self, effect)) : Effect.runSyncWith(self.cachedContext)(effect);
    },
    runPromiseExit(effect, options) {
      return self.cachedContext === undefined ? Effect.runPromiseExit(provide(self, effect), mergeRunOptions(options)) : Effect.runPromiseExitWith(self.cachedContext)(effect, mergeRunOptions(options));
    },
    runPromise(effect, options) {
      return self.cachedContext === undefined ? Effect.runPromise(provide(self, effect), mergeRunOptions(options)) : Effect.runPromiseWith(self.cachedContext)(effect, mergeRunOptions(options));
    }
  };
  return self;
};
function provide(managed, effect) {
  return Effect.flatMap(managed.contextEffect, context => Effect.provideContext(effect, context));
}
//# sourceMappingURL=ManagedRuntime.js.map