import * as Channel from "../../Channel.js";
import * as Context from "../../Context.js";
import * as Effect from "../../Effect.js";
import * as Inspectable from "../../Inspectable.js";
import * as Option from "../../Option.js";
import * as Result from "../../Result.js";
import * as Schema from "../../Schema.js";
import * as Stream from "../../Stream.js";
import * as Socket from "../socket/Socket.js";
import * as Cookies from "./Cookies.js";
import * as Headers from "./Headers.js";
import * as HttpBody from "./HttpBody.js";
import * as HttpClientRequest from "./HttpClientRequest.js";
import * as HttpIncomingMessage from "./HttpIncomingMessage.js";
import { hasBody } from "./HttpMethod.js";
import { HttpServerError, RequestParseError } from "./HttpServerError.js";
import * as Multipart from "./Multipart.js";
import * as UrlParams from "./UrlParams.js";
export {
/**
 * Provides the `MaxBodySize` fiber reference for configuring request body limits.
 *
 * **When to use**
 *
 * Use to configure the maximum body size accepted while reading server
 * request bodies.
 *
 * @category fiber refs
 * @since 4.0.0
 */
MaxBodySize } from "./HttpIncomingMessage.js";
/**
 * Runtime type identifier for `HttpServerRequest` values.
 *
 * @category type IDs
 * @since 4.0.0
 */
export const TypeId = "~effect/http/HttpServerRequest";
/**
 * Service tag for the active server-side HTTP request.
 *
 * **When to use**
 *
 * Use to access the request currently being handled by HTTP server routes and
 * middleware.
 *
 * @category context
 * @since 4.0.0
 */
export const HttpServerRequest = /*#__PURE__*/Context.Service("effect/http/HttpServerRequest");
/**
 * Service that contains decoded URL query parameters for the current request.
 *
 * **When to use**
 *
 * Use to access query parameters that have already been parsed for the current
 * server request.
 *
 * **Details**
 *
 * Each key maps to a string value, or to an array when the parameter appears more
 * than once.
 *
 * @category search params
 * @since 4.0.0
 */
export class ParsedSearchParams extends /*#__PURE__*/Context.Service()("effect/http/ParsedSearchParams") {}
/**
 * Converts a `URL` object's search parameters into a record.
 *
 * **Details**
 *
 * Repeated parameters are represented as arrays in insertion order.
 *
 * @category search params
 * @since 4.0.0
 */
export const searchParamsFromURL = url => {
  const out = {};
  for (const [key, value] of url.searchParams.entries()) {
    const entry = out[key];
    if (entry !== undefined) {
      if (Array.isArray(entry)) {
        entry.push(value);
      } else {
        out[key] = [entry, value];
      }
    } else {
      out[key] = value;
    }
  }
  return out;
};
/**
 * Creates a channel backed by the current request's upgraded socket.
 *
 * **Details**
 *
 * The channel reads incoming socket messages and writes byte chunks to the
 * socket, failing if the request cannot be upgraded or the socket fails.
 *
 * @category accessors
 * @since 4.0.0
 */
