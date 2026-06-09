import * as Arr from "./Array.js";
import * as Cache from "./Cache.js";
import * as Context from "./Context.js";
import * as Effect from "./Effect.js";
import * as Exit from "./Exit.js";
import { constTrue, dual, identity } from "./Function.js";
import { exitFail, exitSucceed } from "./internal/core.js";
import * as effect from "./internal/effect.js";
import * as internal from "./internal/request.js";
import * as Iterable from "./Iterable.js";
import * as MutableHashMap from "./MutableHashMap.js";
import { pipeArguments } from "./Pipeable.js";
import { hasProperty } from "./Predicate.js";
import * as Tracer from "./Tracer.js";
import * as Persistence from "./unstable/persistence/Persistence.js";
const TypeId = "~effect/RequestResolver";
const RequestResolverProto = {
  [TypeId]: {
    _A: identity,
    _R: identity
  },
  pipe() {
    return pipeArguments(this, arguments);
  }
};
/**
 * Returns `true` if the specified value is a `RequestResolver`, `false` otherwise.
 *
 * **When to use**
 *
 * Use to narrow unknown values before passing them to APIs that require a
 * `RequestResolver`.
 *
 * @see {@link RequestResolver} for the type narrowed by this guard
 *
 * @category guards
 * @since 2.0.0
 */
export const isRequestResolver = u => hasProperty(u, TypeId);
/**
 * Creates a request resolver with fine-grained
 * control over its behavior.
 *
 * **When to use**
 *
 * Use when you need to supply the resolver batching primitives directly,
 * including the batch key, optional pre-check, delay effect, collection cutoff,
 * and batch runner.
 *
 * **Details**
 *
 * `batchKey` groups request entries, `delay` schedules batch execution,
 * `collectWhile` can end collection early, and `runAll` receives a non-empty
 * batch for one key.
 *
 * **Gotchas**
 *
 * Accepted entries must be completed. If `runAll` succeeds with incomplete
 * entries, waiting requests fail. If `preCheck` returns `false`, the entry is
 * not batched, so it must be completed or linked to another completion path.
 *
 * @see {@link make} for constructing a resolver from a batch runner
 * @see {@link makeGrouped} for constructing a resolver that groups requests by key
 *
 * @category constructors
 * @since 4.0.0
 */
export const makeWith = options => {
  const self = Object.create(RequestResolverProto);
  self.batchKey = options.batchKey;
  self.preCheck = options.preCheck;
  self.delay = options.delay;
  self.collectWhile = options.collectWhile;
  self.runAll = options.runAll;
  return self;
};
const defaultKeyObject = {};
const defaultKey = _request => defaultKeyObject;
/**
 * Constructs a request resolver with the specified method to run requests.
 *
 * **Example** (Creating a request resolver)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * // Define a request type
 * interface GetUserRequest extends Request.Request<string, Error> {
 *   readonly _tag: "GetUserRequest"
 *   readonly id: number
 * }
 * const GetUserRequest = Request.tagged<GetUserRequest>("GetUserRequest")
 *
 * // Create a resolver that handles the requests
 * const UserResolver = RequestResolver.make<GetUserRequest>((entries) =>
 *   Effect.sync(() => {
 *     for (const entry of entries) {
 *       // Complete each request with a result
 *       entry.completeUnsafe(Exit.succeed(`User ${entry.request.id}`))
 *     }
 *   })
 * )
 *
 * // Use the resolver to handle requests
 * const getUserEffect = Effect.request(GetUserRequest({ id: 123 }), UserResolver)
 * ```
 *
 * @category constructors
 * @since 2.0.0
 */
