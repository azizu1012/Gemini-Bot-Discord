import * as Schema from "../../Schema.js";
import * as Msgpack from "../encoding/Msgpack.js";
import * as Rpc from "../rpc/Rpc.js";
import * as RpcGroup from "../rpc/RpcGroup.js";
import * as RpcMiddleware from "../rpc/RpcMiddleware.js";
import * as Transferable from "../workers/Transferable.js";
import { Entry, RemoteEntry, RemoteId } from "./EventJournal.js";
import { EncryptedEntry, EncryptedRemoteEntry } from "./EventLogEncryption.js";
/**
 * Runtime brand identifier for event-log store ids.
 *
 * @category type IDs
 * @since 4.0.0
 */
export const StoreIdTypeId = "effect/eventlog/EventLog/StoreId";
/**
 * Schema for branded event-log store ids.
 *
 * @category StoreId
 * @since 4.0.0
 */
export const StoreId = /*#__PURE__*/Schema.String.pipe(/*#__PURE__*/Schema.brand(StoreIdTypeId));
/**
 * Error returned by event-log remote RPCs.
 *
 * **Details**
 *
 * It records the request tag, optional identity and store information, a protocol
 * error code, and a human-readable message.
 *
 * @category protocols
 * @since 4.0.0
 */
export class EventLogProtocolError extends /*#__PURE__*/Schema.TaggedErrorClass("effect/eventlog/EventLogRemote/ProtocolError")("EventLogProtocolError", {
  requestTag: Schema.String,
  publicKey: /*#__PURE__*/Schema.optional(Schema.String),
  storeId: /*#__PURE__*/Schema.optional(StoreId),
  code: /*#__PURE__*/Schema.Literals(["Unauthorized", "Forbidden", "NotFound", "InvalidRequest", "InternalServerError"]),
  message: Schema.String
}) {}
/**
 * RPC middleware that authenticates event-log requests and provides the client
 * `Identity` to authenticated handlers.
 *
 * @category middleware
 * @since 4.0.0
 */
export class EventLogAuthentication extends /*#__PURE__*/RpcMiddleware.Service()("effect/eventlog/EventLogMessage/EventLogAuthentication", {
  error: EventLogProtocolError
}) {}
/**
 * Response sent by the remote server during the authentication handshake.
 *
 * **Details**
 *
 * It contains the server remote id and a challenge that must be signed by the
 * client.
 *
 * @category protocols
 * @since 4.0.0
 */
export class HelloResponse extends /*#__PURE__*/Schema.Class("effect/eventlog/EventLogRemote/HelloResponse")({
  remoteId: RemoteId,
  challenge: Transferable.Uint8Array
}) {}
/**
 * RPC used to start an event-log remote session and receive a `HelloResponse`.
 *
 * @category protocols
 * @since 4.0.0
 */
export class HelloRpc extends /*#__PURE__*/Rpc.make("EventLog.Hello", {
  success: HelloResponse
}) {}
/**
 * Schema for an authentication request containing the client public key,
 * Ed25519 signing public key, signature over the session challenge payload, and
 * algorithm name.
 *
 * @category protocols
 * @since 4.0.0
 */
export class Authenticate extends /*#__PURE__*/Schema.Class("effect/eventlog/EventLogRemote/Authenticate")({
  publicKey: Schema.String,
  signingPublicKey: Transferable.Uint8Array,
  signature: Transferable.Uint8Array,
  algorithm: /*#__PURE__*/Schema.Literal("Ed25519")
}) {}
/**
 * RPC used to authenticate a remote event-log session after `HelloRpc`.
 *
 * @category protocols
 * @since 4.0.0
 */
export class AuthenticateRpc extends /*#__PURE__*/Rpc.make("EventLog.Authenticate", {
  payload: Authenticate,
  error: EventLogProtocolError
}) {}
/**
 * Represents an entire encoded event-log payload in one transport frame.
 *
 * @category protocols
 * @since 4.0.0
 */
export class SingleMessage extends /*#__PURE__*/Schema.TaggedClass("effect/eventlog/EventLogRemote/SingleMessage")("Single", {
  data: Transferable.Uint8Array
}) {}
/**
 * Represents one part of a large encoded event-log payload.
 *
 * **When to use**
 *
 * Use to divide data into chunks and `join` to reassemble all chunks with
 * the same id once every part has arrived.
 *
 * @category protocols
 * @since 4.0.0
 */
