import * as Effect from "../../Effect.ts";
import * as Schema from "../../Schema.ts";
import type { Simplify } from "../../Types.ts";
import * as HttpClient from "../http/HttpClient.ts";
import * as HttpClientError from "../http/HttpClientError.ts";
import * as HttpClientResponse from "../http/HttpClientResponse.ts";
import * as HttpApi from "./HttpApi.ts";
import * as HttpApiEndpoint from "./HttpApiEndpoint.ts";
import type * as HttpApiGroup from "./HttpApiGroup.ts";
import type * as HttpApiMiddleware from "./HttpApiMiddleware.ts";
/**
 * The type-safe client shape generated from HTTP API groups, with non-top-level
 * groups exposed as nested objects and top-level endpoints exposed as methods.
 *
 * @category models
 * @since 4.0.0
 */
export type Client<Groups extends HttpApiGroup.Any, E = never, R = never> = Simplify<{
    readonly [Group in Extract<Groups, {
        readonly topLevel: false;
    }> as HttpApiGroup.Name<Group>]: Client.Group<Group, Group["identifier"], E, R>;
} & {
    readonly [Method in Client.TopLevelMethods<Groups, E, R> as Method[0]]: Method[1];
}>;
/**
 * Derives the typed client interface for an `HttpApi`, preserving any additional
 * client error and service requirements supplied by the caller.
 *
 * @category models
 * @since 4.0.0
 */
export type ForApi<Api extends HttpApi.Any, E = never, R = never> = Api extends HttpApi.HttpApi<infer _Id, infer Groups> ? Client<Groups, E, R> : never;
/**
 * Helper types used to describe generated HTTP API clients, including endpoint
 * methods, response modes, and grouped client shapes.
 *
 * @since 4.0.0
 */
export declare namespace Client {
    /**
     * The response mode accepted by generated client methods, controlling whether a
     * call returns the decoded success value, the raw response, or both.
     *
     * @category models
     * @since 4.0.0
     */
    type ResponseMode = HttpApiEndpoint.ClientResponseMode;
    /**
     * Computes the value returned by a client method for a success type and response
     * mode.
     *
     * @category models
     * @since 4.0.0
     */
    type Response<Success, Mode extends ResponseMode> = [Mode] extends ["decoded-and-response"] ? [Success, HttpClientResponse.HttpClientResponse] : [Mode] extends ["response-only"] ? HttpClientResponse.HttpClientResponse : Success;
    /**
     * The client object for one API group, mapping each endpoint name in that group to
     * its typed client method.
     *
     * @category models
     * @since 4.0.0
     */
    type Group<Groups extends HttpApiGroup.Any, GroupName extends Groups["identifier"], E, R> = [
        HttpApiGroup.WithName<Groups, GroupName>
    ] extends [HttpApiGroup.HttpApiGroup<infer _GroupName, infer _Endpoints>] ? {
        readonly [Endpoint in _Endpoints as HttpApiEndpoint.Name<Endpoint>]: Method<Endpoint, E, R>;
    } : never;
    /**
     * The typed function generated for an endpoint, accepting the endpoint request
     * shape and returning an effect whose success, error, and service channels reflect
     * the endpoint schemas, middleware, and selected response mode.
     *
     * @category models
     * @since 4.0.0
     */
    type Method<Endpoint, E, R> = [Endpoint] extends [
        HttpApiEndpoint.HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _Middleware, infer _MR>
    ] ? <Mode extends ResponseMode = ResponseMode>(request: Simplify<HttpApiEndpoint.ClientRequest<_Params, _Query, _Payload, _Headers, Mode>>) => Effect.Effect<Response<_Success["Type"], Mode>, HttpApiMiddleware.Error<_Middleware> | HttpApiMiddleware.ClientError<_Middleware> | E | HttpClientError.HttpClientError | ([Mode] extends ["response-only"] ? never : _Error["Type"] | Schema.SchemaError), R | _Params["EncodingServices"] | _Query["EncodingServices"] | _Payload["EncodingServices"] | _Headers["EncodingServices"] | ([Mode] extends ["response-only"] ? never : _Success["DecodingServices"] | _Error["DecodingServices"])> : never;
    /**
     * Extracts client methods for endpoints in top-level groups so they can be exposed
     * directly on the generated client object.
     *
     * @category models
     * @since 4.0.0
     */
    type TopLevelMethods<Groups extends HttpApiGroup.Any, E, R> = Extract<Groups, {
        readonly topLevel: true;
    }> extends HttpApiGroup.HttpApiGroup<infer _Id, infer _Endpoints, infer _TopLevel> ? _Endpoints extends infer Endpoint ? [HttpApiEndpoint.Name<Endpoint>, Method<Endpoint, E, R>] : never : never;
}
type UrlBuilderRequest<Endpoint extends HttpApiEndpoint.Any> = (([HttpApiEndpoint.Params<Endpoint>["Type"]] extends [never] ? {} : {
    readonly params: HttpApiEndpoint.Params<Endpoint>["Type"];
}) & ([HttpApiEndpoint.Query<Endpoint>["Type"]] extends [never] ? {} : {
    readonly query: HttpApiEndpoint.Query<Endpoint>["Type"];
})) extends infer Request ? keyof Request extends never ? void | undefined : Request : never;
type UrlBuilderArgs<Endpoint extends HttpApiEndpoint.Any> = [UrlBuilderRequest<Endpoint>] extends [void | undefined] ? [
    request?: UrlBuilderRequest<Endpoint>
] : [request: UrlBuilderRequest<Endpoint>];
/**
 * The type-safe URL builder shape for an HTTP API, mirroring the generated client
 * layout while returning URL strings instead of executing requests.
 *
 * @category models
 * @since 4.0.0
 */