export const make = runAll => makeWith({
  batchKey: defaultKey,
  delay: Effect.yieldNow,
  collectWhile: constTrue,
  runAll
});
/**
 * Constructs a request resolver with the requests grouped by a calculated key.
 *
 * **Details**
 *
 * The key can use the Equal trait to determine if two keys are equal.
 *
 * **Example** (Grouping requests by key)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetUserByRole extends Request.Request<string, Error> {
 *   readonly _tag: "GetUserByRole"
 *   readonly role: string
 *   readonly id: number
 * }
 * const GetUserByRole = Request.tagged<GetUserByRole>("GetUserByRole")
 *
 * // Group requests by role for efficient batch processing
 * const UserByRoleResolver = RequestResolver.makeGrouped<GetUserByRole, string>({
 *   key: ({ request }) => request.role,
 *   resolver: (entries, role) =>
 *     Effect.sync(() => {
 *       console.log(`Processing ${entries.length} requests for role: ${role}`)
 *       for (const entry of entries) {
 *         entry.completeUnsafe(
 *           Exit.succeed(`User ${entry.request.id} with role ${role}`)
 *         )
 *       }
 *     })
 * })
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const makeGrouped = options => makeWith({
  batchKey: hashGroupKey(options.key),
  delay: Effect.yieldNow,
  collectWhile: constTrue,
  runAll: options.resolver
});
const hashGroupKey = get => {
  const groupKeys = MutableHashMap.empty();
  return entry => {
    const key = get(entry);
    const okey = MutableHashMap.get(groupKeys, key);
    if (okey._tag === "Some") {
      return okey.value;
    }
    MutableHashMap.set(groupKeys, key, key);
    return key;
  };
};
/**
 * Constructs a request resolver from a pure function.
 *
 * **Example** (Creating a resolver from a pure function)
 *
 * ```ts
 * import { Effect, Request, RequestResolver } from "effect"
 *
 * interface GetSquareRequest extends Request.Request<number> {
 *   readonly _tag: "GetSquareRequest"
 *   readonly value: number
 * }
 * const GetSquareRequest = Request.tagged<GetSquareRequest>("GetSquareRequest")
 *
 * // Create a resolver from a pure function
 * const SquareResolver = RequestResolver.fromFunction<GetSquareRequest>(
 *   (entry) => entry.request.value * entry.request.value
 * )
 *
 * // Usage
 * const getSquareEffect = Effect.request(
 *   GetSquareRequest({ value: 5 }),
 *   SquareResolver
 * )
 * // Will resolve to 25
 * ```
 *
 * @category constructors
 * @since 2.0.0
 */
export const fromFunction = f => make(entries => Effect.sync(() => {
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    entry.completeUnsafe(exitSucceed(f(entry)));
  }
}));
/**
 * Constructs a request resolver from a pure function that takes a list of requests
 * and returns a list of results of the same size. Each item in the result
 * list must correspond to the item at the same index in the request list.
 *
 * **Example** (Batching pure request handling)
 *
 * ```ts
 * import { Effect, Request, RequestResolver } from "effect"
 *
 * interface GetDoubleRequest extends Request.Request<number> {
 *   readonly _tag: "GetDoubleRequest"
 *   readonly value: number
 * }
 * const GetDoubleRequest = Request.tagged<GetDoubleRequest>("GetDoubleRequest")
 *
 * // Create a resolver that processes multiple requests in a batch
 * const DoubleResolver = RequestResolver.fromFunctionBatched<GetDoubleRequest>(
 *   (entries) => entries.map((entry) => entry.request.value * 2)
 * )
 *
 * // Usage with multiple requests
 * const effects = [1, 2, 3].map((value) =>
 *   Effect.request(GetDoubleRequest({ value }), DoubleResolver)
 * )
 * const batchedEffect = Effect.all(effects) // [2, 4, 6]
 * ```
 *
 * @category constructors
 * @since 2.0.0
 */
export const fromFunctionBatched = f => make(entries => Effect.sync(() => {
  let i = 0;
  for (const result of f(entries)) {
    const entry = entries[i++];
    entry.completeUnsafe(exitSucceed(result));
  }
}));
/**
 * Constructs a request resolver from an effectual function.
 *
 * **Example** (Creating a resolver from an effectful function)
 *
 * ```ts
 * import { Effect, Request, RequestResolver } from "effect"
 *
 * interface GetUserFromAPIRequest extends Request.Request<string> {
 *   readonly _tag: "GetUserFromAPIRequest"
 *   readonly id: number
 * }
 * const GetUserFromAPIRequest = Request.tagged<GetUserFromAPIRequest>(
 *   "GetUserFromAPIRequest"
 * )
 *
 * // Create a resolver that uses effects (like HTTP calls)
 * const UserAPIResolver = RequestResolver.fromEffect<GetUserFromAPIRequest>(
 *   (entry) =>
 *     Effect.gen(function*() {
 *       // Simulate an API call
 *       yield* Effect.sleep("100 millis")
 *       // Just return the result without error handling for simplicity
 *       return `User ${entry.request.id} from API`
 *     })
 * )
 *
 * // Usage
 * const getUserEffect = Effect.request(
 *   GetUserFromAPIRequest({ id: 123 }),
 *   UserAPIResolver
 * )
 * ```
 *
 * @category constructors
 * @since 2.0.0
 */
