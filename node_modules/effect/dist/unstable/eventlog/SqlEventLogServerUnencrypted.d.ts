import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import type * as Scope from "../../Scope.ts";
import * as SqlClient from "../sql/SqlClient.ts";
import * as SqlError from "../sql/SqlError.ts";
import * as EventLogServerUnencrypted from "./EventLogServerUnencrypted.ts";
/**
 * Creates unencrypted event-log server `Storage` backed by SQL.
 *
 * **Details**
 *
 * The implementation creates tables for the server remote id, store sequences,
 * entries, and session authentication bindings, then persists and streams
 * plaintext remote entries.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const makeStorage: (options?: {
    readonly entryTablePrefix?: string;
    readonly remoteIdTable?: string;
    readonly insertBatchSize?: number;
}) => Effect.Effect<EventLogServerUnencrypted.Storage["Service"], SqlError.SqlError, SqlClient.SqlClient | Scope.Scope>;
/**
 * Provides unencrypted server `Storage` using the SQL-backed implementation.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layerStorage: (options?: {
    readonly entryTablePrefix?: string;
    readonly remoteIdTable?: string;
    readonly insertBatchSize?: number;
}) => Layer.Layer<EventLogServerUnencrypted.Storage, SqlError.SqlError, SqlClient.SqlClient>;
//# sourceMappingURL=SqlEventLogServerUnencrypted.d.ts.map