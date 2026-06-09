import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import * as SqlClient from "../sql/SqlClient.ts";
import * as MessageStorage from "./MessageStorage.ts";
import type { ShardingConfig } from "./ShardingConfig.ts";
import * as Snowflake from "./Snowflake.ts";
/**
 * Creates a SQL-backed `MessageStorage` implementation, running its migrations
 * and using the optional table prefix.
 *
 * **When to use**
 *
 * Use when you need the SQL-backed `MessageStorage` service directly, such as
 * when composing a custom layer or providing your own `Snowflake.Generator`.
 *
 * **Details**
 *
 * The optional `prefix` controls the table names for messages, replies, and
 * migrations; when omitted, `cluster` is used.
 *
 * **Gotchas**
 *
 * Changing `prefix` after deployment points the runtime at a different set of
 * tables, including the migration history table.
 *
 * @see {@link layer} for a ready-made layer using the default prefix and generator
 * @see {@link layerWith} for a ready-made layer with a custom table prefix
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options?: {
    readonly prefix?: string | undefined;
}) => Effect.Effect<MessageStorage.MessageStorage["Service"], never, SqlClient.SqlClient | Snowflake.Generator>;
/**
 * Layer that provides SQL-backed `MessageStorage` using the default table prefix
 * and the default snowflake generator.
 *
 * **When to use**
 *
 * Use when a cluster should persist mailbox messages and replies in SQL using
 * the default `cluster` table prefix and the standard snowflake generator.
 *
 * **Details**
 *
 * The layer runs the SQL migrations through `make`, provides `MessageStorage`,
 * and supplies `Snowflake.layerGenerator` internally. Callers still provide
 * `SqlClient` and `ShardingConfig`.
 *
 * **Gotchas**
 *
 * This layer always uses the `cluster` table prefix. Use `layerWith` before
 * deployment if you need a different stable prefix, because changing prefixes
 * later points the runtime at a different set of tables.
 *
 * @see {@link layerWith} for the same SQL storage layer with a custom table prefix
 * @see {@link make} for the lower-level service constructor that uses an existing `Snowflake.Generator`
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: Layer.Layer<MessageStorage.MessageStorage, never, SqlClient.SqlClient | ShardingConfig>;
/**
 * Layer that provides SQL-backed `MessageStorage` using a custom table prefix.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerWith: (options: {
    readonly prefix?: string | undefined;
}) => Layer.Layer<MessageStorage.MessageStorage, never, SqlClient.SqlClient | ShardingConfig>;
//# sourceMappingURL=SqlMessageStorage.d.ts.map