import * as Context from "../../Context.ts";
import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import type * as Scope from "../../Scope.ts";
import * as Tracer from "../../Tracer.ts";
import * as Socket from "../socket/Socket.ts";
import * as DevToolsSchema from "./DevToolsSchema.ts";
declare const DevToolsClient_base: Context.ServiceClass<DevToolsClient, "effect/devtools/DevToolsClient", {
    readonly sendUnsafe: (_: DevToolsSchema.Span | DevToolsSchema.SpanEvent) => void;
}>;
/**
 * Service for sending span and span-event telemetry to the Effect devtools
 * connection.
 *
 * @category services
 * @since 4.0.0
 */
export declare class DevToolsClient extends DevToolsClient_base {
}
/**
 * Creates a devtools client over the current `Socket`, speaking the devtools
 * NDJSON protocol, sending periodic pings, and responding to metrics snapshot
 * requests.
 *
 * **When to use**
 *
 * Use when you already have a `Socket` and need the low-level `DevToolsClient`
 * service to exchange devtools telemetry directly.
 *
 * **Details**
 *
 * The effect requires `Scope` because it starts background fibers for the socket
 * stream and heartbeat.
 *
 * **Gotchas**
 *
 * `make` creates only the client service; tracing is installed separately.
 *
 * @see {@link layer} for providing the client as a layer
 * @see {@link makeTracer} for creating a tracer after a `DevToolsClient` is available
 * @see {@link layerTracer} for creating the client from the current `Socket` and installing the tracer as a layer
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: Effect.Effect<DevToolsClient["Service"], never, Scope.Scope | Socket.Socket>;
/**
 * Layer that provides `DevToolsClient` using the current `Socket`.
 *
 * **When to use**
 *
 * Use to provide the low-level `DevToolsClient` service over an existing
 * `Socket` for custom devtools integrations that send telemetry through the
 * client directly.
 *
 * **Details**
 *
 * It delegates to `make`, so it speaks the devtools NDJSON protocol over the
 * provided `Socket`, sends periodic pings, responds to metrics snapshot
 * requests, and finalizes its background fibers when the layer scope closes.
 *
 * **Gotchas**
 *
 * This layer only provides the client. It does not install the devtools tracer
 * by itself.
 *
 * @see {@link make} for constructing the client as a scoped effect instead of a layer
 * @see {@link layerTracer} for a higher-level layer that creates the client and installs the devtools tracer
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: Layer.Layer<DevToolsClient, never, Socket.Socket>;
/**
 * Creates a tracer that delegates to the current tracer while sending span
 * starts, span events, and span ends to `DevToolsClient`.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const makeTracer: Effect.Effect<Tracer.Tracer, never, DevToolsClient>;
/**
 * Layer that creates a `DevToolsClient` from the current `Socket` and installs
 * the devtools tracer.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerTracer: Layer.Layer<never, never, Socket.Socket>;
export {};
//# sourceMappingURL=DevToolsClient.d.ts.map