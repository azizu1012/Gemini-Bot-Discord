import type * as Option from "../../Option.ts";
import * as Schema from "../../Schema.ts";
/**
 * Schema for a span status representing a span that has started but not yet
 * ended.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const SpanStatusStarted: Schema.Struct<{
    readonly _tag: Schema.tag<"Started">;
    readonly startTime: Schema.BigInt;
}>;
/**
 * Type of a span status representing a span that has started but not yet ended.
 *
 * @category schemas
 * @since 4.0.0
 */
export type SpanStatusStarted = Schema.Schema.Type<typeof SpanStatusStarted>;
/**
 * Schema for a span status representing an ended span, including start time,
 * end time, and encoded exit status. Encoding drops success values with
 * `Exit.asVoid`.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const SpanStatusEnded: Schema.Struct<{
    readonly _tag: Schema.tag<"Ended">;
    readonly startTime: Schema.BigInt;
    readonly endTime: Schema.BigInt;
    readonly exit: Schema.decodeTo<Schema.Exit<Schema.Unknown, Schema.Unknown, Schema.Unknown>, Schema.Exit<Schema.Void, Schema.Defect, Schema.Defect>, never, never>;
}>;
/**
 * Type of a span status representing an ended span with start time, end time,
 * and exit status.
 *
 * @category schemas
 * @since 4.0.0
 */
export type SpanStatusEnded = Schema.Schema.Type<typeof SpanStatusEnded>;
/**
 * Schema for devtools span status, either started or ended.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const SpanStatus: Schema.Union<readonly [Schema.Struct<{
    readonly _tag: Schema.tag<"Started">;
    readonly startTime: Schema.BigInt;
}>, Schema.Struct<{
    readonly _tag: Schema.tag<"Ended">;
    readonly startTime: Schema.BigInt;
    readonly endTime: Schema.BigInt;
    readonly exit: Schema.decodeTo<Schema.Exit<Schema.Unknown, Schema.Unknown, Schema.Unknown>, Schema.Exit<Schema.Void, Schema.Defect, Schema.Defect>, never, never>;
}>]>;
/**
 * Type of a devtools span status, either started or ended.
 *
 * @category schemas
 * @since 4.0.0
 */
export type SpanStatus = Schema.Schema.Type<typeof SpanStatus>;
/**
 * Serialized parent span context for a span created outside the current
 * devtools span tree.
 *
 * @category schemas
 * @since 4.0.0
 */
export interface ExternalSpan {
    readonly _tag: "ExternalSpan";
    readonly spanId: string;
    readonly traceId: string;
    readonly sampled: boolean;
}
/**
 * Schema for an external parent span context containing span id, trace id, and
 * sampling flag.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const ExternalSpan: Schema.Codec<ExternalSpan>;
/**
 * Telemetry payload for an Effect span sent to devtools, including identity,
 * attributes, status, sampling flag, and optional parent span.
 *
 * @category schemas
 * @since 4.0.0
 */
export interface Span {
    readonly _tag: "Span";
    readonly spanId: string;
    readonly traceId: string;
    readonly name: string;
    readonly sampled: boolean;
    readonly attributes: ReadonlyMap<string, unknown>;
    readonly status: SpanStatus;
    readonly parent: Option.Option<ParentSpan>;
}
/**
 * Schema for an Effect span telemetry payload sent to devtools.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Span: Schema.Codec<Span>;
/**
 * Schema for a named event emitted by a span, including trace id, span id,
 * start time, and optional attributes.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const SpanEvent: Schema.Struct<{
    readonly _tag: Schema.tag<"SpanEvent">;
    readonly traceId: Schema.String;
    readonly spanId: Schema.String;
    readonly name: Schema.String;
    readonly startTime: Schema.BigInt;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.Any>>;
}>;
/**
 * Type of a named event emitted by a span and sent to devtools.
 *
 * @category schemas
 * @since 4.0.0
 */
export type SpanEvent = Schema.Schema.Type<typeof SpanEvent>;
/**
 * Type of a span parent, represented either by a devtools `Span` payload or an
 * `ExternalSpan` context.
 *
 * @category schemas
 * @since 4.0.0
 */
export type ParentSpan = Span | ExternalSpan;
/**
 * Schema for a span parent, either a full devtools `Span` payload or an
 * `ExternalSpan` context.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const ParentSpan: Schema.Union<readonly [Schema.Codec<Span, Span, never, never>, Schema.Codec<ExternalSpan, ExternalSpan, never, never>]>;
/**
 * Schema for the devtools heartbeat request sent by the client.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Ping: Schema.Struct<{
    readonly _tag: Schema.tag<"Ping">;
}>;
/**
 * Type of the devtools heartbeat request sent by the client.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Ping = Schema.Schema.Type<typeof Ping>;
/**
 * Schema for the devtools heartbeat response.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Pong: Schema.Struct<{
    readonly _tag: Schema.tag<"Pong">;
}>;
/**
 * Type of the devtools heartbeat response.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Pong = Schema.Schema.Type<typeof Pong>;
/**
 * Schema for a devtools request asking the client to send a metrics snapshot.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const MetricsRequest: Schema.Struct<{
    readonly _tag: Schema.tag<"MetricsRequest">;
}>;
/**
 * Type of a devtools request asking the client to send a metrics snapshot.
 *
 * @category schemas
 * @since 4.0.0
 */
