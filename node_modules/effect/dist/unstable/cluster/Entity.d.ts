import type * as Cause from "../../Cause.ts";
import * as Context from "../../Context.ts";
import * as Data from "../../Data.ts";
import type * as Duration from "../../Duration.ts";
import * as Effect from "../../Effect.ts";
import * as Equal from "../../Equal.ts";
import * as Exit from "../../Exit.ts";
import type * as Latch from "../../Latch.ts";
import * as Layer from "../../Layer.ts";
import * as Option from "../../Option.ts";
import * as Queue from "../../Queue.ts";
import type * as Schedule from "../../Schedule.ts";
import { Scope } from "../../Scope.ts";
import * as Stream from "../../Stream.ts";
import * as Rpc from "../rpc/Rpc.ts";
import * as RpcClient from "../rpc/RpcClient.ts";
import * as RpcGroup from "../rpc/RpcGroup.ts";
import type { AlreadyProcessingMessage, MailboxFull, PersistenceError } from "./ClusterError.ts";
import { EntityAddress } from "./EntityAddress.ts";
import type { EntityId } from "./EntityId.ts";
import { EntityType } from "./EntityType.ts";
import * as Envelope from "./Envelope.ts";
import type * as Reply from "./Reply.ts";
import { RunnerAddress } from "./RunnerAddress.ts";
import * as ShardId from "./ShardId.ts";
import type { Sharding } from "./Sharding.ts";
import { ShardingConfig } from "./ShardingConfig.ts";
declare const TypeId = "~effect/cluster/Entity";
/**
 * Represents a cluster entity type and the RPC protocol it can handle.
 *
 * **Details**
 *
 * An entity defines how ids map to shard groups, exposes a sharded client, and
 * can be registered as a layer using RPC handlers or a mailbox queue.
 *
 * @category models
 * @since 4.0.0
 */
export interface Entity<in out Type extends string, in out Rpcs extends Rpc.Any> extends Equal.Equal {
    readonly [TypeId]: typeof TypeId;
    /**
     * The name of the entity type.
     */
    readonly type: EntityType;
    /**
     * A RpcGroup definition for messages which represents the messaging protocol
     * that the entity is capable of processing.
     */
    readonly protocol: RpcGroup.RpcGroup<Rpcs>;
    /**
     * Get the shard group for the given EntityId.
     */
    getShardGroup(entityId: EntityId): string;
    /**
     * Get the ShardId for the given EntityId.
     */
    getShardId(entityId: EntityId): Effect.Effect<ShardId.ShardId, never, Sharding>;
    /**
     * Annotate the entity with a value.
     */
    annotate<I, S>(key: Context.Key<I, S>, value: S): Entity<Type, Rpcs>;
    /**
     * Annotate the Rpc's above this point with a value.
     */
    annotateRpcs<I, S>(key: Context.Key<I, S>, value: S): Entity<Type, Rpcs>;
    /**
     * Annotate the entity with the given annotations.
     */
    annotateMerge<S>(annotation: Context.Context<S>): Entity<Type, Rpcs>;
    /**
     * Annotate the Rpc's above this point with a context object.
     */
    annotateRpcsMerge<S>(context: Context.Context<S>): Entity<Type, Rpcs>;
    /**
     * Create a client for this entity.
     */
    readonly client: Effect.Effect<(entityId: string) => RpcClient.RpcClient.From<Rpcs, MailboxFull | AlreadyProcessingMessage | PersistenceError>, never, Sharding>;
    /**
     * Create a Layer from an Entity.
     *
     * **Details**
     *
     * It will register the entity with the Sharding service.
     */
    toLayer<Handlers extends HandlersFrom<Rpcs>, RX = never>(build: Handlers | Effect.Effect<Handlers, never, RX>, options?: {
        readonly maxIdleTime?: Duration.Input | undefined;
        readonly concurrency?: number | "unbounded" | undefined;
        readonly mailboxCapacity?: number | "unbounded" | undefined;
        readonly disableFatalDefects?: boolean | undefined;
        readonly defectRetryPolicy?: Schedule.Schedule<any, unknown> | undefined;
        readonly spanAttributes?: Record<string, string> | undefined;
    }): Layer.Layer<never, never, Exclude<RX, Scope | CurrentAddress | CurrentRunnerAddress> | RpcGroup.HandlersServices<Rpcs, Handlers> | Rpc.ServicesClient<Rpcs> | Rpc.ServicesServer<Rpcs> | Rpc.Middleware<Rpcs> | Sharding>;
    of<Handlers extends HandlersFrom<Rpcs>>(handlers: Handlers): Handlers;
    /**
     * Create a Layer from an Entity.
     *
     * **Details**
     *
     * It will register the entity with the Sharding service.
     */
    toLayerQueue<R, RX = never>(build: ((queue: Queue.Dequeue<Envelope.Request<Rpcs>>, replier: Replier<Rpcs>) => Effect.Effect<never, never, R>) | Effect.Effect<(queue: Queue.Dequeue<Envelope.Request<Rpcs>>, replier: Replier<Rpcs>) => Effect.Effect<never, never, R>, never, RX>, options?: {
        readonly maxIdleTime?: Duration.Input | undefined;
        readonly mailboxCapacity?: number | "unbounded" | undefined;
        readonly disableFatalDefects?: boolean | undefined;
        readonly defectRetryPolicy?: Schedule.Schedule<any, unknown> | undefined;
        readonly spanAttributes?: Record<string, string> | undefined;
    }): Layer.Layer<never, never, Exclude<RX, Scope | CurrentAddress | CurrentRunnerAddress> | R | Rpc.ServicesClient<Rpcs> | Rpc.ServicesServer<Rpcs> | Rpc.Middleware<Rpcs> | Sharding>;
}
/**
 * Type alias for any cluster `Entity`, regardless of entity type or RPC
 * protocol.
 *
 * @category models
 * @since 4.0.0
 */
