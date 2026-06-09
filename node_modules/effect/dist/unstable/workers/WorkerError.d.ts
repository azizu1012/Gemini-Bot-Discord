import * as Schema from "../../Schema.ts";
declare const TypeId: "~effect/workers/WorkerError";
/**
 * Type-level identifier used to brand `WorkerError` values.
 *
 * @category type IDs
 * @since 4.0.0
 */
export type TypeId = typeof TypeId;
/**
 * Returns `true` when a value is a `WorkerError`.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isWorkerError: (u: unknown) => u is WorkerError;
declare const WorkerSpawnError_base: Schema.Class<WorkerSpawnError, Schema.Struct<{
    readonly _tag: Schema.tag<"WorkerSpawnError">;
    readonly message: Schema.String;
    readonly cause: Schema.optional<Schema.Defect>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Worker error reason for failures while spawning or setting up a worker.
 *
 * @category models
 * @since 4.0.0
 */
export declare class WorkerSpawnError extends WorkerSpawnError_base {
}
declare const WorkerSendError_base: Schema.Class<WorkerSendError, Schema.Struct<{
    readonly _tag: Schema.tag<"WorkerSendError">;
    readonly message: Schema.String;
    readonly cause: Schema.optional<Schema.Defect>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Worker error reason for failures while sending a message to a worker.
 *
 * @category models
 * @since 4.0.0
 */
export declare class WorkerSendError extends WorkerSendError_base {
}
declare const WorkerReceiveError_base: Schema.Class<WorkerReceiveError, Schema.Struct<{
    readonly _tag: Schema.tag<"WorkerReceiveError">;
    readonly message: Schema.String;
    readonly cause: Schema.optional<Schema.Defect>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Worker error reason for failures while receiving or handling a message from a
 * worker.
 *
 * @category models
 * @since 4.0.0
 */
export declare class WorkerReceiveError extends WorkerReceiveError_base {
}
declare const WorkerUnknownError_base: Schema.Class<WorkerUnknownError, Schema.Struct<{
    readonly _tag: Schema.tag<"WorkerUnknownError">;
    readonly message: Schema.String;
    readonly cause: Schema.optional<Schema.Defect>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Worker error reason for an unclassified worker failure.
 *
 * @category models
 * @since 4.0.0
 */
export declare class WorkerUnknownError extends WorkerUnknownError_base {
}
/**
 * Union of the specific failure reasons that can be wrapped by a `WorkerError`.
 *
 * @category models
 * @since 4.0.0
 */
export type WorkerErrorReason = WorkerSpawnError | WorkerSendError | WorkerReceiveError | WorkerUnknownError;
/**
 * Schema for decoding and encoding all supported worker error reason variants.
 *
 * @category models
 * @since 4.0.0
 */
export declare const WorkerErrorReason: Schema.Union<[
    typeof WorkerSpawnError,
    typeof WorkerSendError,
    typeof WorkerReceiveError,
    typeof WorkerUnknownError
]>;
declare const WorkerError_base: Schema.Class<WorkerError, Schema.Struct<{
    readonly _tag: Schema.tag<"WorkerError">;
    readonly reason: Schema.Union<[typeof WorkerSpawnError, typeof WorkerSendError, typeof WorkerReceiveError, typeof WorkerUnknownError]>;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Error raised by worker APIs, wrapping a specific `WorkerErrorReason` and
 * exposing its message and cause.
 *
 * @category models
 * @since 4.0.0
 */
export declare class WorkerError extends WorkerError_base {
    constructor(props: {
        readonly reason: WorkerErrorReason;
    });
    /**
     * Marks this value as a worker error for runtime guards.
     *
     * @since 4.0.0
     */
    readonly [TypeId]: TypeId;
    get message(): string;
}
export {};
//# sourceMappingURL=WorkerError.d.ts.map