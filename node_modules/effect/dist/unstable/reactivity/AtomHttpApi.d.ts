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
import * as Context from "../../Context.ts";
import * as Duration from "../../Duration.ts";
import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import type { ReadonlyRecord } from "../../Record.ts";
import * as Schema from "../../Schema.ts";
import type { Simplify } from "../../Types.ts";
import type * as HttpClient from "../http/HttpClient.ts";
import type { HttpClientResponse } from "../http/HttpClientResponse.ts";
import type * as HttpApi from "../httpapi/HttpApi.ts";
import * as HttpApiClient from "../httpapi/HttpApiClient.ts";
import * as HttpApiEndpoint from "../httpapi/HttpApiEndpoint.ts";
import type * as HttpApiGroup from "../httpapi/HttpApiGroup.ts";
import type * as HttpApiMiddleware from "../httpapi/HttpApiMiddleware.ts";
import * as AsyncResult from "./AsyncResult.ts";
import * as Atom from "./Atom.ts";
/**
 * A `Context.Service` for an HTTP API client integrated with atom reactivity.
 *
 * **Details**
 *
 * It exposes the generated HTTP API client, an atom runtime, mutation helpers that
 * return `AtomResultFn`s, and query helpers that return atoms of endpoint results.
 *
 * @category models
 * @since 4.0.0
 */
export interface AtomHttpApiClient<Self, Id extends string, Groups extends HttpApiGroup.Any> extends Context.Service<Self, HttpApiClient.Client<Groups, never, never>> {
    new (_: never): Context.ServiceClass.Shape<Id, HttpApiClient.Client<Groups, never, never>>;
    readonly runtime: Atom.AtomRuntime<Self>;
    readonly mutation: <GroupName extends HttpApiGroup.Name<Groups>, Name extends HttpApiEndpoint.Name<HttpApiGroup.Endpoints<Group>>, Group extends HttpApiGroup.Any = HttpApiGroup.WithName<Groups, GroupName>, Endpoint extends HttpApiEndpoint.Any = HttpApiEndpoint.WithName<HttpApiGroup.Endpoints<Group>, Name>, const ResponseMode extends HttpApiEndpoint.ClientResponseMode = HttpApiEndpoint.ClientResponseMode>(group: GroupName, endpoint: Name, options?: {
        readonly responseMode?: ResponseMode | undefined;
    }) => [Endpoint] extends [
        HttpApiEndpoint.HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _Middleware, infer _RE>
    ] ? Atom.AtomResultFn<Simplify<HttpApiEndpoint.ClientRequest<_Params, _Query, _Payload, _Headers, "decoded-only"> & {
        readonly reactivityKeys?: ReadonlyArray<unknown> | ReadonlyRecord<string, ReadonlyArray<unknown>> | undefined;
    }>, ResponseByMode<_Success["Type"], ResponseMode>, ErrorByMode<_Error, _Middleware, ResponseMode>> : never;
    readonly query: <GroupName extends HttpApiGroup.Name<Groups>, Name extends HttpApiEndpoint.Name<HttpApiGroup.Endpoints<Group>>, Group extends HttpApiGroup.Any = HttpApiGroup.WithName<Groups, GroupName>, Endpoint extends HttpApiEndpoint.Any = HttpApiEndpoint.WithName<HttpApiGroup.Endpoints<Group>, Name>, const ResponseMode extends HttpApiEndpoint.ClientResponseMode = "decoded-only">(group: GroupName, endpoint: Name, request: [Endpoint] extends [
        HttpApiEndpoint.HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _R, infer _RE>
    ] ? Simplify<HttpApiEndpoint.ClientRequest<_Params, _Query, _Payload, _Headers, ResponseMode> & {
        readonly reactivityKeys?: ReadonlyArray<unknown> | ReadonlyRecord<string, ReadonlyArray<unknown>> | undefined;
        readonly timeToLive?: Duration.Input | undefined;
        readonly serializationKey?: string | undefined;
    }> : never) => [Endpoint] extends [
        HttpApiEndpoint.HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _Middleware, infer _RE>
    ] ? Atom.Atom<AsyncResult.AsyncResult<ResponseByMode<_Success["Type"], ResponseMode>, ErrorByMode<_Error, _Middleware, ResponseMode>>> : never;
}
declare global {
    interface ErrorConstructor {
        stackTraceLimit: number;
    }
}
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
export declare const Service: <Self>() => <const Id extends string, ApiId extends string, Groups extends HttpApiGroup.Any>(id: Id, options: {
    readonly api: HttpApi.HttpApi<ApiId, Groups>;
    readonly httpClient: Layer.Layer<HttpApiGroup.ClientServices<Groups> | HttpClient.HttpClient> | ((get: Atom.AtomContext) => Layer.Layer<HttpApiGroup.ClientServices<Groups> | HttpClient.HttpClient>);
    readonly transformClient?: ((client: HttpClient.HttpClient) => HttpClient.HttpClient) | undefined;
    readonly transformResponse?: ((effect: Effect.Effect<unknown, unknown, unknown>) => Effect.Effect<unknown, unknown, unknown>) | undefined;
    readonly baseUrl?: URL | string | undefined;
    readonly runtime?: Atom.RuntimeFactory | undefined;
}) => AtomHttpApiClient<Self, Id, Groups>;
type ResponseByMode<Success, ResponseMode extends HttpApiEndpoint.ClientResponseMode> = [ResponseMode] extends [
    "decoded-and-response"
] ? [Success, HttpClientResponse] : [ResponseMode] extends ["response-only"] ? HttpClientResponse : Success;
type ErrorByMode<Error extends Schema.Top, Middleware, ResponseMode extends HttpApiEndpoint.ClientResponseMode> = HttpApiMiddleware.Error<Middleware> | HttpApiMiddleware.ClientError<Middleware> | ([ResponseMode] extends ["response-only"] ? never : Error["Type"]);
export {};
//# sourceMappingURL=AtomHttpApi.d.ts.map