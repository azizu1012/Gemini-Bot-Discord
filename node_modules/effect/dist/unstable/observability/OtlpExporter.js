/**
 * Low-level OTLP/HTTP batch exporter used by the observability modules for
 * logs, metrics, and traces.
 *
 * This module owns the scoped transport loop for already-encoded telemetry
 * payloads: callers provide the OTLP endpoint, request headers, a body encoder,
 * and batching settings, then push records that should be delivered to a
 * collector. It is useful when implementing a concrete signal exporter, such
 * as the OTLP logger or tracer, or when wiring a snapshot-based exporter like
 * metrics into the same lifecycle and retry behavior.
 *
 * The exporter sends HTTP POST requests with the provided `HttpClient`, disables
 * tracer propagation for its own traffic, retries transient failures, and
 * honors numeric `retry-after` values on 429 responses. Exports run on
 * `exportInterval`, flush during scope finalization up to `shutdownTimeout`,
 * and can also be triggered early when the buffered item count reaches
 * `maxBatchSize`.
 *
 * Use `maxBatchSize: "disabled"` only for pull-style exporters whose `body`
 * callback builds a fresh payload without relying on drained buffered items,
 * because pushed data is not cleared in that mode. After an unrecovered export
 * failure the exporter drops the buffered batch and disables exporting for 60
 * seconds, so choose intervals, batch sizes, headers, and shutdown timeouts with
 * collector limits and process shutdown behavior in mind.
 *
 * @since 4.0.0
 */
import { Clock } from "../../Clock.js";
import * as Context from "../../Context.js";
import * as Duration from "../../Duration.js";
import * as Effect from "../../Effect.js";
import * as Fiber from "../../Fiber.js";
import * as Num from "../../Number.js";
import * as Option from "../../Option.js";
import * as Schedule from "../../Schedule.js";
import * as Scope from "../../Scope.js";
import * as Headers from "../../unstable/http/Headers.js";
import * as HttpClient from "../../unstable/http/HttpClient.js";
import * as HttpClientError from "../../unstable/http/HttpClientError.js";
import * as HttpClientRequest from "../../unstable/http/HttpClientRequest.js";
const policy = /*#__PURE__*/Schedule.forever.pipe(Schedule.passthrough, /*#__PURE__*/Schedule.addDelay(error => {
  if (HttpClientError.isHttpClientError(error) && error.reason._tag === "StatusCodeError" && error.reason.response.status === 429) {
    const retryAfter = Option.fromUndefinedOr(error.reason.response.headers["retry-after"]).pipe(Option.flatMap(Num.parse), Option.getOrElse(() => 5));
    return Effect.succeed(Duration.seconds(retryAfter));
  }
  return Effect.succeed(Duration.seconds(1));
}));
/**
 * Creates a scoped OTLP batch exporter.
 *
 * **Details**
 *
 * The exporter buffers pushed data, periodically posts encoded batches to the
 * configured URL, retries transient failures, temporarily disables exporting
 * after unhandled failures, and flushes during scope finalization up to
 * `shutdownTimeout`.
 *
 * @category constructors
 * @since 4.0.0
 */
export const make = /*#__PURE__*/Effect.fnUntraced(function* (options) {
  const services = yield* Effect.context();
  const clock = Context.get(services, Clock);
  const scope = Context.get(services, Scope.Scope);
  const runFork = Effect.runForkWith(services);
  const exportInterval = Duration.max(Duration.fromInputUnsafe(options.exportInterval), Duration.zero);
  let disabledUntil = undefined;
  const client = HttpClient.filterStatusOk(Context.get(services, HttpClient.HttpClient)).pipe(HttpClient.transformResponse(Effect.provideService(HttpClient.TracerPropagationEnabled, false)), HttpClient.retryTransient({
    schedule: policy,
    times: 3
  }));
  let headers = Headers.fromRecordUnsafe({
    "user-agent": `effect-opentelemetry-${options.label}/0.0.0`
  });
  if (options.headers) {
    headers = Headers.merge(Headers.fromInput(options.headers), headers);
  }
  const request = HttpClientRequest.post(options.url, {
    headers
  });
  let buffer = [];
  const runExport = Effect.suspend(() => {
    if (disabledUntil !== undefined && clock.currentTimeMillisUnsafe() < disabledUntil) {
      return Effect.void;
    } else if (disabledUntil !== undefined) {
      disabledUntil = undefined;
    }
    const items = buffer;
    if (options.maxBatchSize !== "disabled") {
      if (buffer.length === 0) {
        return Effect.void;
      }
      buffer = [];
    }
    return client.execute(HttpClientRequest.setBody(request, options.body(items))).pipe(Effect.asVoid, Effect.withTracerEnabled(false));
  }).pipe(Effect.catchCause(cause => {
    if (disabledUntil !== undefined) return Effect.void;
    disabledUntil = clock.currentTimeMillisUnsafe() + 60_000;
    buffer = [];
    return Effect.logDebug("Disabling exporter for 60 seconds", cause);
  }), Effect.annotateLogs({
    package: "@effect/opentelemetry",
    module: options.label
  }));
  yield* Scope.addFinalizer(scope, runExport.pipe(Effect.ignore, Effect.interruptible, Effect.timeoutOption(options.shutdownTimeout)));
  yield* Effect.sleep(exportInterval).pipe(Effect.andThen(runExport), Effect.forever, Effect.forkIn(scope));
  return {
    push(data) {
      if (disabledUntil !== undefined) return;
      buffer.push(data);
      if (options.maxBatchSize !== "disabled" && buffer.length >= options.maxBatchSize) {
        Fiber.runIn(runFork(runExport), scope);
      }
    }
  };
});
//# sourceMappingURL=OtlpExporter.js.map