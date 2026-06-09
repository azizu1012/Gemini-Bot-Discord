import type { Brand } from "../../Brand.ts";
import * as Context from "../../Context.ts";
import type { Effect } from "../../Effect.ts";
import { type Pipeable } from "../../Pipeable.ts";
import * as Schema from "../../Schema.ts";
import type * as Stream from "../../Stream.ts";
import type * as Types from "../../Types.ts";
import type { HttpMethod } from "../http/HttpMethod.ts";
import * as HttpRouter from "../http/HttpRouter.ts";
import type { HttpServerRequest } from "../http/HttpServerRequest.ts";
import type { HttpServerResponse } from "../http/HttpServerResponse.ts";
import type * as Multipart from "../http/Multipart.ts";
import type * as HttpApiGroup from "./HttpApiGroup.ts";
import type * as HttpApiMiddleware from "./HttpApiMiddleware.ts";
import * as HttpApiSchema from "./HttpApiSchema.ts";
declare const TypeId = "~effect/httpapi/HttpApiEndpoint";
/**
 * Returns `true` when a value is an `HttpApiEndpoint`, narrowing the value to the
 * endpoint interface.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isHttpApiEndpoint: (u: unknown) => u is HttpApiEndpoint<any, any, any>;
/**
 * Maps content types to the payload encoding strategy and one or more schemas that
 * can decode or encode payloads for that content type.
 *
 * @category models
 * @since 4.0.0
 */
export type PayloadMap = ReadonlyMap<string, {
    readonly encoding: HttpApiSchema.PayloadEncoding;
    readonly schemas: [Schema.Top, ...Array<Schema.Top>];
}>;
/**
 * Represents an API endpoint. An API endpoint is mapped to a single route on
 * the underlying `HttpRouter`.
 *
 * @category models
 * @since 4.0.0
 */
export interface HttpApiEndpoint<out Name extends string, out Method extends HttpMethod, out Path extends string, out Params extends Schema.Top = never, out Query extends Schema.Top = never, out Payload extends Schema.Top = never, out Headers extends Schema.Top = never, out Success extends Schema.Top = typeof HttpApiSchema.NoContent, out Error extends Schema.Top = never, in out Middleware = never, out MiddlewareR = never> extends Pipeable {
    readonly [TypeId]: {
        readonly _MiddlewareR: Types.Covariant<MiddlewareR>;
    };
    readonly "~Params": Params;
    readonly "~Query": Query;
    readonly "~Headers": Headers;
    readonly "~Payload": Payload;
    readonly "~Success": Success;
    readonly "~Error": Error;
    readonly name: Name;
    readonly path: Path;
    readonly method: Method;
    readonly params: Schema.Top | undefined;
    readonly query: Schema.Top | undefined;
    readonly headers: Schema.Top | undefined;
    readonly payload: PayloadMap;
    readonly success: ReadonlySet<Schema.Top>;
    readonly error: ReadonlySet<Schema.Top>;
    readonly annotations: Context.Context<never>;
    readonly middlewares: ReadonlySet<Context.Key<Middleware, any>>;
    /**
     * Add a prefix to the path of the endpoint.
     */
    prefix<const Prefix extends HttpRouter.PathInput>(prefix: Prefix): HttpApiEndpoint<Name, Method, `${Prefix}${Path}`, Params, Query, Payload, Headers, Success, Error, Middleware, MiddlewareR>;
    /**
     * Add an `HttpApiMiddleware` to the endpoint.
     */
    middleware<I extends HttpApiMiddleware.AnyId, S>(middleware: Context.Key<I, S>): HttpApiEndpoint<Name, Method, Path, Params, Query, Payload, Headers, Success, Error, Middleware | I, HttpApiMiddleware.ApplyServices<I, MiddlewareR>>;
    /**
     * Add an annotation on the endpoint.
     */
    annotate<I, S>(key: Context.Key<I, S>, value: Types.NoInfer<S>): HttpApiEndpoint<Name, Method, Path, Params, Query, Payload, Headers, Success, Error, Middleware, MiddlewareR>;
    /**
     * Merge the annotations of the endpoint with the provided context.
     */
    annotateMerge<I>(annotations: Context.Context<I>): HttpApiEndpoint<Name, Method, Path, Params, Query, Payload, Headers, Success, Error, Middleware, MiddlewareR>;
}
/**
 * A widened `HttpApiEndpoint` type used when the concrete method, path, schemas,
 * and middleware types are not needed.
 *
 * @category models
 * @since 4.0.0
 */