export type MetricsRequest = Schema.Schema.Type<typeof MetricsRequest>;
/**
 * Schema for a metric label key/value pair in a devtools metrics snapshot.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const MetricLabel: Schema.Struct<{
    readonly key: Schema.String;
    readonly value: Schema.String;
}>;
/**
 * Type of a metric label key/value pair in a devtools metrics snapshot.
 *
 * @category schemas
 * @since 4.0.0
 */
export type MetricLabel = Schema.Schema.Type<typeof MetricLabel>;
/**
 * Schema for a counter metric snapshot, including the count and whether updates
 * are incremental.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Counter: Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Counter">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly count: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
        readonly incremental: Schema.Boolean;
    }>;
}>;
/**
 * Type of a devtools counter metric snapshot.
 *
 * **Details**
 *
 * The state contains the current count and whether the counter reports
 * incremental updates.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Counter = Schema.Schema.Type<typeof Counter>;
/**
 * Schema for a devtools frequency metric snapshot.
 *
 * **Details**
 *
 * The metric state records occurrence counts by string key.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Frequency: Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Frequency">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly occurrences: Schema.$ReadonlyMap<Schema.String, Schema.Number>;
    }>;
}>;
/**
 * Type of a devtools frequency metric snapshot.
 *
 * **Details**
 *
 * The state maps observed string values to occurrence counts.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Frequency = Schema.Schema.Type<typeof Frequency>;
/**
 * Schema for a devtools gauge metric snapshot.
 *
 * **Details**
 *
 * The metric state contains the current numeric or bigint value.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Gauge: Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Gauge">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly value: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
    }>;
}>;
/**
 * Type of a devtools gauge metric snapshot.
 *
 * **Details**
 *
 * The state contains the current numeric or bigint value.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Gauge = Schema.Schema.Type<typeof Gauge>;
/**
 * Schema for a devtools histogram metric snapshot.
 *
 * **Details**
 *
 * The metric state includes bucket counts plus the total count, minimum,
 * maximum, and sum.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Histogram: Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Histogram">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly buckets: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.Number]>>;
        readonly count: Schema.Number;
        readonly min: Schema.Number;
        readonly max: Schema.Number;
        readonly sum: Schema.Number;
    }>;
}>;
/**
 * Type of a devtools histogram metric snapshot.
 *
 * **Details**
 *
 * The state includes bucket counts plus the total count, minimum, maximum, and
 * sum.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Histogram = Schema.Schema.Type<typeof Histogram>;
/**
 * Schema for a devtools summary metric snapshot.
 *
 * **Details**
 *
 * The metric state contains quantile values plus the total count, minimum,
 * maximum, and sum.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Summary: Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Summary">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly quantiles: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.UndefinedOr<Schema.Number>]>>;
        readonly count: Schema.Number;
        readonly min: Schema.Number;
        readonly max: Schema.Number;
        readonly sum: Schema.Number;
    }>;
}>;
/**
 * Type of a devtools summary metric snapshot.
 *
 * **Details**
 *
 * The state contains quantile values plus the total count, minimum, maximum,
 * and sum.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Summary = Schema.Schema.Type<typeof Summary>;
/**
 * Schema for any devtools metric snapshot.
 *
 * **Details**
 *
 * Accepted metric kinds are counters, frequencies, gauges, histograms, and
 * summaries.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Metric: Schema.Union<readonly [Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Counter">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly count: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
        readonly incremental: Schema.Boolean;
    }>;
}>, Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Frequency">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly occurrences: Schema.$ReadonlyMap<Schema.String, Schema.Number>;
    }>;
}>, Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Gauge">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly value: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
    }>;
}>, Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Histogram">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly buckets: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.Number]>>;
        readonly count: Schema.Number;
        readonly min: Schema.Number;
        readonly max: Schema.Number;
        readonly sum: Schema.Number;
    }>;
}>, Schema.Struct<{
    readonly id: Schema.String;
    readonly type: Schema.tag<"Summary">;
    readonly description: Schema.UndefinedOr<Schema.String>;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
    readonly state: Schema.Struct<{
        readonly quantiles: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.UndefinedOr<Schema.Number>]>>;
        readonly count: Schema.Number;
        readonly min: Schema.Number;
        readonly max: Schema.Number;
        readonly sum: Schema.Number;
    }>;
}>]>;
/**
 * Type of any devtools metric snapshot.
 *
 * **Details**
 *
 * The union covers counters, frequencies, gauges, histograms, and summaries.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Metric = Schema.Schema.Type<typeof Metric>;
/**
 * Schema for a devtools protocol message containing the current metric
 * snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const MetricsSnapshot: Schema.Struct<{
    readonly _tag: Schema.tag<"MetricsSnapshot">;
    readonly metrics: Schema.$Array<Schema.Union<readonly [Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Counter">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly count: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
            readonly incremental: Schema.Boolean;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Frequency">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly occurrences: Schema.$ReadonlyMap<Schema.String, Schema.Number>;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Gauge">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly value: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Histogram">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly buckets: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.Number]>>;
            readonly count: Schema.Number;
            readonly min: Schema.Number;
            readonly max: Schema.Number;
            readonly sum: Schema.Number;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Summary">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly quantiles: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.UndefinedOr<Schema.Number>]>>;
            readonly count: Schema.Number;
            readonly min: Schema.Number;
            readonly max: Schema.Number;
            readonly sum: Schema.Number;
        }>;
    }>]>>;
}>;
/**
 * Type of a devtools protocol message containing the current metric snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export type MetricsSnapshot = Schema.Schema.Type<typeof MetricsSnapshot>;
/**
 * Schema for devtools protocol requests accepted by the server.
 *
 * **Details**
 *
 * Requests include heartbeat pings, spans, span events, and metric snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Request: Schema.Union<readonly [Schema.Struct<{
    readonly _tag: Schema.tag<"Ping">;
}>, Schema.Codec<Span, Span, never, never>, Schema.Struct<{
    readonly _tag: Schema.tag<"SpanEvent">;
    readonly traceId: Schema.String;
    readonly spanId: Schema.String;
    readonly name: Schema.String;
    readonly startTime: Schema.BigInt;
    readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.Any>>;
}>, Schema.Struct<{
    readonly _tag: Schema.tag<"MetricsSnapshot">;
    readonly metrics: Schema.$Array<Schema.Union<readonly [Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Counter">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly count: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
            readonly incremental: Schema.Boolean;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Frequency">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly occurrences: Schema.$ReadonlyMap<Schema.String, Schema.Number>;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Gauge">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly value: Schema.Union<readonly [Schema.Number, Schema.BigInt]>;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Histogram">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly buckets: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.Number]>>;
            readonly count: Schema.Number;
            readonly min: Schema.Number;
            readonly max: Schema.Number;
            readonly sum: Schema.Number;
        }>;
    }>, Schema.Struct<{
        readonly id: Schema.String;
        readonly type: Schema.tag<"Summary">;
        readonly description: Schema.UndefinedOr<Schema.String>;
        readonly attributes: Schema.UndefinedOr<Schema.$Record<Schema.String, Schema.String>>;
        readonly state: Schema.Struct<{
            readonly quantiles: Schema.$Array<Schema.Tuple<readonly [Schema.Number, Schema.UndefinedOr<Schema.Number>]>>;
            readonly count: Schema.Number;
            readonly min: Schema.Number;
            readonly max: Schema.Number;
            readonly sum: Schema.Number;
        }>;
    }>]>>;
}>]>;
/**
 * Type of devtools protocol requests accepted by the server.
 *
 * **Details**
 *
 * Requests include heartbeat pings, spans, span events, and metric snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Request = Schema.Schema.Type<typeof Request>;
/**
 * Namespace containing helper types for devtools protocol requests.
 *
 * @since 4.0.0
 */
