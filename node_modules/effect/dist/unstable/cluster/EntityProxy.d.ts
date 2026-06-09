/**
 * The `EntityProxy` module derives external RPC and HTTP API surfaces from a
 * clustered {@link Entity.Entity}. It is used when callers should communicate
 * with entities through ordinary RPC clients or HTTP routes while the cluster
 * runtime keeps responsibility for locating, routing, and delivering messages
 * to the entity instance identified by `entityId`.
 *
 * **Common tasks**
 *
 * - Derive an `RpcGroup` from an entity with {@link toRpcGroup}
 * - Derive an `HttpApiGroup` from an entity with {@link toHttpApiGroup}
 * - Expose both request/response calls and discard variants for fire-and-forget
 *   delivery
 *
 * **Gotchas**
 *
 * - Proxy RPC payloads wrap the original RPC payload with an `entityId`; HTTP
 *   endpoints place the same identifier in the route path.
 * - Generated RPC names are prefixed with the entity type, while HTTP endpoint
 *   paths are based on lower-cased RPC tags.
 * - Proxy errors include cluster delivery errors such as mailbox saturation,
 *   duplicate in-flight messages, and persistence failures.
 *
 * @since 4.0.0
 */
import * as Schema from "../../Schema.ts";
import * as HttpApiEndpoint from "../httpapi/HttpApiEndpoint.ts";
import * as HttpApiGroup from "../httpapi/HttpApiGroup.ts";
import * as Rpc from "../rpc/Rpc.ts";
import * as RpcGroup from "../rpc/RpcGroup.ts";
import { AlreadyProcessingMessage, MailboxFull, PersistenceError } from "./ClusterError.ts";
import type * as Entity from "./Entity.ts";
import type { EntityId } from "./EntityId.ts";
/**
 * Derives an `RpcGroup` from an `Entity`.
 *
 * **Example** (Deriving RPC endpoints from an entity)
 *
 * ```ts
 * import { Layer, Schema } from "effect"
 * import { ClusterSchema, Entity, EntityProxy, EntityProxyServer } from "effect/unstable/cluster"
 * import { Rpc, RpcServer } from "effect/unstable/rpc"
 *
 * export const Counter = Entity.make("Counter", [
 *   Rpc.make("Increment", {
 *     payload: { id: Schema.String, amount: Schema.Number },
 *     primaryKey: ({ id }) => id,
 *     success: Schema.Number
 *   })
 * ]).annotateRpcs(ClusterSchema.Persisted, true)
 *
 * // Use EntityProxy.toRpcGroup to create a `RpcGroup` from the Counter entity
 * export class MyRpcs extends EntityProxy.toRpcGroup(Counter) {}
 *
 * // Use EntityProxyServer.layerRpcHandlers to create a layer that implements
 * // the rpc handlers
 * const RpcServerLayer = RpcServer.layer(MyRpcs).pipe(
 *   Layer.provide(EntityProxyServer.layerRpcHandlers(Counter))
 * )
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const toRpcGroup: <Type extends string, Rpcs extends Rpc.Any>(entity: Entity.Entity<Type, Rpcs>) => RpcGroup.RpcGroup<ConvertRpcs<Rpcs, Type>>;
/**
 * Type-level conversion used by `toRpcGroup`.
 *
 * **Details**
 *
 * For each entity RPC, this creates a prefixed request RPC and a discard RPC
 * whose payload includes `entityId`, and whose errors include cluster client
 * errors.
 *
 * @category converting
 * @since 4.0.0
 */
export type ConvertRpcs<Rpcs extends Rpc.Any, Prefix extends string> = Rpcs extends Rpc.Rpc<infer _Tag, infer _Payload, infer _Success, infer _Error, infer _Middleware, infer _Requires> ? Rpc.Rpc<`${Prefix}.${_Tag}`, Schema.Struct<{
    entityId: typeof Schema.String;
    payload: _Payload;
}>, _Success, Schema.Codec<_Error["Type"] | MailboxFull | AlreadyProcessingMessage | PersistenceError, _Error["Encoded"] | typeof MailboxFull["Encoded"] | typeof AlreadyProcessingMessage["Encoded"] | typeof PersistenceError["Encoded"], _Error["DecodingServices"], _Error["EncodingServices"]>> | Rpc.Rpc<`${Prefix}.${_Tag}Discard`, Schema.Struct<{
    entityId: typeof Schema.String;
    payload: _Payload;
}>, typeof Schema.Void, Schema.Union<[
    typeof MailboxFull,
    typeof AlreadyProcessingMessage,
    typeof PersistenceError
]>> : never;
/**
 * Derives an `HttpApiGroup` from an `Entity`.
 *
 * **Example** (Deriving HTTP API endpoints from an entity)
 *
 * ```ts
 * import { Layer, Schema } from "effect"
 * import { ClusterSchema, Entity, EntityProxy, EntityProxyServer } from "effect/unstable/cluster"
 * import { HttpApi, HttpApiBuilder } from "effect/unstable/httpapi"
 * import { Rpc } from "effect/unstable/rpc"
 *
 * export const Counter = Entity.make("Counter", [
 *   Rpc.make("Increment", {
 *     payload: { id: Schema.String, amount: Schema.Number },
 *     primaryKey: ({ id }) => id,
 *     success: Schema.Number
 *   })
 * ]).annotateRpcs(ClusterSchema.Persisted, true)
 *
 * // Use EntityProxy.toHttpApiGroup to create a `HttpApiGroup` from the
 * // Counter entity
 * export class MyApi extends HttpApi.make("api")
 *   .add(
 *     EntityProxy.toHttpApiGroup("counter", Counter)
 *       .prefix("/counter")
 *   )
 * {}
 *
 * // Use EntityProxyServer.layerHttpApi to create a layer that implements
 * // the handlers for the HttpApiGroup
 * const ApiLayer = HttpApiBuilder.layer(MyApi).pipe(
 *   Layer.provide(EntityProxyServer.layerHttpApi(MyApi, "counter", Counter))
 * )
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const toHttpApiGroup: <const Name extends string, Type extends string, Rpcs extends Rpc.Any>(name: Name, entity: Entity.Entity<Type, Rpcs>) => HttpApiGroup.HttpApiGroup<Name, ConvertHttpApi<Rpcs>>;
/**
 * Type-level conversion used by `toHttpApiGroup`.
 *
 * **Details**
 *
 * For each entity RPC, this creates a POST endpoint at `/<tag>/:entityId` and a
 * discard endpoint at `/<tag>/:entityId/discard`, including cluster client
 * errors.
 *
 * @category converting
 * @since 4.0.0
 */
export type ConvertHttpApi<Rpcs extends Rpc.Any> = Rpcs extends Rpc.Rpc<infer _Tag, infer _Payload, infer _Success, infer _Error, infer _Middleware, infer _Requires> ? HttpApiEndpoint.HttpApiEndpoint<_Tag, "POST", `/${Lowercase<_Tag>}/:entityId`, Schema.Struct<{
    entityId: typeof EntityId;
}>, never, _Payload, never, _Success, _Error | typeof MailboxFull | typeof AlreadyProcessingMessage | typeof PersistenceError> | HttpApiEndpoint.HttpApiEndpoint<`${_Tag}Discard`, "POST", `/${Lowercase<_Tag>}/:entityId/discard`, Schema.Struct<{
    entityId: typeof EntityId;
}>, never, _Payload, never, Schema.Void, typeof MailboxFull | typeof AlreadyProcessingMessage | typeof PersistenceError> : never;
//# sourceMappingURL=EntityProxy.d.ts.map