export interface Any extends Pipeable {
    readonly [TypeId]: any;
    readonly name: string;
    readonly ["~Success"]: Schema.Top;
    readonly ["~Error"]: Schema.Top;
}
/**
 * A widened endpoint type that preserves concrete runtime properties such as
 * method, path, schemas, annotations, and middleware sets.
 *
 * @category models
 * @since 4.0.0
 */
export interface AnyWithProps extends HttpApiEndpoint<string, HttpMethod, string, Schema.Top, Schema.Top, Schema.Top, Schema.Top, any, any> {
}
/**
 * Extracts the name literal from an `HttpApiEndpoint`.
 *
 * @category models
 * @since 4.0.0
 */
export type Name<Endpoint> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Name : never;
/**
 * Extracts the success schema associated with an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type Success<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Success : never;
/**
 * Extracts the error schema associated with an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type Error<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Error : never;
/**
 * Extracts the schema used for an endpoint's path parameters.
 *
 * @category models
 * @since 4.0.0
 */
export type Params<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Params : never;
/**
 * Extracts the schema used for an endpoint's query parameters.
 *
 * @category models
 * @since 4.0.0
 */
export type Query<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Query : never;
/**
 * Extracts the schema used for an endpoint's request payload.
 *
 * @category models
 * @since 4.0.0
 */
export type Payload<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Payload : never;
/**
 * Extracts the schema used for an endpoint's request headers.
 *
 * @category models
 * @since 4.0.0
 */
export type Headers<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Headers : never;
/**
 * Extracts the middleware identifiers attached to an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type Middleware<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _M : never;
/**
 * Computes the services provided by the middleware attached to an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareProvides<Endpoint extends Any> = HttpApiMiddleware.Provides<Middleware<Endpoint>>;
/**
 * Computes the client-side middleware services required by an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareClient<Endpoint extends Any> = HttpApiMiddleware.MiddlewareClient<Middleware<Endpoint>>;
/**
 * Computes the error types that can be produced by the middleware attached to an
 * endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareError<Endpoint extends Any> = HttpApiMiddleware.Error<Middleware<Endpoint>>;
/**
 * Computes the full error value union for an endpoint, including the endpoint
 * error schema's type and errors introduced by middleware.
 *
 * @category models
 * @since 4.0.0
 */
export type Errors<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Error["Type"] | HttpApiMiddleware.Error<Middleware<Endpoint>> : never;
/**
 * Computes the services required to encode an endpoint's error responses,
 * including services required by middleware error encoders.
 *
 * @category models
 * @since 4.0.0
 */
export type ErrorServicesEncode<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Error["EncodingServices"] | HttpApiMiddleware.ErrorServicesEncode<Middleware<Endpoint>> : never;
/**
 * Builds the decoded request shape passed to a normal endpoint handler, including
 * available params, query, payload, headers, the raw request, endpoint, and group.
 * Multipart stream payloads are exposed as streams of parts.
 *
 * @category models
 * @since 4.0.0
 */
export type Request<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? ([_Params["Type"]] extends [never] ? {} : {
    readonly params: _Params["Type"];
}) & ([_Query["Type"]] extends [never] ? {} : {
    readonly query: _Query["Type"];
}) & ([_Payload["Type"]] extends [never] ? {} : _Payload["Type"] extends Brand<HttpApiSchema.MultipartStreamTypeId> ? {
    readonly payload: Stream.Stream<Multipart.Part, Multipart.MultipartError>;
} : {
    readonly payload: _Payload["Type"];
}) & ([_Headers] extends [never] ? {} : {
    readonly headers: _Headers["Type"];
}) & {
    readonly request: HttpServerRequest;
    readonly endpoint: Endpoint;
    readonly group: HttpApiGroup.AnyWithProps;
} : {};
/**
 * Builds the request shape passed to a raw endpoint handler, including decoded
 * params, query, and headers plus the raw request, endpoint, and group, while
 * leaving payload handling to the raw request.
 *
 * @category models
 * @since 4.0.0
 */
