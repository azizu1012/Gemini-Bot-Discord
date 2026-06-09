/**
 * Durable storage for encoded `Persistable` request results.
 *
 * The `Persistence` service creates scoped stores that read and write
 * schema-encoded `Exit` values keyed by each request's `PrimaryKey`. It is the
 * lower-level persistence layer used by `PersistedCache` and similar request
 * workflows to reuse expensive or idempotent lookup results across fibers,
 * process restarts, and workers that share a backing store.
 *
 * Each store is selected by a `storeId`, while each entry id comes from the
 * request's primary key. Keep both stable and collision-free: changing the
 * `storeId`, the primary-key format, or the success/error schemas is a
 * persistence migration, because old entries may stop being found or fail to
 * decode. Values are encoded with the request's success and error schemas using
 * the JSON codec, so any required schema services must be available at store
 * read and write time, and the backing value must stay JSON-compatible.
 *
 * TTLs are computed from the stored `Exit` and request key. Infinite TTLs are
 * stored without an expiration, finite TTLs become backing-store expirations,
 * and zero or negative TTLs skip the write entirely. Backing layers provide
 * process-local memory, `KeyValueStore`, Redis, and SQL implementations; store
 * ids are used as prefixes, table names, or SQL partitions and should be
 * chosen with the target backing store in mind.
 *
 * @since 4.0.0
 */