export declare namespace Request {
    /**
     * Devtools request messages excluding heartbeat pings.
     *
     * **Details**
     *
     * `DevToolsServer` handles `Ping` internally and exposes only these requests
     * to client handlers.
     *
     * @since 4.0.0
     */
    type WithoutPing = Exclude<Request, {
        readonly _tag: "Ping";
    }>;
}
/**
 * Schema for devtools protocol responses sent by the server.
 *
 * **Details**
 *
 * Responses include heartbeat pongs and requests for metric snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export declare const Response: Schema.Union<readonly [Schema.Struct<{
    readonly _tag: Schema.tag<"Pong">;
}>, Schema.Struct<{
    readonly _tag: Schema.tag<"MetricsRequest">;
}>]>;
/**
 * Type of devtools protocol responses sent by the server.
 *
 * **Details**
 *
 * Responses include heartbeat pongs and requests for metric snapshots.
 *
 * @category schemas
 * @since 4.0.0
 */
export type Response = Schema.Schema.Type<typeof Response>;
/**
 * Namespace containing helper types for devtools protocol responses.
 *
 * @since 4.0.0
 */
export declare namespace Response {
    /**
     * Devtools response messages excluding heartbeat pongs.
     *
     * **Details**
     *
     * `DevToolsServer` sends `Pong` internally and accepts only these responses
     * from client handlers.
     *
     * @since 4.0.0
     */
    type WithoutPong = Exclude<Response, {
        readonly _tag: "Pong";
    }>;
}
//# sourceMappingURL=DevToolsSchema.d.ts.map