export type RequestRaw<Endpoint extends Any> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? ([_Params["Type"]] extends [never] ? {} : {
    readonly params: _Params["Type"];
}) & ([_Query["Type"]] extends [never] ? {} : {
    readonly query: _Query["Type"];
}) & ([_Headers["Type"]] extends [never] ? {} : {
    readonly headers: _Headers["Type"];
}) & {
    readonly request: HttpServerRequest;
    readonly endpoint: Endpoint;
    readonly group: HttpApiGroup.AnyWithProps;
} : {};
/**
 * Builds the request object accepted by a generated client method, including only
 * the params, query, headers, payload, and response mode fields required by the
 * endpoint. Multipart payloads are supplied as `FormData`.
 *
 * @category models
 * @since 4.0.0
 */
export type ClientRequest<Params extends Schema.Top, Query extends Schema.Top, Payload extends Schema.Top, Headers extends Schema.Top, ResponseMode extends ClientResponseMode> = (([Params["Type"]] extends [never] ? {} : {
    readonly params: Params["Type"];
}) & ([Query["Type"]] extends [never] ? {} : {
    readonly query: Query["Type"];
}) & ([Headers["Type"]] extends [never] ? {} : {
    readonly headers: Headers["Type"];
}) & ([Payload["Type"]] extends [never] ? {} : Payload["Type"] extends infer P ? P extends Brand<HttpApiSchema.MultipartTypeId> | Brand<HttpApiSchema.MultipartStreamTypeId> ? {
    readonly payload: FormData;
} : {
    readonly payload: Payload["Type"];
} : {
    readonly payload: Payload["Type"];
})) extends infer Req ? keyof Req extends never ? (void | {
    readonly responseMode?: ResponseMode;
}) : Req & {
    readonly responseMode?: ResponseMode;
} : void;
/**
 * Controls what a generated client method returns: the decoded success value,
 * the decoded value paired with the raw response, or only the raw response.
 *
 * @category models
 * @since 4.0.0
 */
export type ClientResponseMode = "decoded-only" | "decoded-and-response" | "response-only";
/**
 * Computes the services required on the server to decode endpoint inputs and
 * encode endpoint success, error, and middleware error responses.
 *
 * @category models
 * @since 4.0.0
 */
export type ServerServices<Endpoint> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Params["DecodingServices"] | _Query["DecodingServices"] | _Payload["DecodingServices"] | _Headers["DecodingServices"] | _Success["EncodingServices"] | _Error["EncodingServices"] | HttpApiMiddleware.ErrorServicesEncode<_M> : never;
/**
 * Computes the services required on the client to encode endpoint requests and
 * decode endpoint success or error responses.
 *
 * @category models
 * @since 4.0.0
 */
export type ClientServices<Endpoint> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Params["EncodingServices"] | _Query["EncodingServices"] | _Payload["EncodingServices"] | _Headers["EncodingServices"] | _Success["DecodingServices"] | _Error["DecodingServices"] : never;
/**
 * Extracts the additional services required by middleware applied to an endpoint.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareServices<Endpoint> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _MR : never;
/**
 * Computes the services required to decode an endpoint's error responses,
 * including services required by middleware error decoders.
 *
 * @category models
 * @since 4.0.0
 */
export type ErrorServicesDecode<Endpoint> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? _Error["DecodingServices"] | HttpApiMiddleware.ErrorServicesDecode<Middleware<Endpoint>> : never;
/**
 * The normal server handler for an endpoint, accepting the decoded request shape
 * and returning either the endpoint success value or a custom `HttpServerResponse`.
 *
 * @category models
 * @since 4.0.0
 */
export type Handler<Endpoint extends Any, E, R> = (request: Types.Simplify<Request<Endpoint>>) => Effect<Endpoint["~Success"]["Type"] | HttpServerResponse, Endpoint["~Error"]["Type"] | E, R>;
/**
 * The raw server handler for an endpoint, receiving a request shape without a
 * decoded payload so the handler can read the raw `HttpServerRequest` directly.
 *
 * @category models
 * @since 4.0.0
 */
export type HandlerRaw<Endpoint extends Any, E, R> = (request: Types.Simplify<RequestRaw<Endpoint>>) => Effect<Endpoint["~Success"]["Type"] | HttpServerResponse, Endpoint["~Error"]["Type"] | E, R>;
/**
 * Selects the endpoint with the specified name from a union of endpoints.
 *
 * @category models
 * @since 4.0.0
 */
export type WithName<Endpoints extends Any, Name extends string> = Extract<Endpoints, {
    readonly name: Name;
}>;
/**
 * Removes endpoints with the specified name from a union of endpoints.
 *
 * @category models
 * @since 4.0.0
 */
