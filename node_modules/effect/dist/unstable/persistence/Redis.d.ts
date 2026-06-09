import * as Context from "../../Context.ts";
import * as Effect from "../../Effect.ts";
import * as Schema from "../../Schema.ts";
declare const Redis_base: Context.ServiceClass<Redis, "effect/persistence/Redis", {
    readonly send: <A = unknown>(command: string, ...args: ReadonlyArray<string>) => Effect.Effect<A, RedisError>;
    readonly eval: <Config extends {
        readonly params: ReadonlyArray<unknown>;
        readonly result: unknown;
    }>(script: Script<Config>) => (...params: Config["params"]) => Effect.Effect<Config["result"], RedisError>;
}>;
/**
 * Service for sending Redis commands and evaluating cached Lua scripts.
 *
 * @category services
 * @since 4.0.0
 */
export declare class Redis extends Redis_base {
}
/**
 * Creates a `Redis` service from a raw command sender.
 *
 * **Details**
 *
 * Lua scripts are loaded through `SCRIPT LOAD`, cached, and then invoked with
 * `EVALSHA`.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options: {
    readonly send: <A = unknown>(command: string, ...args: ReadonlyArray<string>) => Effect.Effect<A, RedisError>;
}) => Effect.Effect<{
    readonly send: <A = unknown>(command: string, ...args: ReadonlyArray<string>) => Effect.Effect<A, RedisError>;
    readonly eval: <Config extends {
        readonly params: ReadonlyArray<unknown>;
        readonly result: unknown;
    }>(script: Script<Config>) => (...params: Config["params"]) => Effect.Effect<Config["result"], RedisError>;
}, never, never>;
type ErrorTypeId = "~effect/persistence/Redis/RedisError";
declare const ErrorTypeId: ErrorTypeId;
declare const RedisError_base: Schema.Class<RedisError, Schema.Struct<{
    readonly _tag: Schema.tag<"RedisError">;
    readonly cause: Schema.Defect;
}>, import("../../Cause.ts").YieldableError>;
/**
 * Error raised by Redis command or script execution.
 *
 * @category errors
 * @since 4.0.0
 */
export declare class RedisError extends RedisError_base {
    /**
     * Marks this value as a Redis persistence error for runtime guards.
     *
     * @since 4.0.0
     */
    readonly [ErrorTypeId]: ErrorTypeId;
}
type ScriptTypeId = "~effect/persistence/Redis/Script";
declare const ScriptTypeId: ScriptTypeId;
/**
 * Typed descriptor for a Redis Lua script.
 *
 * **Details**
 *
 * It defines the Lua source, parameter-to-argument mapping, Redis key count,
 * and result type used by `Redis.eval`.
 *
 * @category Scripting
 * @since 4.0.0
 */
export interface Script<Config extends {
    readonly params: ReadonlyArray<unknown>;
    readonly result: unknown;
}> {
    readonly [ScriptTypeId]: {
        readonly params: Config["params"];
        readonly result: Config["result"];
    };
    readonly lua: string;
    readonly params: (...params: Config["params"]) => ReadonlyArray<unknown>;
    readonly numberOfKeys: (...params: Config["params"]) => number;
    /**
     * Set the return type of the script.
     */
    withReturnType<Result>(): Script<{
        params: Config["params"];
        result: Result;
    }>;
}
/**
 * Constructs a typed Redis Lua script descriptor.
 *
 * **Details**
 *
 * The result type defaults to `void` and can be refined with
 * `withReturnType`.
 *
 * @category Scripting
 * @since 4.0.0
 */
export declare const script: <Params extends ReadonlyArray<any>>(f: (...params: Params) => ReadonlyArray<unknown>, options: {
    readonly lua: string;
    readonly numberOfKeys: number | ((...params: Params) => number);
}) => Script<{
    params: Params;
    result: void;
}>;
export {};
//# sourceMappingURL=Redis.d.ts.map