import type * as AtomRegistry from "./AtomRegistry.ts";
/**
 * Marker interface for entries in a dehydrated atom registry state.
 *
 * @category models
 * @since 4.0.0
 */
export interface DehydratedAtom {
    readonly "~effect/reactivity/DehydratedAtom": true;
}
/**
 * A dehydrated serializable atom value.
 *
 * **Details**
 *
 * It stores the atom serialization key, encoded value, dehydration timestamp, and
 * an optional promise used when an `AsyncResult.Initial` value is encoded as a
 * future non-initial value.
 *
 * @category models
 * @since 4.0.0
 */
export interface DehydratedAtomValue extends DehydratedAtom {
    readonly key: string;
    readonly value: unknown;
    readonly dehydratedAt: number;
    readonly resultPromise?: Promise<unknown> | undefined;
}
/**
 * Encodes the serializable atoms currently stored in a registry into dehydrated
 * state.
 *
 * **Details**
 *
 * Only atoms marked with `Atom.serializable` are included. `encodeInitialAs`
 * controls whether `AsyncResult.Initial` values are ignored, encoded as values, or
 * represented by promises that resolve when the atom leaves the initial state.
 *
 * @category dehydration
 * @since 4.0.0
 */
export declare const dehydrate: (registry: AtomRegistry.AtomRegistry, options?: {
    /**
     * How to encode `AsyncResult.Initial` values. Default is "ignore".
     */
    readonly encodeInitialAs?: "ignore" | "promise" | "value-only" | undefined;
}) => Array<DehydratedAtom>;
/**
 * Returns dehydrated state entries as `DehydratedAtomValue` records.
 *
 * @category dehydration
 * @since 4.0.0
 */
export declare const toValues: (state: ReadonlyArray<DehydratedAtom>) => Array<DehydratedAtomValue>;
/**
 * Applies dehydrated atom state to a registry.
 *
 * **When to use**
 *
 * Use to preload serialized atom values into a target registry before those
 * atoms are read.
 *
 * **Details**
 *
 * Encoded values are preloaded by serialization key. Entries with a
 * `resultPromise` update the matching registry node, or preload the resolved value,
 * when the promise resolves.
 *
 * @category hydration
 * @since 4.0.0
 */
export declare const hydrate: (registry: AtomRegistry.AtomRegistry, dehydratedState: Iterable<DehydratedAtom>) => void;
//# sourceMappingURL=Hydration.d.ts.map