export type ExcludeName<Endpoints extends Any, Name extends string> = Exclude<Endpoints, {
    readonly name: Name;
}>;
/**
 * Derives the normal handler type for the endpoint with the specified name in an
 * endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type HandlerWithName<Endpoints extends Any, Name extends string, E, R> = Handler<WithName<Endpoints, Name>, E, R>;
/**
 * Derives the raw handler type for the endpoint with the specified name in an
 * endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type HandlerRawWithName<Endpoints extends Any, Name extends string, E, R> = HandlerRaw<WithName<Endpoints, Name>, E, R>;
/**
 * Extracts the decoded success value type for the endpoint with the specified name
 * in an endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type SuccessWithName<Endpoints extends Any, Name extends string> = Success<WithName<Endpoints, Name>>["Type"];
/**
 * Computes the full error value union for the endpoint with the specified name in
 * an endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type ErrorsWithName<Endpoints extends Any, Name extends string> = Errors<WithName<Endpoints, Name>>;
/**
 * Computes the server-side service requirements for the endpoint with the
 * specified name in an endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type ServerServicesWithName<Endpoints extends Any, Name extends string> = ServerServices<WithName<Endpoints, Name>>;
/**
 * Extracts the middleware identifiers for the endpoint with the specified name in
 * an endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareWithName<Endpoints extends Any, Name extends string> = Middleware<WithName<Endpoints, Name>>;
/**
 * Extracts the middleware service requirements for the endpoint with the specified
 * name in an endpoint union.
 *
 * @category models
 * @since 4.0.0
 */
export type MiddlewareServicesWithName<Endpoints extends Any, Name extends string> = MiddlewareServices<WithName<Endpoints, Name>>;
/**
 * Removes services provided by the HTTP router and the named endpoint's middleware
 * from a service requirement union.
 *
 * @category models
 * @since 4.0.0
 */
export type ExcludeProvidedWithName<Endpoints extends Any, Name extends string, R> = ExcludeProvided<WithName<Endpoints, Name>, R>;
/**
 * Removes services provided by the HTTP router and endpoint middleware from a
 * service requirement union.
 *
 * @category models
 * @since 4.0.0
 */
export type ExcludeProvided<Endpoint extends Any, R> = Exclude<R, HttpRouter.Provided | HttpApiMiddleware.Provides<Middleware<Endpoint>>>;
/**
 * Returns an endpoint type with the supplied path prefix prepended while
 * preserving the endpoint's schemas, method, errors, and middleware.
 *
 * @category models
 * @since 4.0.0
 */
export type AddPrefix<Endpoint extends Any, Prefix extends HttpRouter.PathInput> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? HttpApiEndpoint<_Name, _Method, `${Prefix}${_Path}`, _Params, _Query, _Payload, _Headers, _Success, _Error, _M, _MR> : never;
/**
 * Returns an endpoint type with an additional error schema added to the endpoint's
 * existing error schema union.
 *
 * @category models
 * @since 4.0.0
 */
export type AddError<Endpoint extends Any, E extends Schema.Top> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? HttpApiEndpoint<_Name, _Method, _Path, _Params, _Query, _Payload, _Headers, _Success, _Error | E, _M, _MR> : never;
/**
 * Returns an endpoint type with additional middleware applied and the endpoint's
 * middleware service requirements updated accordingly.
 *
 * @category models
 * @since 4.0.0
 */
export type AddMiddleware<Endpoint extends Any, M extends HttpApiMiddleware.AnyId> = Endpoint extends HttpApiEndpoint<infer _Name, infer _Method, infer _Path, infer _Params, infer _Query, infer _Payload, infer _Headers, infer _Success, infer _Error, infer _M, infer _MR> ? HttpApiEndpoint<_Name, _Method, _Path, _Params, _Query, _Payload, _Headers, _Success, _Error, _M | M, HttpApiMiddleware.ApplyServices<M, _MR>> : never;
/**
 * Constraint for path parameter schemas: each parameter must encode to
 * `string | undefined`, or the schema must encode to a record of those values.
 *
 * @category constraints
 * @since 4.0.0
 */
export type ParamsConstraint = Record<string, Schema.Encoder<string | undefined, unknown>> | Schema.Encoder<Record<string, string | undefined>, unknown>;
/**
 * Constraint for header schemas: each header must encode to `string | undefined`,
 * or the schema must encode to a record of those values.
 *
 * @category constraints
 * @since 4.0.0
 */