export type Any = Entity<string, Rpc.Any>;
/**
 * Maps each RPC in an entity protocol to the handler function expected by
 * `Entity.toLayer`.
 *
 * **Details**
 *
 * Each handler receives the entity request envelope for that RPC and returns the
 * RPC result or a supported RPC wrapper.
 *
 * @category models
 * @since 4.0.0
 */
export type HandlersFrom<Rpc extends Rpc.Any> = {
    readonly [Current in Rpc as Current["_tag"]]: (envelope: Request<Current>) => Rpc.WrapperOr<Rpc.ResultFrom<Current, any>>;
};
/**
 * Returns `true` when the supplied value is a cluster `Entity`.
 *
 * **Details**
 *
 * The check is based on the internal entity type identifier.
 *
 * @category refinements
 * @since 4.0.0
 */
export declare const isEntity: (u: unknown) => u is Any;
/**
 * Creates a new `Entity` of the specified `type` which will accept messages
 * that adhere to the provided `RpcGroup`.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const fromRpcGroup: <const Type extends string, Rpcs extends Rpc.Any>(
/**
 * The entity type name.
 */
type: Type, 
/**
 * The schema definition for messages that the entity is capable of
 * processing.
 */
protocol: RpcGroup.RpcGroup<Rpcs>) => Entity<Type, Rpcs>;
/**
 * Creates a new `Entity` of the specified `type` which will accept messages
 * that adhere to the provided schemas.
 *
 * **When to use**
 *
 * Use to define a cluster entity from individual `Rpc` definitions, giving the
 * cluster runtime a typed protocol for handlers and per-entity clients.
 *
 * **Details**
 *
 * The `type` argument is stored as the entity `EntityType`, and the RPC array
 * is grouped into the entity's `protocol`.
 *
 * **Gotchas**
 *
 * RPC tags should be unique within the array. If multiple definitions use the
 * same tag, the resulting protocol keeps the later definition for that tag.
 *
 * @see {@link fromRpcGroup} for creating an entity from an existing `RpcGroup`
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: <const Type extends string, Rpcs extends ReadonlyArray<Rpc.Any>>(
/**
 * The entity type name.
 */
type: Type, 
/**
 * The schema definition for messages that the entity is capable of
 * processing.
 */
protocol: Rpcs) => Entity<Type, Rpcs[number]>;
declare const CurrentAddress_base: Context.ServiceClass<CurrentAddress, "effect/cluster/Entity/EntityAddress", EntityAddress>;
/**
 * Service tag for the entity address currently being processed.
 *
 * **When to use**
 *
 * Use to read the current entity identity and shard address from entity
 * handlers and keep-alive logic.
 *
 * @category context
 * @since 4.0.0
 */
export declare class CurrentAddress extends CurrentAddress_base {
}
declare const CurrentRunnerAddress_base: Context.ServiceClass<CurrentRunnerAddress, "effect/cluster/Entity/RunnerAddress", RunnerAddress>;
/**
 * Service tag for the runner address currently registering entity handlers.
 *
 * **When to use**
 *
 * Use to read the runner address associated with the current entity handler
 * registration.
 *
 * @category context
 * @since 4.0.0
 */
export declare class CurrentRunnerAddress extends CurrentRunnerAddress_base {
}
/**
 * Reply API passed to queue-based entity handlers.
 *
 * **When to use**
 *
 * Use when you use it to complete an entity request by succeeding, failing, failing with a
 * cause, or supplying an explicit `Exit`.
 *
 * @category Replier
 * @since 4.0.0
 */
