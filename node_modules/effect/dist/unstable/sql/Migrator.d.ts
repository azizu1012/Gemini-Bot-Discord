import * as Effect from "../../Effect.ts";
import { FileSystem } from "../../FileSystem.ts";
import * as Client from "./SqlClient.ts";
import type { SqlError } from "./SqlError.ts";
/**
 * Options for running SQL migrations, including the migration loader, optional
 * schema dump directory, and migrations table name.
 *
 * @category options
 * @since 4.0.0
 */
export interface MigratorOptions<R = never> {
    readonly loader: Loader<R>;
    readonly schemaDirectory?: string;
    readonly table?: string;
}
/**
 * Effect that resolves the available migrations for the migrator or fails with a
 * `MigrationError`.
 *
 * @category models
 * @since 4.0.0
 */
export type Loader<R = never> = Effect.Effect<ReadonlyArray<ResolvedMigration>, MigrationError, R>;
/**
 * Tuple produced by a migration loader, containing the migration id, migration
 * name, and an effect that loads the migration implementation.
 *
 * @category models
 * @since 4.0.0
 */
export type ResolvedMigration = readonly [
    id: number,
    name: string,
    load: Effect.Effect<any, any, Client.SqlClient>
];
/**
 * Metadata for a migration recorded in the migrations table, including its id,
 * name, and creation timestamp.
 *
 * @category models
 * @since 4.0.0
 */
export interface Migration {
    readonly id: number;
    readonly name: string;
    readonly createdAt: Date;
}
declare const MigrationError_base: new <A extends Record<string, any> = {}>(args: import("../../Types.ts").VoidIfEmpty<{ readonly [P in keyof A as P extends "_tag" ? never : P]: A[P]; }>) => import("../../Cause.ts").YieldableError & {
    readonly _tag: "MigrationError";
} & Readonly<A>;
/**
 * Error raised while loading, validating, locking, or running SQL migrations.
 *
 * @category errors
 * @since 4.0.0
 */
export declare class MigrationError extends MigrationError_base<{
    readonly _tag: "MigrationError";
    readonly cause?: unknown;
    readonly kind: "BadState" | "ImportError" | "Failed" | "Duplicates" | "Locked";
    readonly message: string;
}> {
}
/**
 * Creates a migrator that ensures the migrations table exists, runs pending
 * migrations in a transaction, and optionally dumps the schema after successful
 * migrations.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: <RD = never>({ dumpSchema }: {
    dumpSchema?: (path: string, migrationsTable: string) => Effect.Effect<void, MigrationError, RD>;
}) => <R2 = never>({ loader, schemaDirectory, table }: MigratorOptions<R2>) => Effect.Effect<ReadonlyArray<readonly [id: number, name: string]>, MigrationError | SqlError, Client.SqlClient | RD | R2>;
/**
 * Creates a migration loader from a glob record of dynamic import functions,
 * parsing files named `<id>_<name>.js`, `<id>_<name>.ts`,
 * `<id>_<name>.mjs`, or `<id>_<name>.mts` and sorting migrations by id.
 *
 * @category loaders
 * @since 4.0.0
 */
export declare const fromGlob: (migrations: Record<string, () => Promise<any>>) => Loader;
/**
 * Creates a migration loader from a Babel-style glob record, parsing keys such
 * as `_<id>_<name>Js`, `_<id>_<name>Ts`, `_<id>_<name>Mjs`, or
 * `_<id>_<name>Mts` and sorting migrations by id.
 *
 * @category loaders
 * @since 4.0.0
 */
export declare const fromBabelGlob: (migrations: Record<string, any>) => Loader;
/**
 * Creates a migration loader from a record of migration effects keyed by
 * `<id>_<name>`, sorted by migration id.
 *
 * @category loaders
 * @since 4.0.0
 */
export declare const fromRecord: (migrations: Record<string, Effect.Effect<void, unknown, Client.SqlClient>>) => Loader;
/**
 * Creates a migration loader that reads a directory with `FileSystem`, imports
 * files named `<id>_<name>.js`, `<id>_<name>.ts`,
 * `<id>_<name>.mjs`, or `<id>_<name>.mts`, and sorts migrations by id.
 *
 * @category loaders
 * @since 4.0.0
 */
export declare const fromFileSystem: (directory: string) => Loader<FileSystem>;
export {};
//# sourceMappingURL=Migrator.d.ts.map