export const upgradeChannel = () => HttpServerRequest.pipe(Effect.flatMap(_ => _.upgrade), Effect.map(Socket.toChannelWith()), Channel.unwrap);
/**
 * Decodes a schema from the cookies of the current request.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaCookies = (schema, options) => {
  const parse = Schema.decodeUnknownEffect(schema);
  return Effect.flatMap(HttpServerRequest, req => parse(req.cookies, options));
};
/**
 * Decodes a schema from the headers of the current request.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaHeaders = (schema, options) => {
  const parse = Schema.decodeUnknownEffect(schema);
  return Effect.flatMap(HttpServerRequest, req => parse(req.headers, options));
};
/**
 * Decodes a schema from the parsed search parameters of the current request.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaSearchParams = (schema, options) => {
  const parse = Schema.decodeUnknownEffect(schema);
  return Effect.flatMap(ParsedSearchParams, params => parse(params, options));
};
/**
 * Reads the current request body as JSON and decodes it with the supplied schema.
 *
 * **Details**
 *
 * The effect can fail if the body cannot be read or parsed, or if schema decoding
 * fails.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaBodyJson = (schema, options) => {
  const parse = HttpIncomingMessage.schemaBodyJson(schema, options);
  return Effect.flatMap(HttpServerRequest, parse);
};
const isMultipart = request => request.headers["content-type"]?.toLowerCase().includes("multipart/form-data") === true || getFormDataBody(request) !== undefined;
/**
 * Decodes the current request body as form data.
 *
 * **Details**
 *
 * Multipart requests are persisted and decoded as multipart data; other form
 * requests are decoded from URL-encoded body parameters.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaBodyForm = (schema, options) => {
  const parseMultipart = Multipart.schemaPersisted(schema);
  const parseUrlParams = HttpIncomingMessage.schemaBodyUrlParams(schema, options);
  return Effect.flatMap(HttpServerRequest, request => {
    if (isMultipart(request)) {
      return Effect.flatMap(request.multipart, _ => parseMultipart(_, options));
    }
    return parseUrlParams(request);
  });
};
/**
 * Reads the current request body as URL-encoded parameters and decodes them with
 * the supplied schema.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaBodyUrlParams = (schema, options) => {
  const parse = HttpIncomingMessage.schemaBodyUrlParams(schema, options);
  return Effect.flatMap(HttpServerRequest, parse);
};
/**
 * Persists the current multipart request body and decodes it with the supplied
 * schema.
 *
 * **Details**
 *
 * The effect requires the services needed to persist multipart files, including a
 * scope, file system, and path service.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaBodyMultipart = (schema, options) => {
  const parse = Multipart.schemaPersisted(schema);
  return HttpServerRequest.pipe(Effect.flatMap(_ => _.multipart), Effect.flatMap(_ => parse(_, options)));
};
/**
 * Creates a decoder for a JSON value stored in a form field.
 *
 * **Details**
 *
 * For multipart requests, the named multipart field is decoded as JSON. For
 * URL-encoded requests, the named parameter is decoded as JSON and then decoded
 * with the supplied schema.
 *
 * @category schemas
 * @since 4.0.0
 */
export const schemaBodyFormJson = (schema, options) => {
  const parseMultipart = Multipart.schemaJson(schema, options);
  return field => {
    const parseUrlParams = UrlParams.schemaJsonField(field).pipe(Schema.decodeTo(schema), Schema.decodeEffect);
    return Effect.flatMap(HttpServerRequest, request => {
      if (isMultipart(request)) {
        return Effect.flatMap(Effect.mapError(request.multipart, cause => new HttpServerError({
          reason: new RequestParseError({
            request,
            cause
          })
        })), parseMultipart(field));
      }
      return Effect.flatMap(request.urlParamsBody, _ => parseUrlParams(_, options));
    });
  };
};
/**
 * Creates an `HttpServerRequest` view of an `HttpClientRequest`.
 *
 * **Details**
 *
 * If the client request can be converted to an absolute URL, that URL is used as
 * the original URL.
 *
 * @category converting
 * @since 4.0.0
 */
export const fromClientRequest = request => {
  const url = Option.match(HttpClientRequest.toUrl(request), {
    onNone: () => request.url,
    onSome: url => url.toString()
  });
  return new ClientRequestImpl(request, url);
};
/**
 * Wraps a Web `Request` as an `HttpServerRequest`.
 *
 * **Details**
 *
 * The request's current URL is stored without the scheme and host, while the
 * original Web URL remains available as `originalUrl`.
 *
 * @category converting
 * @since 4.0.0
 */
export const fromWeb = request => new ServerRequestImpl(request, removeHost(request.url));
/**
 * Converts an `HttpServerRequest` into an `HttpClientRequest`.
 *
 * **Details**
 *
 * The converted request preserves the method, headers, body stream, and a URL
 * derived from the request when possible.
 *
 * @category converting
 * @since 4.0.0
 */
