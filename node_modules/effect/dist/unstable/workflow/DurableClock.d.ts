import * as Duration from "../../Duration.ts";
import * as Effect from "../../Effect.ts";
import type * as Schema from "../../Schema.ts";
import * as DurableDeferred from "./DurableDeferred.ts";
import type { WorkflowEngine, WorkflowInstance } from "./WorkflowEngine.ts";
declare const TypeId = "~effect/workflow/DurableClock";
/**
 * Represents a durable workflow timer with a name, duration, and deferred
 * completed when the timer wakes.
 *
 * @category models
 * @since 4.0.0
 */
export interface DurableClock {
    readonly [TypeId]: typeof TypeId;
    readonly name: string;
    readonly duration: Duration.Duration;
    readonly deferred: DurableDeferred.DurableDeferred<typeof Schema.Void>;
}
/**
 * Creates a durable clock definition and its associated deferred wake-up
 * signal.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options: {
    readonly name: string;
    readonly duration: Duration.Input;
}) => DurableClock;
/**
 * Waits inside a workflow, using an in-memory activity for durations at or
 * below the threshold and scheduling a durable clock for longer durations.
 *
 * @category sleeping
 * @since 4.0.0
 */
export declare const sleep: (options: {
    readonly name: string;
    readonly duration: Duration.Input;
    /**
     * If the duration is less than or equal to this threshold, the clock will
     * be executed in memory.
     *
     * @default 60 seconds
     */
    readonly inMemoryThreshold?: Duration.Input | undefined;
}) => Effect.Effect<void, never, WorkflowEngine | WorkflowInstance>;
export {};
//# sourceMappingURL=DurableClock.d.ts.map