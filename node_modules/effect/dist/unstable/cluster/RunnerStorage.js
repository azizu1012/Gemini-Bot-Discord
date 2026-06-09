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
import { isArrayNonEmpty } from "../../Array.js";
import * as Context from "../../Context.js";
import * as Effect from "../../Effect.js";
import * as Layer from "../../Layer.js";
import * as MutableHashMap from "../../MutableHashMap.js";
import * as MachineId from "./MachineId.js";
import { Runner } from "./Runner.js";
import * as ShardId from "./ShardId.js";
/**
 * Represents a generic interface to the persistent storage required by the
 * cluster.
 *
 * @category models
 * @since 4.0.0
 */
export class RunnerStorage extends /*#__PURE__*/Context.Service()("effect/cluster/RunnerStorage") {}
/**
 * Adapts an encoded runner storage implementation into `RunnerStorage`, converting
 * runner addresses, runners, machine ids, and shard ids between typed values and
 * their string or numeric storage forms.
 *
 * @category layers
 * @since 4.0.0
 */
export const makeEncoded = encoded => RunnerStorage.of({
  getRunners: Effect.gen(function* () {
    const runners = yield* encoded.getRunners;
    const results = [];
    for (let i = 0; i < runners.length; i++) {
      const [runner, healthy] = runners[i];
      // @effect-diagnostics-next-line tryCatchInEffectGen:off
      try {
        results.push([Runner.decodeSync(runner), healthy]);
      } catch {
        //
      }
    }
    return results;
  }),
  register: (runner, healthy) => Effect.map(encoded.register(encodeRunnerAddress(runner.address), Runner.encodeSync(runner), healthy), MachineId.make),
  unregister: address => encoded.unregister(encodeRunnerAddress(address)),
  setRunnerHealth: (address, healthy) => encoded.setRunnerHealth(encodeRunnerAddress(address), healthy),
  acquire: (address, shardIds) => {
    const arr = Array.from(shardIds, id => id.toString());
    if (!isArrayNonEmpty(arr)) return Effect.succeed([]);
    return encoded.acquire(encodeRunnerAddress(address), arr).pipe(Effect.map(shards => shards.map(ShardId.fromString)));
  },
  refresh: (address, shardIds) => encoded.refresh(encodeRunnerAddress(address), Array.from(shardIds, id => id.toString())).pipe(Effect.map(shards => shards.map(ShardId.fromString))),
  release(address, shardId) {
    return encoded.release(encodeRunnerAddress(address), shardId.toString());
  },
  releaseAll(address) {
    return encoded.releaseAll(encodeRunnerAddress(address));
  }
});
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
export const makeMemory = /*#__PURE__*/Effect.gen(function* () {
  const runners = MutableHashMap.empty();
  let acquired = [];
  let id = 0;
  return RunnerStorage.of({
    getRunners: Effect.sync(() => Array.from(MutableHashMap.values(runners), runner => [runner, true])),
    register: runner => Effect.sync(() => {
      MutableHashMap.set(runners, runner.address, runner);
      return MachineId.make(id++);
    }),
    unregister: address => Effect.sync(() => {
      MutableHashMap.remove(runners, address);
    }),
    setRunnerHealth: () => Effect.void,
    acquire: (_address, shardIds) => {
      acquired = Array.from(shardIds);
      return Effect.succeed(Array.from(shardIds));
    },
    refresh: () => Effect.sync(() => acquired),
    release: () => Effect.void,
    releaseAll: () => Effect.void
  });
});
/**
 * Layer that provides the in-memory `RunnerStorage` implementation.
 *
 * @category layers
 * @since 4.0.0
 */
export const layerMemory = /*#__PURE__*/Layer.effect(RunnerStorage)(makeMemory);
// -------------------------------------------------------------------------------------
// internal
// -------------------------------------------------------------------------------------
const encodeRunnerAddress = runnerAddress => `${runnerAddress.host}:${runnerAddress.port}`;
//# sourceMappingURL=RunnerStorage.js.map