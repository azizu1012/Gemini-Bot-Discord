/**
 * The `AtomHttpApi` module adapts typed `HttpApi` clients to the unstable atom
 * reactivity runtime. Use it to define a `Context.Service` whose generated HTTP
 * API client is available directly and whose endpoints can also be invoked as
 * atoms: `query` creates an atom of `AsyncResult` for reads, while `mutation`
 * creates an `AtomResultFn` for writes.
 *
 * It is intended for applications that want server state to participate in atom
 * caching, invalidation, and hydration. Queries can be associated with
 * `reactivityKeys` so they refresh when those keys are invalidated, mutations can
 * invalidate the same keys after the request succeeds, and `timeToLive` controls
 * whether idle query atoms expire, stay alive for a duration, or are kept alive.
 *
 * Serialization is schema-based and intentionally limited to decoded values.
 * Mutation atoms are serializable only in `"decoded-only"` mode, while query
 * atoms are serializable only in `"decoded-only"` mode when a stable
 * `serializationKey` is supplied. Choose serialization keys that uniquely
 * identify the endpoint request, keep reactivity keys stable across client and
 * server registries during hydration, and avoid serializing response modes that
 * expose raw `HttpClientResponse` values.
 *
 * The service wraps `HttpApiClient.make`, so the same `HttpApi` definition,
 * schemas, base URL, middleware services, and HTTP client layer must be available
 * wherever the atom runtime is constructed. Use `transformClient` and
 * `transformResponse` for cross-cutting client behavior, and remember that
 * schema or low-level HTTP client failures are raised as defects while endpoint
 * and middleware failures remain typed errors.
 *
 * @since 4.0.0
 */
import * as Context from "../../Context.js";
import * as Duration from "../../Duration.js";
import * as Effect from "../../Effect.js";
import * as Layer from "../../Layer.js";
import * as Schema from "../../Schema.js";
import * as HttpClientError from "../http/HttpClientError.js";
import * as HttpApiClient from "../httpapi/HttpApiClient.js";
import * as HttpApiEndpoint from "../httpapi/HttpApiEndpoint.js";
import * as AsyncResult from "./AsyncResult.js";
import * as Atom from "./Atom.js";
import * as Reactivity from "./Reactivity.js";
/**
 * Creates a `Context.Service` class for an HTTP API client backed by an atom
 * runtime.
 *
 * **Details**
 *
 * The options provide the API definition, HTTP client layer, optional client and
 * response transforms, base URL, and runtime factory used by the query and
 * mutation helpers.
 *
 * @category constructors
 * @since 4.0.0
 */
export const Service = () => (id, options) => {
  const self = Context.Service()(id);
  const layer = Layer.effect(self, HttpApiClient.make(options.api, options));
  const runtimeFactory = options.runtime ?? Atom.runtime;
  self.runtime = runtimeFactory(typeof options.httpClient === "function" ? get => Layer.provide(layer, options.httpClient(get)) : Layer.provide(layer, options.httpClient));
  const catchErrors = Effect.catch(e => Schema.isSchemaError(e) || HttpClientError.isHttpClientError(e) ? Effect.die(e) : Effect.fail(e));
  const mutationFamily = Atom.family(({
    endpoint,
    group,
    responseMode
  }) => {
    const atom = self.runtime.fn()(Effect.fnUntraced(function* (opts) {
      const client = yield* self;
      const effect = catchErrors(client[group][endpoint]({
        ...opts,
        responseMode
      }));
      return yield* opts.reactivityKeys ? Reactivity.mutation(effect, opts.reactivityKeys) : effect;
    }));
    if (responseMode === "decoded-only") {
      const definition = options.api.groups[group].endpoints[endpoint];
      return Atom.serializable(atom, {
        key: `AtomHttpApi:mutation:${group}:${endpoint}`,
        schema: AsyncResult.Schema({
          success: Schema.Union(HttpApiEndpoint.getSuccessSchemas(definition)),
          error: Schema.Union(HttpApiEndpoint.getErrorSchemas(definition))
        })
      });
    }
    return atom;
  });
  self.mutation = (group, endpoint, options) => mutationFamily({
    group,
    endpoint,
    responseMode: options?.responseMode ?? "decoded-only"
  });
  const queryFamily = Atom.family(opts => {
    let atom = self.runtime.atom(self.use(client_ => {
      const client = client_;
      return catchErrors(client[opts.group][opts.endpoint](opts));
    }));
    if (opts.responseMode === "decoded-only" && opts.serializationKey) {
      const endpoint = options.api.groups[opts.group].endpoints[opts.endpoint];
      atom = Atom.serializable(atom, {
        key: `AtomHttpApi:${opts.group}:${opts.endpoint}:${opts.serializationKey}`,
        schema: AsyncResult.Schema({
          success: Schema.Union(HttpApiEndpoint.getSuccessSchemas(endpoint)),
          error: Schema.Union(HttpApiEndpoint.getErrorSchemas(endpoint))
        })
      });
    }
    if (opts.timeToLive) {
      atom = Duration.isFinite(opts.timeToLive) ? Atom.setIdleTTL(atom, opts.timeToLive) : Atom.keepAlive(atom);
    }
    return opts.reactivityKeys ? self.runtime.factory.withReactivity(opts.reactivityKeys)(atom) : atom;
  });
  self.query = (group, endpoint, request) => {
    const key = {
      group,
      endpoint,
      params: request.params,
      query: request.query,
      payload: request.payload,
      headers: request.headers,
      responseMode: request.responseMode ?? "decoded-only",
      reactivityKeys: request.reactivityKeys,
      timeToLive: request.timeToLive ? Duration.fromInputUnsafe(request.timeToLive) : undefined,
      serializationKey: request.serializationKey
    };
    return queryFamily(key);
  };
  return self;
};
//# sourceMappingURL=AtomHttpApi.js.map