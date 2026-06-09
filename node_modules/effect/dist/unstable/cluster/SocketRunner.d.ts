import * as Layer from "../../Layer.ts";
import type * as RpcSerialization from "../rpc/RpcSerialization.ts";
import { SocketServer } from "../socket/SocketServer.ts";
import type { MessageStorage } from "./MessageStorage.ts";
import type { RunnerHealth } from "./RunnerHealth.ts";
import type * as Runners from "./Runners.ts";
import type * as RunnerStorage from "./RunnerStorage.ts";
import type * as Sharding from "./Sharding.ts";
import type { ShardingConfig } from "./ShardingConfig.ts";
/**
 * Layer that runs a cluster runner over the socket RPC protocol, providing
 * `Sharding` and `Runners` clients and logging the socket listen address.
 *
 * **When to use**
 *
 * Use when a cluster runner process should accept runner RPCs through a
 * provided `SocketServer` and receive shard assignments while exposing
 * `Sharding` and `Runners` services.
 *
 * **Details**
 *
 * It logs the bound `SocketServer.address` when the layer starts, formatting TCP
 * addresses as `hostname:port` and Unix socket addresses as their filesystem
 * path.
 *
 * **Gotchas**
 *
 * Although this layer serves runner RPCs with the provided `SocketServer`,
 * outgoing calls to other runners still require a `Runners.RpcClientProtocol`
 * service.
 *
 * @see {@link layerClientOnly} for the socket runner layer that only provides clients and does not receive shard assignments
 * @see {@link Runners.RpcClientProtocol} for the outgoing runner client protocol required by this layer
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: Layer.Layer<Sharding.Sharding | Runners.Runners, never, Runners.RpcClientProtocol | ShardingConfig | RpcSerialization.RpcSerialization | SocketServer | MessageStorage | RunnerStorage.RunnerStorage | RunnerHealth>;
/**
 * Provides a client-only socket runner layer that provides `Sharding` and `Runners` clients
 * without starting a runner server or receiving shard assignments.
 *
 * **When to use**
 *
 * Use to join a socket-based cluster as a client-only participant that can send
 * messages without hosting shards.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerClientOnly: Layer.Layer<Sharding.Sharding | Runners.Runners, never, Runners.RpcClientProtocol | ShardingConfig | MessageStorage | RunnerStorage.RunnerStorage>;
//# sourceMappingURL=SocketRunner.d.ts.map