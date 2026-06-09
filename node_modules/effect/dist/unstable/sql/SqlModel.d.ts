/**
 * Builds SQL repositories and request resolvers from Effect schema models.
 *
 * Use this module when a `Model` describes rows in a concrete SQL table and
 * you want the common insert, update, find-by-id, and delete operations without
 * hand-writing the schema encoding, row decoding, and resolver batching each
 * time. The helpers are intended for model-backed tables where the model field
 * names line up with the encoded table columns and the chosen `idColumn` is
 * present in both the model fields and update schema.
 *
 * Returned rows are decoded with the full model schema, while insert and update
 * requests are encoded with the model's dedicated input schemas. Soft deletes
 * are opt-in via `softDeleteColumn`: reads and updates only see rows where that
 * column is `null`, and deletes set it to `CURRENT_TIMESTAMP` instead of
 * removing the row. Dialects with `returning` support return changed rows
 * directly; MySQL performs a follow-up `select`, so generated ids, defaults,
 * and trigger-updated values must be observable from that query.
 *
 * @since 4.0.0
 */
import type * as Cause from "../../Cause.ts";
import * as Effect from "../../Effect.ts";
import * as RequestResolver from "../../RequestResolver.ts";
import type * as Schema from "../../Schema.ts";
import type { Scope } from "../../Scope.ts";
import type * as Model from "../schema/Model.ts";
import { SqlClient } from "./SqlClient.ts";
import type { ResultLengthMismatch, SqlError } from "./SqlError.ts";
import * as SqlResolver from "./SqlResolver.ts";
/**
 * Creates a CRUD repository for a schema model backed by a SQL table, with
 * insert, update, find-by-id, and delete operations. When `softDeleteColumn` is
 * supplied, reads ignore soft-deleted rows and delete updates that column
 * instead of removing the row.
 *
 * @category repository
 * @since 4.0.0
 */
export declare const makeRepository: <S extends Model.Any, Id extends (keyof S["Type"]) & (keyof S["update"]["Type"]) & (keyof S["fields"]), SoftDelete extends keyof S["fields"] = never>(Model: S, options: {
    readonly tableName: string;
    readonly spanPrefix: string;
    readonly idColumn: Id;
    readonly softDeleteColumn?: SoftDelete | undefined;
}) => Effect.Effect<{
    readonly insert: (insert: S["insert"]["Type"]) => Effect.Effect<S["Type"], Schema.SchemaError | SqlError, S["DecodingServices"] | S["insert"]["EncodingServices"]>;
    readonly insertVoid: (insert: S["insert"]["Type"]) => Effect.Effect<void, Schema.SchemaError | SqlError, S["insert"]["EncodingServices"]>;
    readonly update: (update: S["update"]["Type"]) => Effect.Effect<S["Type"], Schema.SchemaError | SqlError, S["DecodingServices"] | S["update"]["EncodingServices"]>;
    readonly updateVoid: (update: S["update"]["Type"]) => Effect.Effect<void, Schema.SchemaError | SqlError, S["update"]["EncodingServices"]>;
    readonly findById: (id: S["fields"][Id]["Type"]) => Effect.Effect<S["Type"], Cause.NoSuchElementError | Schema.SchemaError | SqlError, S["DecodingServices"] | S["fields"][Id]["EncodingServices"]>;
    readonly delete: (id: S["fields"][Id]["Type"]) => Effect.Effect<void, Schema.SchemaError | SqlError, S["fields"][Id]["EncodingServices"]>;
}, never, SqlClient>;
/**
 * Creates batched request resolvers for a schema model's insert, insert-void,
 * find-by-id, and delete operations, honoring the optional soft-delete column.
 *
 * @category repository
 * @since 4.0.0
 */
export declare const makeResolvers: <S extends Model.Any, Id extends (keyof S["Type"]) & (keyof S["update"]["Type"]) & (keyof S["fields"]), SoftDelete extends keyof S["fields"] = never>(Model: S, options: {
    readonly tableName: string;
    readonly spanPrefix: string;
    readonly idColumn: Id;
    readonly softDeleteColumn?: SoftDelete | undefined;
}) => Effect.Effect<{
    readonly insert: RequestResolver.RequestResolver<SqlResolver.SqlRequest<S["insert"]["Type"], S["Type"], ResultLengthMismatch | SqlError, S["insert"]["EncodingServices"]>>;
    readonly insertVoid: RequestResolver.RequestResolver<SqlResolver.SqlRequest<S["insert"]["Type"], void, SqlError, S["insert"]["EncodingServices"]>>;
    readonly findById: RequestResolver.RequestResolver<SqlResolver.SqlRequest<S["fields"][Id]["Type"], S["Type"], Cause.NoSuchElementError | SqlError, S["DecodingServices"] | S["fields"][Id]["EncodingServices"]>>;
    readonly delete: RequestResolver.RequestResolver<SqlResolver.SqlRequest<S["fields"][Id]["Type"], void, SqlError, S["fields"][Id]["EncodingServices"]>>;
}, never, SqlClient | Scope>;
//# sourceMappingURL=SqlModel.d.ts.map