export type UrlBuilder<Api extends HttpApi.Any> = Api extends HttpApi.HttpApi<infer _ApiId, infer Groups> ? Simplify<{
    readonly [Group in Extract<Groups, {
        readonly topLevel: false;
    }> as HttpApiGroup.Name<Group>]: UrlBuilderGroup<HttpApiGroup.Endpoints<Group>>;
} & {
    readonly [Method in UrlBuilderTopLevelMethods<Groups> as Method[0]]: Method[1];
}> : never;
type UrlBuilderGroup<Endpoints extends HttpApiEndpoint.Any> = {
    readonly [Endpoint in Endpoints as HttpApiEndpoint.Name<Endpoint>]: UrlBuilderMethod<Endpoint>;
};
type UrlBuilderMethod<Endpoint extends HttpApiEndpoint.Any> = (...args: UrlBuilderArgs<Endpoint>) => string;
type UrlBuilderTopLevelMethods<Groups extends HttpApiGroup.Any> = Extract<Groups, {
    readonly topLevel: true;
}> extends HttpApiGroup.HttpApiGroup<infer _Id, infer _Endpoints, infer _TopLevel> ? _Endpoints extends infer Endpoint extends HttpApiEndpoint.Any ? [
    HttpApiEndpoint.Name<Endpoint>,
    UrlBuilderMethod<Endpoint>
] : never : never;
/**
 * Constructs a type-safe client for an HTTP API using the `HttpClient` service,
 * endpoint schemas, middleware, and optional client or response transformations.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: <ApiId extends string, Groups extends HttpApiGroup.Any>(api: HttpApi.HttpApi<ApiId, Groups>, options?: {
    readonly transformClient?: ((client: HttpClient.HttpClient) => HttpClient.HttpClient) | undefined;
    readonly transformResponse?: ((effect: Effect.Effect<unknown, unknown, unknown>) => Effect.Effect<unknown, unknown, unknown>) | undefined;
    readonly baseUrl?: URL | string | undefined;
}) => Effect.Effect<Client<Groups>, never, HttpClient.HttpClient | HttpApiGroup.MiddlewareClient<Groups>>;
/**
 * Constructs a type-safe client for an HTTP API from the supplied `HttpClient`,
 * using the API metadata to encode requests, execute middleware, and decode
 * responses.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const makeWith: <ApiId extends string, Groups extends HttpApiGroup.Any, E, R>(api: HttpApi.HttpApi<ApiId, Groups>, options: {
    readonly httpClient: HttpClient.HttpClient.With<E, R>;
    readonly transformResponse?: ((effect: Effect.Effect<unknown, unknown, unknown>) => Effect.Effect<unknown, unknown, unknown>) | undefined;
    readonly baseUrl?: URL | string | undefined;
}) => Effect.Effect<Client<Groups, E, R>, never, HttpApiGroup.MiddlewareClient<Groups>>;
/**
 * Builds a typed client object for a single API group from the supplied
 * `HttpClient`, filtering the API to that group.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const group: <ApiId extends string, Groups extends HttpApiGroup.Any, const GroupName extends HttpApiGroup.Name<Groups>, E, R>(api: HttpApi.HttpApi<ApiId, Groups>, options: {
    readonly group: GroupName;
    readonly httpClient: HttpClient.HttpClient.With<E, R>;
    readonly transformResponse?: ((effect: Effect.Effect<unknown, unknown, unknown>) => Effect.Effect<unknown, unknown, unknown>) | undefined;
    readonly baseUrl?: URL | string | undefined;
}) => Effect.Effect<Client.Group<Groups, GroupName, E, R>, never, HttpApiGroup.MiddlewareClient<HttpApiGroup.WithName<Groups, GroupName>>>;
/**
 * Builds the typed client method for one endpoint in one API group, using the
 * supplied `HttpClient` and endpoint metadata.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const endpoint: <ApiId extends string, Groups extends HttpApiGroup.Any, const GroupName extends HttpApiGroup.Name<Groups>, const EndpointName extends HttpApiEndpoint.Name<HttpApiGroup.EndpointsWithName<Groups, GroupName>>, E, R>(api: HttpApi.HttpApi<ApiId, Groups>, options: {
    readonly group: GroupName;
    readonly endpoint: EndpointName;
    readonly httpClient: HttpClient.HttpClient.With<E, R>;
    readonly transformClient?: ((client: HttpClient.HttpClient) => HttpClient.HttpClient) | undefined;
    readonly transformResponse?: ((effect: Effect.Effect<unknown, unknown, unknown>) => Effect.Effect<unknown, unknown, unknown>) | undefined;
    readonly baseUrl?: URL | string | undefined;
}) => Effect.Effect<Client.Method<HttpApiEndpoint.WithName<HttpApiGroup.Endpoints<HttpApiGroup.WithName<Groups, GroupName>>, EndpointName>, E, R>, never, HttpApiEndpoint.MiddlewareClient<HttpApiEndpoint.WithName<HttpApiGroup.Endpoints<HttpApiGroup.WithName<Groups, GroupName>>, EndpointName>>>;
/**
 * Creates a type-safe URL builder that mirrors `HttpApiClient.make`.
 *
 * **Example** (Building typed URLs)
 *
 * ```ts
 * import { Schema } from "effect"
 * import { HttpApi, HttpApiClient, HttpApiEndpoint, HttpApiGroup } from "effect/unstable/httpapi"
 *
 * const Api = HttpApi.make("Api").add(
 *   HttpApiGroup.make("users").add(
 *     HttpApiEndpoint.get("getUser", "/users/:id", {
 *       params: { id: Schema.String }
 *     })
 *   )
 * )
 *
 * const buildUrl = HttpApiClient.urlBuilder(Api, {
 *   baseUrl: "https://api.example.com"
 * })
 *
 * buildUrl.users.getUser({
 *   params: { id: "123" }
 * })
 * //=> "https://api.example.com/users/123"
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const urlBuilder: <Api extends HttpApi.Any>(api: Api, options?: {
    readonly baseUrl?: URL | string | undefined;
}) => UrlBuilder<Api>;
export {};
//# sourceMappingURL=HttpApiClient.d.ts.map