export interface Replier<Rpcs extends Rpc.Any> {
    readonly succeed: <R extends Rpcs>(request: Envelope.Request<R>, value: Replier.Success<R>) => Effect.Effect<void>;
    readonly fail: <R extends Rpcs>(request: Envelope.Request<R>, error: Rpc.Error<R>) => Effect.Effect<void>;
    readonly failCause: <R extends Rpcs>(request: Envelope.Request<R>, cause: Cause.Cause<Rpc.Error<R>>) => Effect.Effect<void>;
    readonly complete: <R extends Rpcs>(request: Envelope.Request<R>, exit: Exit.Exit<Replier.Success<R>, Rpc.Error<R>>) => Effect.Effect<void>;
}
/**
 * Helper types used by the `Replier` API.
 *
 * @since 4.0.0
 */
export declare namespace Replier {
    /**
     * Success value accepted by a `Replier` for a single RPC.
     *
     * **Details**
     *
     * For streaming RPCs this may be either a stream of success chunks or a dequeue
     * of success chunks. For non-streaming RPCs it is the RPC success value.
     *
     * @category Replier
     * @since 4.0.0
     */
    type Success<R extends Rpc.Any> = Rpc.Success<R> extends Stream.Stream<infer _A, infer _E, infer _R> ? Stream.Stream<_A, _E | Rpc.Error<R>, _R> | Queue.Dequeue<_A, _E | Rpc.Error<R> | Cause.Done> : Rpc.Success<R>;
}
/**
 * Represents an entity request envelope delivered to entity handlers.
 *
 * **Details**
 *
 * It includes the underlying request envelope plus the last stream reply chunk
 * that was sent, allowing handlers to resume chunk sequencing after a restart.
 *
 * @category request
 * @since 4.0.0
 */
export declare class Request<Rpc extends Rpc.Any> extends Data.Class<Envelope.Request<Rpc> & {
    readonly lastSentChunk: Option.Option<Reply.Chunk<Rpc>>;
}> {
    /**
     * Most recent success chunk value sent by the entity, when one exists.
     *
     * @since 4.0.0
     */
    get lastSentChunkValue(): Option.Option<Rpc.SuccessChunk<Rpc>>;
    /**
     * Sequence number to use for the entity's next outgoing success chunk.
     *
     * @since 4.0.0
     */
    get nextSequence(): number;
}
/**
 * Builds an in-memory test client for an entity layer.
 *
 * **Details**
 *
 * The returned function creates a no-serialization RPC client for each entity ID,
 * using a test sharding service instead of the cluster transport.
 *
 * @category testing
 * @since 4.0.0
 */
export declare const makeTestClient: <Type extends string, Rpcs extends Rpc.Any, LA, LE, LR>(entity: Entity<Type, Rpcs>, layer: Layer.Layer<LA, LE, LR>) => Effect.Effect<(entityId: string) => Effect.Effect<RpcClient.RpcClient<Rpcs>>, LE, Scope | ShardingConfig | Exclude<LR, Sharding> | Rpc.MiddlewareClient<Rpcs>>;
/**
 * Enables or disables keep-alive for the current entity.
 *
 * **Details**
 *
 * When enabled it sends the internal keep-alive RPC for the current address; when
 * disabled it releases the keep-alive latch if one is present.
 *
 * @category Keep alive
 * @since 4.0.0
 */
export declare const keepAlive: (enabled: boolean) => Effect.Effect<void, never, Sharding | CurrentAddress>;
/**
 * RPC used internally to keep an entity active while a resource is held.
 *
 * **Details**
 *
 * The RPC is marked as persisted and uninterruptible so the keep-alive signal
 * survives normal entity restarts.
 *
 * @category Keep alive
 * @since 4.0.0
 */
export declare const KeepAliveRpc: Rpc.Rpc<"Cluster/Entity/keepAlive", import("../../Schema.ts").Void, import("../../Schema.ts").Void, import("../../Schema.ts").Never, never, never>;
declare const KeepAliveLatch_base: Context.ServiceClass<KeepAliveLatch, "effect/cluster/Entity/KeepAliveLatch", Latch.Latch>;
/**
 * Service tag for the latch that coordinates entity keep-alive state.
 *
 * **Details**
 *
 * `keepAlive` closes the latch when keep-alive is active and opens it again when
 * the resource no longer needs to keep the entity alive.
 *
 * @category Keep alive
 * @since 4.0.0
 */
export declare class KeepAliveLatch extends KeepAliveLatch_base {
}
export {};
//# sourceMappingURL=Entity.d.ts.map