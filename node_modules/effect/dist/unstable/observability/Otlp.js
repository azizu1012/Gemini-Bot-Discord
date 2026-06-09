import { flow } from "../../Function.js";
import * as Layer from "../../Layer.js";
import * as HttpClientRequest from "../http/HttpClientRequest.js";
import * as OtlpLogger from "./OtlpLogger.js";
import * as OtlpMetrics from "./OtlpMetrics.js";
import * as OtlpSerialization from "./OtlpSerialization.js";
import * as OtlpTracer from "./OtlpTracer.js";
/**
 * Creates a combined OTLP layer for logs, metrics, and traces.
 *
 * **Details**
 *
 * The layer sends data to `/v1/logs`, `/v1/metrics`, and `/v1/traces` below
 * `baseUrl` and requires an `OtlpSerialization` implementation.
 *
 * @category layers
 * @since 4.0.0
 */
export const layer = options => {
  const base = HttpClientRequest.get(options.baseUrl);
  const url = path => HttpClientRequest.appendUrl(base, path).url;
  return Layer.mergeAll(OtlpLogger.layer({
    url: url("/v1/logs"),
    resource: options.resource,
    headers: options.headers,
    exportInterval: options.loggerExportInterval,
    maxBatchSize: options.maxBatchSize,
    shutdownTimeout: options.shutdownTimeout,
    excludeLogSpans: options.loggerExcludeLogSpans,
    mergeWithExisting: options.loggerMergeWithExisting
  }), OtlpMetrics.layer({
    url: url("/v1/metrics"),
    resource: options.resource,
    headers: options.headers,
    exportInterval: options.metricsExportInterval,
    shutdownTimeout: options.shutdownTimeout,
    temporality: options.metricsTemporality
  }), OtlpTracer.layer({
    url: url("/v1/traces"),
    resource: options.resource,
    headers: options.headers,
    exportInterval: options.tracerExportInterval,
    maxBatchSize: options.maxBatchSize,
    context: options.tracerContext,
    shutdownTimeout: options.shutdownTimeout
  }));
};
/**
 * Creates the combined OTLP logs, metrics, and traces layer using JSON
 * serialization.
 *
 * @category layers
 * @since 4.0.0
 */
export const layerJson = /*#__PURE__*/flow(layer, /*#__PURE__*/Layer.provide(OtlpSerialization.layerJson));
/**
 * Creates the combined OTLP logs, metrics, and traces layer using protobuf
 * serialization.
 *
 * @category layers
 * @since 4.0.0
 */
export const layerProtobuf = /*#__PURE__*/flow(layer, /*#__PURE__*/Layer.provide(OtlpSerialization.layerProtobuf));
//# sourceMappingURL=Otlp.js.map