export class ChunkedMessage extends /*#__PURE__*/Schema.TaggedClass("effect/eventlog/EventLogRemote/ChunkedMessage")("Chunked", {
  id: Schema.Number,
  part: /*#__PURE__*/Schema.Tuple([Schema.Number, Schema.Number]),
  data: Transferable.Uint8Array
}) {
  static chunkSize = 512_000;
  static initialJoinState() {
    return new Map();
  }
  /**
   * Splits binary event-log message data into numbered chunks.
   *
   * @since 4.0.0
   */
  static split(id, data) {
    const parts = Math.ceil(data.byteLength / ChunkedMessage.chunkSize);
    const result = new Array(parts);
    for (let i = 0; i < parts; i++) {
      const start = i * ChunkedMessage.chunkSize;
      const end = Math.min((i + 1) * ChunkedMessage.chunkSize, data.byteLength);
      result[i] = new ChunkedMessage({
        id,
        part: [i, parts],
        data: data.subarray(start, end)
      });
    }
    return result;
  }
  /**
   * Reassembles all chunks for a message id into the original binary payload.
   *
   * @since 4.0.0
   */
  static join(map, part) {
    const [index, total] = part.part;
    let entry = map.get(part.id);
    if (!entry) {
      entry = {
        parts: new Array(total),
        count: 0,
        bytes: 0
      };
      map.set(part.id, entry);
    }
    entry.parts[index] = part.data;
    entry.count++;
    entry.bytes += part.data.byteLength;
    if (entry.count !== total) {
      return;
    }
    const data = new Uint8Array(entry.bytes);
    let offset = 0;
    for (const part of entry.parts) {
      data.set(part, offset);
      offset += part.byteLength;
    }
    map.delete(part.id);
    return data;
  }
}
/**
 * RPC used to send one chunk of a large encoded write payload.
 *
 * @category protocols
 * @since 4.0.0
 */
export class WriteChunkedRpc extends /*#__PURE__*/Rpc.make("EventLog.WriteChunked", {
  payload: ChunkedMessage,
  error: EventLogProtocolError
}).middleware(EventLogAuthentication) {}
/**
 * Schema for encrypted event-log write payloads sent to a remote store.
 *
 * **Details**
 *
 * It includes the client public key, target store id, AES-GCM initialization
 * vector, and encrypted entries.
 *
 * @category protocols
 * @since 4.0.0
 */
export class WriteEntries extends /*#__PURE__*/Schema.Class("effect/eventlog/EventLogRemote/WriteEntries")({
  publicKey: Schema.String,
  storeId: StoreId,
  iv: Transferable.Uint8Array,
  encryptedEntries: /*#__PURE__*/Schema.Array(EncryptedEntry)
}) {
  static FromMsgpack = /*#__PURE__*/Msgpack.schema(WriteEntries);
  static encode = /*#__PURE__*/Schema.encodeEffect(this.FromMsgpack);
  static decode = /*#__PURE__*/Schema.decodeEffect(this.FromMsgpack);
  get encoded() {
    return WriteEntries.encode(this);
  }
}
/**
 * Schema for plaintext event-log write payloads sent to a remote store.
 *
 * @category protocols
 * @since 4.0.0
 */
export class WriteEntriesUnencrypted extends /*#__PURE__*/Schema.Class("effect/eventlog/EventLogRemote/WriteEntriesUnencrypted")({
  publicKey: Schema.String,
  storeId: StoreId,
  entries: /*#__PURE__*/Schema.Array(Entry)
}) {
  static FromMsgpack = /*#__PURE__*/Msgpack.schema(WriteEntriesUnencrypted);
  static encode = /*#__PURE__*/Schema.encodeEffect(this.FromMsgpack);
  static decode = /*#__PURE__*/Schema.decodeEffect(this.FromMsgpack);
  get encoded() {
    return WriteEntriesUnencrypted.encode(this);
  }
}
/**
 * RPC used to send an encoded write payload that fits in one message.
 *
 * @category protocols
 * @since 4.0.0
 */
export class WriteSingleRpc extends /*#__PURE__*/Rpc.make("EventLog.WriteSingle", {
  payload: {
    data: Transferable.Uint8Array
  },
  error: EventLogProtocolError
}).middleware(EventLogAuthentication) {}
/**
 * RPC used to stream remote event-log changes for a public key and store id
 * starting at a sequence number.
 *
 * **Details**
 *
 * Responses are encoded as either `SingleMessage` values or `ChunkedMessage`
 * parts.
 *
 * @category protocols
 * @since 4.0.0
 */
export class ChangesRpc extends /*#__PURE__*/Rpc.make("EventLog.Changes", {
  payload: {
    publicKey: Schema.String,
    storeId: StoreId,
    startSequence: Schema.Number
  },
  success: Schema.Union([SingleMessage, ChunkedMessage]),
  error: EventLogProtocolError,
  stream: true
}).middleware(EventLogAuthentication) {
  static EncryptedFromMsgpack = /*#__PURE__*/Msgpack.schema(/*#__PURE__*/Schema.NonEmptyArray(EncryptedRemoteEntry));
  static UnencryptedFromMsgpack = /*#__PURE__*/Msgpack.schema(/*#__PURE__*/Schema.NonEmptyArray(RemoteEntry));
  static encodeEncrypted = /*#__PURE__*/Schema.encodeEffect(ChangesRpc.EncryptedFromMsgpack);
  static decodeEncrypted = /*#__PURE__*/Schema.decodeEffect(ChangesRpc.EncryptedFromMsgpack);
  static encodeUnencrypted = /*#__PURE__*/Schema.encodeEffect(ChangesRpc.UnencryptedFromMsgpack);
  static decodeUnencrypted = /*#__PURE__*/Schema.decodeEffect(ChangesRpc.UnencryptedFromMsgpack);
}
/**
 * RPC group containing the event-log remote handshake, authentication, write, and
 * changes endpoints.
 *
 * @category protocols
 * @since 4.0.0
 */
export class EventLogRemoteRpcs extends /*#__PURE__*/RpcGroup.make(HelloRpc, AuthenticateRpc, WriteChunkedRpc, WriteSingleRpc, ChangesRpc) {}
//# sourceMappingURL=EventLogMessage.js.map