export type HeadersConstraint = Record<string, Schema.Encoder<string | undefined, unknown>> | Schema.Encoder<Record<string, string | undefined>, unknown>;
/**
 * Constraint for query schemas: each field must encode to `string`, an array of
 * strings, or `undefined`, or the schema must encode to a record of those values.
 *
 * @category constraints
 * @since 4.0.0
 */
export type QueryConstraint = Record<string, Schema.Encoder<string | ReadonlyArray<string> | undefined, unknown>> | Schema.Encoder<Record<string, string | ReadonlyArray<string> | undefined>, unknown>;
/**
 * Payload schema depends on the HTTP method:
 * - for no-body methods, payload is modeled as query params, so each field must
 *   encode to `string | ReadonlyArray<string> | undefined` and OpenAPI can expand
 *   it into `in: query` parameters
 * - for body methods, payload may be any `Schema.Top` (or content-type keyed
 *   schemas) and OpenAPI uses `requestBody` instead of `parameters`
 *
 * @category constraints
 * @since 4.0.0
 */
export type PayloadConstraint<Method extends HttpMethod> = Method extends HttpMethod.NoBody ? Record<string, Schema.Encoder<string | ReadonlyArray<string> | undefined, unknown>> : SuccessConstraint;
/**
 * Payload constraint used when automatic codecs are enabled: no-body methods
 * accept field records for query-style encoding, while body methods accept one or
 * more schemas.
 *
 * @category constraints
 * @since 4.0.0
 */
export type PayloadConstraintCodecs<Method extends HttpMethod> = Method extends HttpMethod.NoBody ? Record<string, Schema.Top> : Schema.Top | ReadonlyArray<Schema.Top>;
/**
 * Constraint for success response schemas, allowing either a single schema or a
 * readonly array of schemas.
 *
 * @category constraints
 * @since 4.0.0
 */
export type SuccessConstraint = Schema.Top | ReadonlyArray<Schema.Top>;
/**
 * Constraint for error response schemas, allowing either a single schema or a
 * readonly array of schemas.
 *
 * @category constraints
 * @since 4.0.0
 */
export type ErrorConstraint = Schema.Top | ReadonlyArray<Schema.Top>;
/**
 * Creates endpoint constructors for a specific HTTP method. The resulting
 * constructor builds an `HttpApiEndpoint` from a name, path, and optional request
 * and response schemas, applying automatic JSON or string-tree codecs unless
 * `disableCodecs` is enabled.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: <Method extends HttpMethod>(method: Method) => {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends PayloadConstraintCodecs<Method> = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    }): HttpApiEndpoint<Name, Method, Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, Method extends HttpMethod.WithBody ? Json<ExtractSchemaOrArray<Payload>> : StringTree<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends ReadonlyArray<Schema.Top> ? Success[number] : Success>, Json<Error extends ReadonlyArray<Schema.Top> ? Error[number] : Error>>;
    <const Name extends string, const Path_1 extends HttpRouter.PathInput, Params_1 extends ParamsConstraint = never, Query_1 extends QueryConstraint = never, Payload_1 extends PayloadConstraint<Method> = never, Headers_1 extends HeadersConstraint = never, const Success_1 extends SuccessConstraint = HttpApiSchema.NoContent, const Error_1 extends ErrorConstraint = never>(name: Name, path: Path_1, options?: {
        readonly disableCodecs: true;
        readonly params?: Params_1 | undefined;
        readonly query?: Query_1 | undefined;
        readonly headers?: Headers_1 | undefined;
        readonly payload?: Payload_1 | undefined;
        readonly success?: Success_1 | undefined;
        readonly error?: Error_1 | undefined;
    }): HttpApiEndpoint<Name, Method, Path_1, Params_1 extends Schema.Struct.Fields ? Schema.Struct<Params_1> : Params_1, Query_1 extends Schema.Struct.Fields ? Schema.Struct<Query_1> : Query_1, ExtractSchemaOrArray<Payload_1>, ExtractSchemaOrArray<Headers_1>, Success_1 extends ReadonlyArray<Schema.Top> ? Success_1[number] : Success_1, Error_1 extends ReadonlyArray<Schema.Top> ? Error_1[number] : Error_1>;
};
type ExtractSchemaOrArray<S extends Schema.Struct.Fields | Schema.Top | ReadonlyArray<Schema.Top>> = S extends Schema.Struct.Fields ? Schema.Struct<S> : S extends ReadonlyArray<Schema.Top> ? S[number] : S;
/**
 * A schema codec that decodes and encodes the schema's value type through JSON
 * transport values.
 *
 * @category Codecs
 * @since 4.0.0
 */