export const fromEffect = f => {
  effect.interruptChildrenPatch(); // ensure middleware is registered
  return make(entries => Effect.callback(resume => {
    const parent = effect.getCurrentFiber();
    let done = 0;
    for (let i = 0; i < entries.length; i++) {
      const entry = entries[i];
      const fiber = effect.forkUnsafe(parent, f(entry), true);
      fiber.addObserver(exit => {
        entry.completeUnsafe(exit);
        done++;
        if (done === entries.length) {
          resume(effect.void);
        }
      });
    }
  }));
};
/**
 * Constructs a request resolver from a list of tags paired to functions, that takes
 * a list of requests and returns a list of results of the same size. Each item
 * in the result list must correspond to the item at the same index in the
 * request list.
 *
 * **Example** (Handling tagged request batches)
 *
 * ```ts
 * import { Effect, RequestResolver } from "effect"
 * import type { Request } from "effect"
 *
 * interface GetUser extends Request.Request<string, Error> {
 *   readonly _tag: "GetUser"
 *   readonly id: number
 * }
 *
 * interface GetPost extends Request.Request<string, Error> {
 *   readonly _tag: "GetPost"
 *   readonly id: number
 * }
 *
 * type MyRequest = GetUser | GetPost
 *
 * // Create a resolver that handles different request types
 * const MyResolver = RequestResolver.fromEffectTagged<MyRequest>()({
 *   GetUser: (requests) =>
 *     Effect.succeed(requests.map((req) => `User ${req.request.id}`)),
 *   GetPost: (requests) =>
 *     Effect.succeed(requests.map((req) => `Post ${req.request.id}`))
 * })
 * ```
 *
 * @category constructors
 * @since 2.0.0
 */
export const fromEffectTagged = () => fns => make(entries => {
  const grouped = new Map();
  for (let i = 0, len = entries.length; i < len; i++) {
    const group = grouped.get(entries[i].request._tag);
    if (group) {
      group.push(entries[i]);
    } else {
      grouped.set(entries[i].request._tag, [entries[i]]);
    }
  }
  return Effect.forEach(grouped, ([tag, requests]) => Effect.matchCause(fns[tag](requests), {
    onFailure: cause => {
      for (let i = 0; i < requests.length; i++) {
        const entry = requests[i];
        entry.completeUnsafe(exitFail(cause));
      }
    },
    onSuccess: res => {
      for (let i = 0; i < res.length; i++) {
        const entry = requests[i];
        entry.completeUnsafe(exitSucceed(res[i]));
      }
    }
  }), {
    concurrency: "unbounded",
    discard: true
  });
});
/**
 * Sets the batch delay effect for this request resolver.
 *
 * **Example** (Setting an effectful batch delay)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * const resolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.sync(() => {
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed("data"))
 *     }
 *   })
 * )
 *
 * // Set a custom delay effect (e.g., with logging)
 * const resolverWithCustomDelay = RequestResolver.setDelayEffect(
 *   resolver,
 *   Effect.gen(function*() {
 *     yield* Effect.log("Waiting before processing batch...")
 *     yield* Effect.sleep("50 millis")
 *   })
 * )
 * ```
 *
 * @category delay
 * @since 4.0.0
 */
export const setDelayEffect = /*#__PURE__*/dual(2, (self, delay) => makeWith({
  ...self,
  delay
}));
/**
 * Sets the batch delay window for this request resolver to the specified duration.
 *
 * **Example** (Setting a batch delay)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * const resolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.sync(() => {
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed("data"))
 *     }
 *   })
 * )
 *
 * // Add a 100ms delay to batch requests together
 * const delayedResolver = RequestResolver.setDelay(resolver, "100 millis")
 *
 * // Can also use number for milliseconds
 * const delayedResolver2 = RequestResolver.setDelay(resolver, 100)
 * ```
 *
 * @category delay
 * @since 4.0.0
 */
