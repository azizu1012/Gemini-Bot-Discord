import * as Effect from "../../Effect.ts";
import * as Layer from "../../Layer.ts";
import * as SqlClient from "../sql/SqlClient.ts";
import * as SqlError from "../sql/SqlError.ts";
import * as EventJournal from "./EventJournal.ts";
/**
 * Creates an `EventJournal` backed by a SQL database.
 *
 * **Details**
 *
 * The constructor creates the entry and remote metadata tables when needed,
 * persists local and remote entries, and uses the configured `SqlClient`.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options?: {
    readonly entryTable?: string;
    readonly remotesTable?: string;
}) => Effect.Effect<EventJournal.EventJournal["Service"], SqlError.SqlError, SqlClient.SqlClient>;
/**
 * Provides `EventJournal` using the SQL-backed implementation created by
 * `make`.
 *
 * **When to use**
 *
 * Use when composing a Layer graph that should provide a persistent SQL-backed
 * `EventJournal` from an existing `SqlClient` service.
 *
 * **Details**
 *
 * The layer delegates to `make(options)`, so the same optional `entryTable` and
 * `remotesTable` settings are used and construction requires `SqlClient` and
 * may fail with `SqlError`.
 *
 * **Gotchas**
 *
 * Layer construction performs the same minimal `CREATE TABLE IF NOT EXISTS`
 * setup as `make`; manage indexes and schema migrations outside this layer when
 * your SQL schema needs more than the built-in tables.
 *
 * @see {@link make} for constructing the SQL-backed service directly
 * @see {@link EventJournal.layerMemory} for an in-memory `EventJournal` layer
 * @see {@link EventJournal.layerIndexedDb} for an IndexedDB-backed `EventJournal` layer
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: (options?: {
    readonly entryTable?: string;
    readonly remotesTable?: string;
}) => Layer.Layer<EventJournal.EventJournal, SqlError.SqlError, SqlClient.SqlClient>;
//# sourceMappingURL=SqlEventJournal.d.ts.map