/**
 * The `RunnerStorage` module defines the persistence boundary used by clustered
 * runners to register themselves and coordinate shard ownership.
 *
 * Implementations keep track of runner metadata, health, machine ids, and shard
 * locks so a cluster can rebalance work as runners join, leave, or lose their
 * leases. Production adapters usually implement the string-encoded interface and
 * adapt it with {@link makeEncoded}; tests and local setups can use
 * {@link makeMemory}.
 *
 * **Common tasks**
 *
 * - Register and unregister runners in a shared store
 * - Read runner health for scheduling and rebalancing decisions
 * - Acquire, refresh, and release shard locks for distributed processing
 * - Bridge typed cluster values to string or numeric database representations
 *
 * **Gotchas**
 *
 * - Shard acquisition may be partial; callers must use the returned shard list
 * - Refreshing leases is part of keeping shard ownership during rebalancing
 * - The in-memory implementation is process-local and does not persist runner
 *   registrations or locks across restarts
 *
 * @since 4.0.0
 */
import { type NonEmptyArray } from "../../Array.ts";
import * as Context from "../../Context.ts";
import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import type { PersistenceError } from "./ClusterError.ts";
import * as MachineId from "./MachineId.ts";
import { Runner } from "./Runner.ts";
import type { RunnerAddress } from "./RunnerAddress.ts";
import * as ShardId from "./ShardId.ts";
declare const RunnerStorage_base: Context.ServiceClass<RunnerStorage, "effect/cluster/RunnerStorage", {
    /**
     * Register a new runner with the cluster.
     */
    readonly register: (runner: Runner, healthy: boolean) => Effect.Effect<MachineId.MachineId, PersistenceError>;
    /**
     * Unregister the runner with the given address.
     */
    readonly unregister: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
    /**
     * Get all runners registered with the cluster.
     */
    readonly getRunners: Effect.Effect<Array<readonly [runner: Runner, healthy: boolean]>, PersistenceError>;
    /**
     * Set the health status of the given runner.
     */
    readonly setRunnerHealth: (address: RunnerAddress, healthy: boolean) => Effect.Effect<void, PersistenceError>;
    /**
     * Try to acquire the given shard ids for processing.
     *
     * It returns an array of shards it was able to acquire.
     */
    readonly acquire: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Refresh the locks owned by the given runner.
     */
    readonly refresh: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Release the given shard ids.
     */
    readonly release: (address: RunnerAddress, shardId: ShardId.ShardId) => Effect.Effect<void, PersistenceError>;
    /**
     * Release all the shards assigned to the given runner.
     */
    readonly releaseAll: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
}>;
/**
 * Represents a generic interface to the persistent storage required by the
 * cluster.
 *
 * @category models
 * @since 4.0.0
 */
export declare class RunnerStorage extends RunnerStorage_base {
}
/**
 * String-encoded runner storage interface used by adapters that persist runner
 * addresses, runners, machine ids, and shard ids outside the in-memory model.
 *
 * @category Encoded
 * @since 4.0.0
 */
export interface Encoded {
    /**
     * Get all runners registered with the cluster.
     */
    readonly getRunners: Effect.Effect<Array<readonly [runner: string, healthy: boolean]>, PersistenceError>;
    /**
     * Register a new runner with the cluster.
     */
    readonly register: (address: string, runner: string, healthy: boolean) => Effect.Effect<number, PersistenceError>;
    /**
     * Unregister the runner with the given address.
     */
    readonly unregister: (address: string) => Effect.Effect<void, PersistenceError>;
    /**
     * Set the health status of the given runner.
     */
    readonly setRunnerHealth: (address: string, healthy: boolean) => Effect.Effect<void, PersistenceError>;
    /**
     * Acquire the lock on the given shards, returning the shards that were
     * successfully locked.
     */
    readonly acquire: (address: string, shardIds: NonEmptyArray<string>) => Effect.Effect<Array<string>, PersistenceError>;
    /**
     * Refresh the lock on the given shards, returning the shards that were
     * successfully locked.
     */
    readonly refresh: (address: string, shardIds: Array<string>) => Effect.Effect<ReadonlyArray<string>, PersistenceError>;
    /**
     * Release the lock on the given shard.
     */
    readonly release: (address: string, shardId: string) => Effect.Effect<void, PersistenceError>;
    /**
     * Release the lock on all shards for the given runner.
     */
    readonly releaseAll: (address: string) => Effect.Effect<void, PersistenceError>;
}
/**
 * Adapts an encoded runner storage implementation into `RunnerStorage`, converting
 * runner addresses, runners, machine ids, and shard ids between typed values and
 * their string or numeric storage forms.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const makeEncoded: (encoded: Encoded) => {
    /**
     * Register a new runner with the cluster.
     */
    readonly register: (runner: Runner, healthy: boolean) => Effect.Effect<MachineId.MachineId, PersistenceError>;
    /**
     * Unregister the runner with the given address.
     */
    readonly unregister: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
    /**
     * Get all runners registered with the cluster.
     */
    readonly getRunners: Effect.Effect<Array<readonly [runner: Runner, healthy: boolean]>, PersistenceError>;
    /**
     * Set the health status of the given runner.
     */
    readonly setRunnerHealth: (address: RunnerAddress, healthy: boolean) => Effect.Effect<void, PersistenceError>;
    /**
     * Try to acquire the given shard ids for processing.
     *
     * It returns an array of shards it was able to acquire.
     */
    readonly acquire: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Refresh the locks owned by the given runner.
     */
    readonly refresh: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Release the given shard ids.
     */
    readonly release: (address: RunnerAddress, shardId: ShardId.ShardId) => Effect.Effect<void, PersistenceError>;
    /**
     * Release all the shards assigned to the given runner.
     */
    readonly releaseAll: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
};
/**
 * Creates an in-memory `RunnerStorage` implementation for tests and local use.
 *
 * **Details**
 *
 * Registered runners are treated as healthy and shard acquisition is kept only in
 * process memory.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const makeMemory: Effect.Effect<{
    /**
     * Register a new runner with the cluster.
     */
    readonly register: (runner: Runner, healthy: boolean) => Effect.Effect<MachineId.MachineId, PersistenceError>;
    /**
     * Unregister the runner with the given address.
     */
    readonly unregister: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
    /**
     * Get all runners registered with the cluster.
     */
    readonly getRunners: Effect.Effect<Array<readonly [runner: Runner, healthy: boolean]>, PersistenceError>;
    /**
     * Set the health status of the given runner.
     */
    readonly setRunnerHealth: (address: RunnerAddress, healthy: boolean) => Effect.Effect<void, PersistenceError>;
    /**
     * Try to acquire the given shard ids for processing.
     *
     * It returns an array of shards it was able to acquire.
     */
    readonly acquire: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Refresh the locks owned by the given runner.
     */
    readonly refresh: (address: RunnerAddress, shardIds: Iterable<ShardId.ShardId>) => Effect.Effect<Array<ShardId.ShardId>, PersistenceError>;
    /**
     * Release the given shard ids.
     */
    readonly release: (address: RunnerAddress, shardId: ShardId.ShardId) => Effect.Effect<void, PersistenceError>;
    /**
     * Release all the shards assigned to the given runner.
     */
    readonly releaseAll: (address: RunnerAddress) => Effect.Effect<void, PersistenceError>;
}, never, never>;
/**
 * Layer that provides the in-memory `RunnerStorage` implementation.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerMemory: Layer.Layer<RunnerStorage>;
export {};
//# sourceMappingURL=RunnerStorage.d.ts.map