export interface Json<S extends Schema.Top> extends Schema.Codec<S["Type"], Schema.Json, S["DecodingServices"], S["EncodingServices"]> {
}
/**
 * A schema codec that decodes and encodes the schema's value type through
 * `Schema.StringTree` transport values.
 *
 * @category Codecs
 * @since 4.0.0
 */
export interface StringTree<S extends Schema.Top> extends Schema.Codec<S["Type"], Schema.StringTree, S["DecodingServices"], S["EncodingServices"]> {
}
/**
 * Creates a `GET` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const get: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Record<string, Schema.Top> = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "GET", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, StringTree<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends Record<string, Schema.Encoder<string | readonly string[] | undefined, unknown>> = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "GET", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
/**
 * Creates a `POST` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const post: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Schema.Top | readonly Schema.Top[] = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "POST", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, Json<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends SuccessConstraint = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "POST", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
/**
 * Creates a `PUT` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const put: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Schema.Top | readonly Schema.Top[] = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "PUT", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, Json<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends SuccessConstraint = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "PUT", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
/**
 * Creates a `PATCH` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const patch: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Schema.Top | readonly Schema.Top[] = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "PATCH", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, Json<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends SuccessConstraint = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "PATCH", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
declare const del: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Schema.Top | readonly Schema.Top[] = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "DELETE", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, Json<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends SuccessConstraint = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "DELETE", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
export { 
/**
 * Creates a `DELETE` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
del as delete };
/**
 * Creates a `HEAD` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const head: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Record<string, Schema.Top> = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "HEAD", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, StringTree<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends Record<string, Schema.Encoder<string | readonly string[] | undefined, unknown>> = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "HEAD", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
/**
 * Creates an `OPTIONS` endpoint declaration.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const options: {
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends Schema.Top | Schema.Struct.Fields = never, Query extends Schema.Top | Schema.Struct.Fields = never, Payload extends Record<string, Schema.Top> = never, Headers extends Schema.Top | Schema.Struct.Fields = never, const Success extends Schema.Top | ReadonlyArray<Schema.Top> = HttpApiSchema.NoContent, const Error extends Schema.Top | ReadonlyArray<Schema.Top> = never>(name: Name, path: Path, options?: {
        readonly disableCodecs?: false | undefined;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "OPTIONS", Path, StringTree<Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params>, StringTree<Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query>, StringTree<ExtractSchemaOrArray<Payload>>, StringTree<Headers extends Schema.Struct.Fields ? Schema.Struct<Headers> : Headers>, Json<Success extends readonly Schema.Top[] ? Success[number] : Success>, Json<Error extends readonly Schema.Top[] ? Error[number] : Error>, never, never>;
    <const Name extends string, const Path extends HttpRouter.PathInput, Params extends ParamsConstraint = never, Query extends QueryConstraint = never, Payload extends Record<string, Schema.Encoder<string | readonly string[] | undefined, unknown>> = never, Headers extends HeadersConstraint = never, const Success extends SuccessConstraint = HttpApiSchema.NoContent, const Error extends ErrorConstraint = never>(name: Name, path: Path, options?: {
        readonly disableCodecs: true;
        readonly params?: Params | undefined;
        readonly query?: Query | undefined;
        readonly headers?: Headers | undefined;
        readonly payload?: Payload | undefined;
        readonly success?: Success | undefined;
        readonly error?: Error | undefined;
    } | undefined): HttpApiEndpoint<Name, "OPTIONS", Path, Params extends Schema.Struct.Fields ? Schema.Struct<Params> : Params, Query extends Schema.Struct.Fields ? Schema.Struct<Query> : Query, ExtractSchemaOrArray<Payload>, ExtractSchemaOrArray<Headers>, Success extends readonly Schema.Top[] ? Success[number] : Success, Error extends readonly Schema.Top[] ? Error[number] : Error, never, never>;
};
//# sourceMappingURL=HttpApiEndpoint.d.ts.map