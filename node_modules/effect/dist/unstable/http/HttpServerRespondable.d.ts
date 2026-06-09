import * as Effect from "../../Effect.ts";
import type { HttpServerResponse } from "./HttpServerResponse.ts";
/**
 * Protocol key used by values that can render themselves as
 * `HttpServerResponse` values.
 *
 * @category type IDs
 * @since 4.0.0
 */
export declare const symbol = "~effect/http/HttpServerRespondable";
/**
 * Protocol for values that can be converted into an `HttpServerResponse`.
 *
 * **Details**
 *
 * Implement the protocol method to describe the response that should be sent for
 * the value.
 *
 * @category models
 * @since 4.0.0
 */
export interface Respondable {
    [symbol](): Effect.Effect<HttpServerResponse, unknown>;
}
/**
 * Returns `true` when the supplied value implements the `Respondable` protocol.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isRespondable: (u: unknown) => u is Respondable;
/**
 * Converts a `Respondable` value into an `HttpServerResponse`.
 *
 * **Details**
 *
 * If the value is already an HTTP server response it is returned directly; errors
 * from the response conversion are converted to defects.
 *
 * @category accessors
 * @since 4.0.0
 */
export declare const toResponse: (self: Respondable) => Effect.Effect<HttpServerResponse>;
/**
 * Attempts to convert an unknown value into an `HttpServerResponse`, falling back
 * to the supplied response when no conversion is available.
 *
 * **Details**
 *
 * `HttpServerResponse` and `Respondable` values are used directly, schema errors
 * become `400` responses, and no-such-element errors become `404` responses.
 *
 * @category accessors
 * @since 4.0.0
 */
export declare const toResponseOrElse: (u: unknown, orElse: HttpServerResponse) => Effect.Effect<HttpServerResponse>;
/**
 * Attempts to convert an unknown defect into an `HttpServerResponse`, falling
 * back to the supplied response when no conversion is available.
 *
 * **Details**
 *
 * Only `HttpServerResponse` and `Respondable` values receive special handling.
 *
 * @category accessors
 * @since 4.0.0
 */
export declare const toResponseOrElseDefect: (u: unknown, orElse: HttpServerResponse) => Effect.Effect<HttpServerResponse>;
//# sourceMappingURL=HttpServerRespondable.d.ts.map