export const setDelay = /*#__PURE__*/dual(2, (self, duration) => makeWith({
  ...self,
  delay: Effect.sleep(duration)
}));
/**
 * Wraps request resolver execution between `before` and `after` effects.
 *
 * **Example** (Running effects around request resolution)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * const resolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.sync(() => {
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed("data"))
 *     }
 *   })
 * )
 *
 * // Add setup and cleanup around request execution
 * const resolverWithAround = RequestResolver.around(
 *   resolver,
 *   (entries) =>
 *     Effect.gen(function*() {
 *       yield* Effect.log(`Starting batch of ${entries.length} requests`)
 *       return entries.length
 *     }),
 *   (entries, initialSize) =>
 *     Effect.gen(function*() {
 *       yield* Effect.log(
 *         `Batch completed with ${entries.length} requests (started with ${initialSize})`
 *       )
 *     })
 * )
 * ```
 *
 * @category combinators
 * @since 2.0.0
 */
export const around = /*#__PURE__*/dual(3, (self, before, after) => makeWith({
  ...self,
  runAll: (entries, key) => Effect.acquireUseRelease(before(entries), () => self.runAll(entries, key), a => after(entries, a))
}));
/**
 * Creates a request resolver that never executes requests.
 *
 * **When to use**
 *
 * Use as a resolver value for request types that are statically impossible and
 * should never be issued.
 *
 * **Gotchas**
 *
 * If this resolver is used for an actual request, the request waits forever
 * unless the fiber is interrupted.
 *
 * @see {@link make} for constructing a resolver that executes batches and completes request entries
 *
 * @category constructors
 * @since 2.0.0
 */
export const never = /*#__PURE__*/make(() => Effect.never);
/**
 * Returns a request resolver that collects at most `n` requests into each
 * batch.
 *
 * **Details**
 *
 * When more than `n` requests are waiting for the same resolver and batch key,
 * the current batch is run and additional requests are collected into later
 * batches.
 *
 * **Example** (Limiting parallel request batches)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 *   readonly id: number
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * const resolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.sync(() => {
 *     console.log(`Processing batch of ${entries.length} requests`)
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed(`data-${entry.request.id}`))
 *     }
 *   })
 * )
 *
 * // Limit batches to maximum 5 requests
 * const limitedResolver = RequestResolver.batchN(resolver, 5)
 *
 * // When more than 5 requests are made, they'll be split into multiple batches
 * const requests = Array.from(
 *   { length: 12 },
 *   (_, i) => Effect.request(GetDataRequest({ id: i }), limitedResolver)
 * )
 * ```
 *
 * @category combinators
 * @since 2.0.0
 */
export const batchN = /*#__PURE__*/dual(2, (self, n) => makeWith({
  ...self,
  collectWhile: requests => requests.size < n
}));
/**
 * Transforms a request resolver by grouping requests using the specified key
 * function.
 *
 * **Example** (Grouping resolver requests)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetUserRequest extends Request.Request<string> {
 *   readonly _tag: "GetUserRequest"
 *   readonly userId: number
 *   readonly department: string
 * }
 * const GetUserRequest = Request.tagged<GetUserRequest>("GetUserRequest")
 *
 * const resolver = RequestResolver.make<GetUserRequest>((entries) =>
 *   Effect.sync(() => {
 *     console.log(`Processing ${entries.length} users`)
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed(`User ${entry.request.userId}`))
 *     }
 *   })
 * )
 *
 * // Group requests by department for more efficient processing
 * const groupedResolver = RequestResolver.grouped(
 *   resolver,
 *   ({ request }) => request.department
 * )
 *
 * // Requests for the same department will be batched together
 * const requests = [
 *   Effect.request(
 *     GetUserRequest({ userId: 1, department: "Engineering" }),
 *     groupedResolver
 *   ),
 *   Effect.request(
 *     GetUserRequest({ userId: 2, department: "Engineering" }),
 *     groupedResolver
 *   ),
 *   Effect.request(
 *     GetUserRequest({ userId: 3, department: "Marketing" }),
 *     groupedResolver
 *   )
 * ]
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const grouped = /*#__PURE__*/dual(2, (self, f) => makeWith({
  ...self,
  batchKey: hashGroupKey(f)
}));
/**
 * Returns a request resolver that sends each batch to both resolvers and
 * completes with the first resolver to finish.
 *
 * **Details**
 *
 * The losing resolver run is interrupted after the winning resolver completes
 * the batch.
 *
 * **Example** (Racing request resolvers)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 *   readonly id: number
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * // Fast resolver (simulating cache)
 * const fastResolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.gen(function*() {
 *     yield* Effect.sleep("10 millis")
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed(`fast-${entry.request.id}`))
 *     }
 *   })
 * )
 *
 * // Slow resolver (simulating database)
 * const slowResolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.gen(function*() {
 *     yield* Effect.sleep("100 millis")
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed(`slow-${entry.request.id}`))
 *     }
 *   })
 * )
 *
 * // Race resolvers - will use whichever completes first
 * const racingResolver = RequestResolver.race(fastResolver, slowResolver)
 * ```
 *
 * @category combinators
 * @since 2.0.0
 */