export const toClientRequest = request => HttpClientRequest.setUrl(HttpClientRequest.makeWith(request.method, "", UrlParams.empty, Option.none(), request.headers, toClientBody(request)), Option.getOrElse(toURL(request), () => request.url));
const toClientBody = request => hasBody(request.method) ? HttpBody.stream(request.stream, request.headers["content-type"], parseContentLength(request.headers["content-length"])) : HttpBody.empty;
const parseContentLength = contentLength => {
  if (contentLength === undefined) {
    return undefined;
  }
  const parsed = Number.parseInt(contentLength, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
};
const removeHost = url => {
  if (url[0] === "/") {
    return url;
  }
  const index = url.indexOf("/", url.indexOf("//") + 2);
  return index === -1 ? "/" : url.slice(index);
};
class ServerRequestImpl extends Inspectable.Class {
  [TypeId];
  [HttpIncomingMessage.TypeId];
  source;
  url;
  headersOverride;
  remoteAddressOverride;
  constructor(source, url, headersOverride, remoteAddressOverride) {
    super();
    this[TypeId] = TypeId;
    this[HttpIncomingMessage.TypeId] = HttpIncomingMessage.TypeId;
    this.source = source;
    this.url = url;
    this.headersOverride = headersOverride;
    this.remoteAddressOverride = remoteAddressOverride;
  }
  toJSON() {
    return HttpIncomingMessage.inspect(this, {
      _id: "HttpServerRequest",
      method: this.method,
      url: this.originalUrl
    });
  }
  modify(options) {
    return new ServerRequestImpl(this.source, options.url ?? this.url, options.headers ?? this.headersOverride, "remoteAddress" in options ? options.remoteAddress : this.remoteAddressOverride);
  }
  get method() {
    return this.source.method.toUpperCase();
  }
  get originalUrl() {
    return this.source.url;
  }
  get remoteAddress() {
    return this.remoteAddressOverride ?? Option.none();
  }
  get headers() {
    this.headersOverride ??= Headers.fromInput(this.source.headers);
    return this.headersOverride;
  }
  cachedCookies;
  get cookies() {
    if (this.cachedCookies) {
      return this.cachedCookies;
    }
    return this.cachedCookies = Cookies.parseHeader(this.headers.cookie ?? "");
  }
  get stream() {
    return this.source.body ? Stream.fromReadableStream({
      evaluate: () => this.source.body,
      onError: cause => new HttpServerError({
        reason: new RequestParseError({
          request: this,
          cause
        })
      })
    }) : Stream.fail(new HttpServerError({
      reason: new RequestParseError({
        request: this,
        description: "can not create stream from empty body"
      })
    }));
  }
  textEffect;
  get text() {
    if (this.textEffect) {
      return this.textEffect;
    }
    this.textEffect = Effect.runSync(Effect.cached(Effect.tryPromise({
      try: () => this.source.text(),
      catch: cause => new HttpServerError({
        reason: new RequestParseError({
          request: this,
          cause
        })
      })
    })));
    return this.textEffect;
  }
  get json() {
    return Effect.flatMap(this.text, text => Effect.try({
      try: () => JSON.parse(text),
      catch: cause => new HttpServerError({
        reason: new RequestParseError({
          request: this,
          cause
        })
      })
    }));
  }
  get urlParamsBody() {
    return Effect.flatMap(this.text, _ => Effect.try({
      try: () => UrlParams.fromInput(new URLSearchParams(_)),
      catch: cause => new HttpServerError({
        reason: new RequestParseError({
          request: this,
          cause
        })
      })
    }));
  }
  multipartEffect;
  get multipart() {
    if (this.multipartEffect) {
      return this.multipartEffect;
    }
    this.multipartEffect = Effect.runSync(Effect.cached(Multipart.toPersisted(this.multipartStream)));
    return this.multipartEffect;
  }
  get multipartStream() {
    return Stream.pipeThroughChannel(Stream.mapError(this.stream, cause => Multipart.MultipartError.fromReason("InternalError", cause)), Multipart.makeChannel(this.headers));
  }
  arrayBufferEffect;
  get arrayBuffer() {
    if (this.arrayBufferEffect) {
      return this.arrayBufferEffect;
    }
    this.arrayBufferEffect = Effect.runSync(Effect.cached(Effect.tryPromise({
      try: () => this.source.arrayBuffer(),
      catch: cause => new HttpServerError({
        reason: new RequestParseError({
          request: this,
          cause
        })
      })
    })));
    return this.arrayBufferEffect;
  }
  get upgrade() {
    return Effect.fail(new HttpServerError({
      reason: new RequestParseError({
        request: this,
        description: "Not an upgradeable ServerRequest"
      })
    }));
  }
}
class ClientRequestImpl extends Inspectable.Class {
  [TypeId];
  [HttpIncomingMessage.TypeId];
  source;
  originalUrl;
  headersOverride;
  remoteAddressOverride;
  urlOverride;
  constructor(source, originalUrl, urlOverride, headersOverride, remoteAddressOverride) {
    super();
    this[TypeId] = TypeId;
    this[HttpIncomingMessage.TypeId] = HttpIncomingMessage.TypeId;
    this.source = source;
    this.originalUrl = originalUrl;
    this.urlOverride = urlOverride;
    this.headersOverride = headersOverride;
    this.remoteAddressOverride = remoteAddressOverride;
  }
  toJSON() {
    return HttpIncomingMessage.inspect(this, {
      _id: "HttpServerRequest",
      method: this.method,
      url: this.originalUrl
    });
  }
  modify(options) {
    return new ClientRequestImpl(this.source, this.originalUrl, options.url ?? this.url, options.headers ?? this.headersOverride, "remoteAddress" in options ? options.remoteAddress : this.remoteAddressOverride);
  }
  get method() {
    return this.source.method;
  }
  get url() {
    return this.urlOverride ?? removeHost(this.originalUrl);
  }
  get remoteAddress() {
    return this.remoteAddressOverride ?? Option.none();
  }
  get headers() {
    return this.headersOverride ??= this.source.headers;
  }
  cachedCookies;
  get cookies() {
    if (this.cachedCookies) {
      return this.cachedCookies;
    }
    return this.cachedCookies = Cookies.parseHeader(this.headers.cookie ?? "");
  }
  get stream() {
    const body = this.source.body;
    switch (body._tag) {
      case "Empty":
        {
          return Stream.empty;
        }
      case "Uint8Array":
        {
          return Stream.succeed(body.body);
        }
      case "Stream":
        {
          return Stream.mapError(body.stream, cause => requestParseError(this, undefined, cause));
        }
      case "FormData":
        {
          return streamFromReadable(this, new Response(body.formData).body);
        }
      case "Raw":
        {
          return rawBodyStream(this, body.body);
        }
    }
  }
  bytesEffect;
  get bytes() {
    if (this.bytesEffect) {
      return this.bytesEffect;
    }
    const body = this.source.body;
    let effect;
    switch (body._tag) {
      case "Empty":
        {
          effect = Effect.succeed(new Uint8Array(0));
          break;
        }
      case "Uint8Array":
        {
          effect = Effect.succeed(body.body);
          break;
        }
      case "FormData":
        {
          effect = bytesFromBodyInit(this, body.formData);
          break;
        }
      case "Stream":
        {
          effect = Stream.mkUint8Array(this.stream);
          break;
        }
      case "Raw":
        {
          effect = rawBodyBytes(this, body.body);
          break;
        }
    }
    this.bytesEffect = Effect.runSync(Effect.cached(effect));
    return this.bytesEffect;
  }
  get text() {
    return Effect.map(this.bytes, bytes => textDecoder.decode(bytes));
  }
  get json() {
    return Effect.flatMap(this.text, text => Effect.try({
      try: () => text === "" ? null : JSON.parse(text),
      catch: cause => requestParseError(this, undefined, cause)
    }));
  }
  get urlParamsBody() {
    return Effect.flatMap(this.text, _ => Effect.try({
      try: () => UrlParams.fromInput(new URLSearchParams(_)),
      catch: cause => requestParseError(this, undefined, cause)
    }));
  }
  multipartEffect;
  get multipart() {
    if (this.multipartEffect) {
      return this.multipartEffect;
    }
    this.multipartEffect = Effect.runSync(Effect.cached(Multipart.toPersisted(this.multipartStream)));
    return this.multipartEffect;
  }
  get multipartStream() {
    const formData = this.source.body._tag === "FormData" && this.source.body.formData;
    if (formData) {
      return Stream.fromIterable(formDataToParts(formData));
    }
    return Stream.pipeThroughChannel(Stream.mapError(this.stream, cause => Multipart.MultipartError.fromReason("InternalError", cause)), Multipart.makeChannel(this.headers));
  }
  get arrayBuffer() {
    return Effect.map(this.bytes, bytes => bytes.slice().buffer);
  }
  get upgrade() {
    return Effect.fail(requestParseError(this, "Not an upgradeable ServerRequest"));
  }
}
const getFormDataBody = request => {
  if (!HttpClientRequest.isHttpClientRequest(request.source)) {
    return undefined;
  }
  const body = request.source.body;
  if (body._tag === "FormData") {
    return body.formData;
  }
  if (body._tag === "Raw" && isFormData(body.body)) {
    return body.body;
  }
  return undefined;
};
const rawBodyStream = (request, body) => {
  if (body instanceof Request) {
    return streamFromReadable(request, body.body);
  }
  if (isFormData(body)) {
    return streamFromReadable(request, new Response(body).body);
  }
  if (isReadableStream(body)) {
    return streamFromReadable(request, body);
  }
  return Stream.fail(requestParseError(request, "Unsupported body type"));
};
const rawBodyBytes = (request, body) => {
  if (body instanceof Blob) {
    return bytesFromBodyInit(request, body);
  }
  if (body instanceof Request) {
    return Effect.tryPromise({
      try: () => body.arrayBuffer().then(buffer => new Uint8Array(buffer)),
      catch: cause => requestParseError(request, undefined, cause)
    });
  }
  return Effect.fail(requestParseError(request, "Unsupported body type"));
};
const bytesFromBodyInit = (request, body) => Effect.tryPromise({
  try: () => new Response(body).arrayBuffer().then(buffer => new Uint8Array(buffer)),
  catch: cause => requestParseError(request, undefined, cause)
});
const streamFromReadable = (request, body) => body ? Stream.fromReadableStream({
  evaluate: () => body,
  onError: cause => requestParseError(request, undefined, cause)
}) : Stream.empty;
const requestParseError = (request, description, cause) => new HttpServerError({
  reason: new RequestParseError({
    request,
    ...(description === undefined ? undefined : {
      description
    }),
    ...(cause === undefined ? undefined : {
      cause
    })
  })
});
const formDataToParts = formData => {
  const parts = [];
  for (const [key, value] of formData.entries()) {
    parts.push(typeof value === "string" ? new MultipartFieldPart(key, value) : new MultipartFilePart(key, value));
  }
  return parts;
};
class MultipartFieldPart extends Inspectable.Class {
  [Multipart.TypeId];
  _tag = "Field";
  contentType = "text/plain";
  key;
  value;
  constructor(key, value) {
    super();
    this[Multipart.TypeId] = Multipart.TypeId;
    this.key = key;
    this.value = value;
  }
  toJSON() {
    return {
      _id: "@effect/platform/Multipart/Part",
      _tag: "Field",
      key: this.key,
      contentType: this.contentType,
      value: this.value
    };
  }
}
class MultipartFilePart extends Inspectable.Class {
  [Multipart.TypeId];
  _tag = "File";
  key;
  name;
  contentType;
  content;
  contentEffect;
  constructor(key, file) {
    super();
    this[Multipart.TypeId] = Multipart.TypeId;
    this.key = key;
    this.name = file.name;
    this.contentType = file.type;
    this.content = Stream.fromReadableStream({
      evaluate: () => file.stream(),
      onError: cause => Multipart.MultipartError.fromReason("InternalError", cause)
    });
    this.contentEffect = Effect.tryPromise({
      try: () => file.arrayBuffer().then(buffer => new Uint8Array(buffer)),
      catch: cause => Multipart.MultipartError.fromReason("InternalError", cause)
    });
  }
  toJSON() {
    return {
      _id: "@effect/platform/Multipart/Part",
      _tag: "File",
      key: this.key,
      name: this.name,
      contentType: this.contentType
    };
  }
}
const isReadableStream = u => typeof ReadableStream !== "undefined" && u instanceof ReadableStream;
const isFormData = u => typeof FormData !== "undefined" && u instanceof FormData;
const textDecoder = /*#__PURE__*/new TextDecoder();
/**
 * Attempts to construct an absolute `URL` for a server request safely.
 *
 * **Details**
 *
 * The host comes from the `host` header, defaulting to `localhost`, and the
 * protocol is `https` only when `x-forwarded-proto` is `https`; invalid URLs
 * return `Option.none`.
 *
 * @category converting
 * @since 4.0.0
 */
export const toURL = self => {
  const host = self.headers.host ?? "localhost";
  const protocol = self.headers["x-forwarded-proto"] === "https" ? "https" : "http";
  try {
    return Option.some(new URL(self.url, `${protocol}://${host}`));
  } catch {
    return Option.none();
  }
};
/**
 * Converts an `HttpServerRequest` safely to a Web `Request` as a `Result`.
 *
 * **Details**
 *
 * If the source is already a Web `Request`, it is returned unchanged. Otherwise
 * an absolute URL is derived from the request; invalid URLs fail with a
 * `RequestParseError`.
 *
 * @category converting
 * @since 4.0.0
 */
export const toWebResult = (self, options) => {
  if (self.source instanceof Request) {
    return Result.succeed(self.source);
  }
  const url = toURL(self);
  if (Option.isNone(url)) {
    return Result.fail(new RequestParseError({
      request: self,
      description: "Invalid URL"
    }));
  }
  const requestInit = {
    method: self.method,
    headers: self.headers
  };
  if (options?.signal) {
    requestInit.signal = options.signal;
  }
  if (hasBody(self.method)) {
    requestInit.body = Stream.toReadableStreamWith(self.stream, options?.context ?? Context.empty());
    requestInit.duplex = "half";
  }
  return Result.succeed(new Request(url.value, requestInit));
};
/**
 * Converts an `HttpServerRequest` to a Web `Request` in `Effect`.
 *
 * **Details**
 *
 * The current context is used when streaming the request body into the Web
 * request.
 *
 * @category converting
 * @since 4.0.0
 */
export const toWeb = (self, options) => Effect.contextWith(context => Effect.fromResult(toWebResult(self, {
  context,
  signal: options?.signal
})));
//# sourceMappingURL=HttpServerRequest.js.map