import * as Arr from "../../Array.ts";
import * as Clock from "../../Clock.ts";
import * as Context from "../../Context.ts";
import * as Duration from "../../Duration.ts";
import * as Effect from "../../Effect.ts";
import * as Exit from "../../Exit.ts";
import * as Layer from "../../Layer.ts";
import * as Schema from "../../Schema.ts";
import type * as Scope from "../../Scope.ts";
import * as SqlClient from "../sql/SqlClient.ts";
import * as KeyValueStore from "./KeyValueStore.ts";
import * as Persistable from "./Persistable.ts";
import * as Redis from "./Redis.ts";
declare const ErrorTypeId: "~effect/persistence/Persistence/PersistenceError";
declare const PersistenceError_base: Schema.Class<PersistenceError, Schema.Struct<{
    readonly _tag: Schema.tag<"PersistenceError">;
    readonly message: Schema.String;
    readonly cause: Schema.optional<Schema.Defect>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Error raised by persistence and backing-store operations.
 *
 * @category errors
 * @since 4.0.0
 */
export declare class PersistenceError extends PersistenceError_base {
    /**
     * Marks this value as a persistence error for runtime guards.
     *
     * @since 4.0.0
     */
    readonly [ErrorTypeId]: typeof ErrorTypeId;
}
declare const Persistence_base: Context.ServiceClass<Persistence, "effect/persistence/Persistence", {
    readonly make: (options: {
        readonly storeId: string;
        readonly timeToLive?: (exit: Exit.Exit<unknown, unknown>, key: Persistable.Any) => Duration.Input;
    }) => Effect.Effect<PersistenceStore, never, Scope.Scope>;
}>;
/**
 * Service for creating scoped stores of persisted `Persistable` request
 * results.
 *
 * @category models
 * @since 4.0.0
 */
export declare class Persistence extends Persistence_base {
}
/**
 * Typed store for persisted `Exit` values keyed by `Persistable` requests.
 *
 * @category models
 * @since 4.0.0
 */
export interface PersistenceStore {
    readonly get: <A extends Schema.Top, E extends Schema.Top>(key: Persistable.Persistable<A, E>) => Effect.Effect<Exit.Exit<A["Type"], E["Type"]> | undefined, PersistenceError | Schema.SchemaError, A["DecodingServices"] | E["DecodingServices"]>;
    readonly getMany: <A extends Schema.Top, E extends Schema.Top>(keys: Iterable<Persistable.Persistable<A, E>>) => Effect.Effect<Array<Exit.Exit<A["Type"], E["Type"]> | undefined>, PersistenceError | Schema.SchemaError, A["DecodingServices"] | E["DecodingServices"]>;
    readonly set: <A extends Schema.Top, E extends Schema.Top>(key: Persistable.Persistable<A, E>, value: Exit.Exit<A["Type"], E["Type"]>) => Effect.Effect<void, PersistenceError | Schema.SchemaError, A["EncodingServices"] | E["EncodingServices"]>;
    readonly setMany: <A extends Schema.Top, E extends Schema.Top>(entries: Iterable<readonly [Persistable.Persistable<A, E>, Exit.Exit<A["Type"], E["Type"]>]>) => Effect.Effect<void, PersistenceError | Schema.SchemaError, A["EncodingServices"] | E["EncodingServices"]>;
    readonly remove: <A extends Schema.Top, E extends Schema.Top>(key: Persistable.Persistable<A, E>) => Effect.Effect<void, PersistenceError>;
    readonly clear: Effect.Effect<void, PersistenceError>;
}
declare const BackingPersistence_base: Context.ServiceClass<BackingPersistence, "effect/persistence/BackingPersistence", {
    readonly make: (storeId: string) => Effect.Effect<BackingPersistenceStore, never, Scope.Scope>;
}>;
/**
 * Service for creating raw backing stores for persistence store ids.
 *
 * @category BackingPersistence
 * @since 4.0.0
 */
export declare class BackingPersistence extends BackingPersistence_base {
}
/**
 * Raw persistence backing store for JSON-compatible objects with optional
 * TTLs.
 *
 * @category BackingPersistence
 * @since 4.0.0
 */
export interface BackingPersistenceStore {
    readonly get: (key: string) => Effect.Effect<object | undefined, PersistenceError>;
    readonly getMany: (keys: Arr.NonEmptyArray<string>) => Effect.Effect<Arr.NonEmptyArray<object | undefined>, PersistenceError>;
    readonly set: (key: string, value: object, ttl: Duration.Duration | undefined) => Effect.Effect<void, PersistenceError>;
    readonly setMany: (entries: Arr.NonEmptyArray<readonly [key: string, value: object, ttl: Duration.Duration | undefined]>) => Effect.Effect<void, PersistenceError>;
    readonly remove: (key: string) => Effect.Effect<void, PersistenceError>;
    readonly clear: Effect.Effect<void, PersistenceError>;
}
/**
 * Provides `Persistence` from `BackingPersistence`.
 *
 * **Details**
 *
 * The layer serializes and deserializes `Persistable` exits, applies
 * per-entry TTLs, and skips writes whose TTL is zero or negative.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: Layer.Layer<Persistence, never, BackingPersistence>;
/**
 * Provides an in-memory `BackingPersistence` grouped by store id.
 *
 * **Details**
 *
 * Entries are process-local and expire according to their stored TTL.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerBackingMemory: Layer.Layer<BackingPersistence>;
/**
 * Provides SQL-backed persistence using one table per store id.
 *
 * **Details**
 *
 * Each table is created if needed and stores JSON-encoded values with optional
 * expiration timestamps.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerBackingSqlMultiTable: Layer.Layer<BackingPersistence, never, SqlClient.SqlClient>;
/**
 * Provides SQL-backed persistence using a shared `effect_persistence` table.
 *
 * **Details**
 *
 * Rows are partitioned by `store_id` and store JSON-encoded values with
 * optional expiration timestamps.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerBackingSql: Layer.Layer<BackingPersistence, never, SqlClient.SqlClient>;
/**
 * Provides Redis-backed persistence.
 *
 * **Details**
 *
 * Each store id is used as a key prefix, values are JSON-encoded, and finite
 * TTLs are stored with Redis expiration.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerBackingRedis: Layer.Layer<BackingPersistence, never, Redis.Redis>;
/**
 * Provides `BackingPersistence` using a `KeyValueStore`.
 *
 * **Details**
 *
 * Each store id becomes a key prefix, and values are stored as JSON with
 * optional expiration timestamps.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerBackingKvs: Layer.Layer<BackingPersistence, never, KeyValueStore.KeyValueStore>;
/**
 * Provides `Persistence` backed by the current `KeyValueStore`.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerKvs: Layer.Layer<Persistence, never, KeyValueStore.KeyValueStore>;
/**
 * Provides `Persistence` backed by process-local in-memory storage.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerMemory: Layer.Layer<Persistence>;
/**
 * Provides `Persistence` backed by the current `Redis` service.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerRedis: Layer.Layer<Persistence, never, Redis.Redis>;
/**
 * Provides `Persistence` backed by SQL with one table per store id.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerSqlMultiTable: Layer.Layer<Persistence, never, SqlClient.SqlClient>;
/**
 * Provides `Persistence` backed by SQL using a shared persistence table.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerSql: Layer.Layer<Persistence, never, SqlClient.SqlClient>;
/**
 * Converts a TTL to an absolute expiration timestamp in milliseconds.
 *
 * **Details**
 *
 * Returns `null` for no TTL and uses `clock.currentTimeMillisUnsafe`, so it is
 * intended for backing-store internals.
 *
 * @category converting
 * @since 4.0.0
 */
export declare const unsafeTtlToExpires: (clock: Clock.Clock, ttl: Duration.Duration | undefined) => number | null;
export {};
//# sourceMappingURL=Persistence.d.ts.map