export const race = /*#__PURE__*/dual(2, (self, that) => make((requests, key) => effect.race(self.runAll(requests, key), that.runAll(requests, key))));
/**
 * Adds a tracing span to the request resolver, which will also add any span
 * links from the request's.
 *
 * **Example** (Adding a tracing span)
 *
 * ```ts
 * import { Effect, Exit, Request, RequestResolver } from "effect"
 *
 * interface GetDataRequest extends Request.Request<string> {
 *   readonly _tag: "GetDataRequest"
 *   readonly id: number
 * }
 * const GetDataRequest = Request.tagged<GetDataRequest>("GetDataRequest")
 *
 * const resolver = RequestResolver.make<GetDataRequest>((entries) =>
 *   Effect.sync(() => {
 *     for (const entry of entries) {
 *       entry.completeUnsafe(Exit.succeed(`data-${entry.request.id}`))
 *     }
 *   })
 * )
 *
 * // Add tracing span with custom name and attributes
 * const tracedResolver = RequestResolver.withSpan(
 *   resolver,
 *   "user-data-resolver",
 *   {
 *     attributes: {
 *       "resolver.type": "user-data",
 *       "resolver.version": "1.0"
 *     }
 *   }
 * )
 *
 * // Spans will automatically include batch size and request links
 * const effect = Effect.request(GetDataRequest({ id: 123 }), tracedResolver)
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withSpan = /*#__PURE__*/dual(args => isRequestResolver(args[0]), (self, name, options) => makeWith({
  ...self,
  runAll: (entries, key) => Effect.suspend(() => {
    const opts = typeof options === "function" ? options(entries) : options;
    const links = opts?.links ? opts.links.slice() : [];
    const seen = new Set();
    for (const entry of entries) {
      const span = Context.getOption(entry.context, Tracer.ParentSpan);
      if (span._tag === "None" || seen.has(span.value)) continue;
      seen.add(span.value);
      links.push({
        span: span.value,
        attributes: {}
      });
    }
    return Effect.withSpan(self.runAll(entries, key), name, {
      ...options,
      links,
      attributes: {
        batchSize: entries.length,
        ...opts?.attributes
      }
    });
  })
}));
/**
 * Wraps a request resolver in a cache, allowing it to cache results up to a
 * specified capacity and optional time-to-live.
 *
 * **When to use**
 *
 * Use to turn a request resolver into a first-class `Cache` when callers need
 * cache lookup, refresh, invalidation, or inspection around request results.
 *
 * **Details**
 *
 * The request value is the cache key. Cache misses run the resolver via
 * `Effect.request`, `timeToLive` receives the request `Exit` and the request,
 * and `requireServicesAt` controls whether services are required at lookup time
 * or construction time.
 *
 * **Gotchas**
 *
 * Cache hits depend on the request value's equality semantics.
 *
 * @see {@link withCache} for keeping caching behind a resolver used with `Effect.request`
 * @see {@link persisted} for storing persistable request results outside process memory
 * @see {@link Cache.Cache} for operations available on the returned cache
 *
 * @category caching
 * @since 4.0.0
 */
export const asCache = /*#__PURE__*/dual(2, (self, options) => Cache.makeWith(req => internal.request(req, self), {
  capacity: options.capacity,
  timeToLive: options.timeToLive,
  requireServicesAt: options.requireServicesAt ?? "lookup"
}));
/**
 * Adds a bounded in-memory cache to a request resolver.
 *
 * **When to use**
 *
 * Use to reuse completed results for repeated equal request values while still
 * passing a `RequestResolver` to `Effect.request`.
 *
 * **Details**
 *
 * Running the returned effect creates the cache and returns a wrapped resolver.
 * The cache stores completed success or failure results by request equality up
 * to `capacity`. The `strategy` option controls eviction order and defaults to
 * `"lru"`; `"fifo"` keeps insertion order.
 *
 * **Gotchas**
 *
 * Entries do not expire by time, and completed failures are cached the same as
 * successes. Request equality controls cache hits.
 *
 * @see {@link asCache} for exposing the resolver as a `Cache` with time-to-live and service lookup controls
 * @see {@link persisted} for backing persistable requests with the configured persistence store
 *
 * @category caching
 * @since 4.0.0
 */
