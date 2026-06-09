import * as Effect from "../../Effect.ts";
/**
 * OTLP resource metadata attached to exported logs, metrics, and traces.
 *
 * @category models
 * @since 4.0.0
 */
export interface Resource {
    /** Resource attributes */
    attributes: Array<KeyValue>;
    /** Resource droppedAttributesCount */
    droppedAttributesCount: number;
}
/**
 * Creates an OTLP resource from service metadata and additional attributes.
 *
 * **Details**
 *
 * The resource always includes `service.name`, includes `service.version` when
 * provided, and converts custom attributes into OTLP attribute values.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: (options: {
    readonly serviceName: string;
    readonly serviceVersion?: string | undefined;
    readonly attributes?: Record<string, unknown> | undefined;
}) => Resource;
/**
 * Creates an OTLP resource from explicit options and OpenTelemetry
 * configuration.
 *
 * **Details**
 *
 * Explicit options override `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_SERVICE_NAME`,
 * and `OTEL_SERVICE_VERSION`; missing required configuration is converted to a
 * defect.
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const fromConfig: (options?: {
    readonly serviceName?: string | undefined;
    readonly serviceVersion?: string | undefined;
    readonly attributes?: Record<string, unknown> | undefined;
} | undefined) => Effect.Effect<Resource>;
/**
 * Returns the `service.name` attribute from an OTLP resource.
 *
 * **Gotchas**
 *
 * Throws if the resource does not contain a string `service.name` attribute.
 *
 * @category Attributes
 * @since 4.0.0
 */
export declare const serviceNameUnsafe: (resource: Resource) => string;
/**
 * Converts key/value entries into OTLP `KeyValue` attributes.
 *
 * @category Attributes
 * @since 4.0.0
 */
export declare const entriesToAttributes: (entries: Iterable<[string, unknown]>) => Array<KeyValue>;
/**
 * Converts an arbitrary JavaScript value into an OTLP `AnyValue`.
 *
 * **Details**
 *
 * Arrays are converted recursively, primitive values use their matching OTLP
 * fields, and unsupported values are formatted as strings.
 *
 * @category Attributes
 * @since 4.0.0
 */
export declare const unknownToAttributeValue: (value: unknown) => AnyValue;
/**
 * An OTLP attribute represented as a string key and typed value.
 *
 * @category models
 * @since 4.0.0
 */
export interface KeyValue {
    /** KeyValue key */
    key: string;
    /** KeyValue value */
    value: AnyValue;
}
/**
 * OTLP `AnyValue` payload for scalar, array, key/value-list, or byte values.
 *
 * @category models
 * @since 4.0.0
 */
export interface AnyValue {
    /** AnyValue stringValue */
    stringValue?: string | null;
    /** AnyValue boolValue */
    boolValue?: boolean | null;
    /** AnyValue intValue */
    intValue?: number | null;
    /** AnyValue doubleValue */
    doubleValue?: number | null;
    /** AnyValue arrayValue */
    arrayValue?: ArrayValue;
    /** AnyValue kvlistValue */
    kvlistValue?: KeyValueList;
    /** AnyValue bytesValue */
    bytesValue?: Uint8Array;
}
/**
 * OTLP array value containing nested `AnyValue` entries.
 *
 * @category models
 * @since 4.0.0
 */
export interface ArrayValue {
    /** ArrayValue values */
    values: Array<AnyValue>;
}
/**
 * OTLP key/value-list value containing nested attributes.
 *
 * @category models
 * @since 4.0.0
 */
export interface KeyValueList {
    /** KeyValueList values */
    values: Array<KeyValue>;
}
/**
 * Low and high 32-bit parts of a 64-bit integer value.
 *
 * @category models
 * @since 4.0.0
 */
export interface LongBits {
    low: number;
    high: number;
}
/**
 * Accepted runtime representations for an OTLP/protobuf fixed 64-bit value.
 *
 * @category models
 * @since 4.0.0
 */
export type Fixed64 = LongBits | string | number;
//# sourceMappingURL=OtlpResource.d.ts.map