export const withCache = /*#__PURE__*/dual(2, (self, options) => Effect.sync(() => {
  const strategy = options.strategy ?? "lru";
  const cache = MutableHashMap.empty();
  return makeWith({
    ...self,
    runAll(entries, key) {
      return Effect.onExit(self.runAll(entries, key), () => {
        let toRemove = MutableHashMap.size(cache) - options.capacity;
        if (toRemove <= 0) return Effect.void;
        for (const k of MutableHashMap.keys(cache)) {
          MutableHashMap.remove(cache, k);
          toRemove--;
          if (toRemove <= 0) break;
        }
        return Effect.void;
      });
    },
    preCheck(entry) {
      const ocached = MutableHashMap.get(cache, entry.request);
      if (ocached._tag === "None") {
        const cached = {
          entry,
          exit: undefined
        };
        MutableHashMap.set(cache, entry.request, cached);
        const prevComplete = entry.completeUnsafe;
        entry.completeUnsafe = function (exit) {
          cached.exit = exit;
          prevComplete(exit);
        };
        return true;
      }
      const cached = ocached.value;
      if (cached.exit) {
        if (strategy === "lru") {
          MutableHashMap.remove(cache, cached.entry.request);
          MutableHashMap.set(cache, cached.entry.request, cached);
        }
        entry.completeUnsafe(cached.exit);
      } else {
        cached.entry.uninterruptible = true;
        const prevComplete = cached.entry.completeUnsafe;
        cached.entry.completeUnsafe = function (exit) {
          prevComplete(exit);
          entry.completeUnsafe(exit);
        };
      }
      return false;
    }
  });
}));
/**
 * Wraps a request resolver with persistent storage for persistable requests.
 *
 * **When to use**
 *
 * Use to keep a `RequestResolver` interface while reusing completed
 * `Persistable` request results through a `Persistence` store.
 *
 * **Details**
 *
 * Cached results are loaded from the configured persistence store before
 * running the underlying resolver. Missing entries are resolved normally and
 * written back to the store. Entries marked stale by `staleWhileRevalidate`
 * receive the stored result and are also resolved again so the refreshed result
 * can be written back to the store. Creating the persisted resolver requires
 * `Persistence.Persistence` and `Scope`.
 *
 * @see {@link withCache} for in-memory resolver caching that does not require persistable request values or a persistence store
 * @see {@link asCache} for exposing resolver results through a `Cache` instead of returning another resolver
 *
 * @category Persistence
 * @since 4.0.0
 */
export const persisted = /*#__PURE__*/dual(2, /*#__PURE__*/Effect.fnUntraced(function* (self, options) {
  const store = yield* (yield* Persistence.Persistence).make(options);
  return makeWith({
    ...self,
    runAll: Effect.fnUntraced(function* (entries, key) {
      const results = yield* store.getMany(Iterable.map(entries, _ => _.request)).pipe(Effect.provideContext(entries[0].context));
      const leftover = [];
      const toPersist = new Map();
      for (let i = 0; i < results.length; i++) {
        const entry = entries[i];
        const exit = results[i];
        if (exit === undefined || options.staleWhileRevalidate && options.staleWhileRevalidate(exit, entry.request)) {
          const prevComplete = entry.completeUnsafe;
          entry.completeUnsafe = function (exit) {
            toPersist.set(entry.request, exit);
            prevComplete(exit);
          };
          leftover.push(entry);
          if (exit === undefined) continue;
        }
        entry.completeUnsafe(exit);
      }
      if (!Arr.isArrayNonEmpty(leftover)) {
        return;
      }
      yield* Effect.catchCause(self.runAll(leftover, key), cause => {
        for (let i = 0; i < leftover.length; i++) {
          const entry = leftover[i];
          if (!toPersist.has(entry.request)) continue;
          entry.completeUnsafe(Exit.failCause(cause));
        }
        return Effect.void;
      });
      yield* store.setMany(toPersist).pipe(Effect.provideContext(entries[0].context));
    })
  });
}));
//# sourceMappingURL=RequestResolver.js.map