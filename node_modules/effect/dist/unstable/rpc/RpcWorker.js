import * as Context from "../../Context.js";
import * as Effect from "../../Effect.js";
import * as Layer from "../../Layer.js";
import * as Schema from "../../Schema.js";
import * as Transferable from "../workers/Transferable.js";
/**
 * Context service that supplies the initial RPC worker message as encoded data
 * paired with any transferables that should be posted with it.
 *
 * @category initial message
 * @since 4.0.0
 */
export class InitialMessage extends /*#__PURE__*/Context.Service()("effect/rpc/RpcWorker/InitialMessage") {}
const ProtocolTag = /*#__PURE__*/Context.Service("effect/rpc/RpcServer/Protocol");
/**
 * Runs an effect, encodes its result with the schema's JSON codec, and returns
 * the encoded value together with collected transferables.
 *
 * @category initial message
 * @since 4.0.0
 */
export const makeInitialMessage = (schema, effect) => {
  const schemaJson = Schema.toCodecJson(schema);
  return Effect.flatMap(effect, value => {
    const collector = Transferable.makeCollectorUnsafe();
    return Schema.encodeEffect(schemaJson)(value).pipe(Effect.provideService(Transferable.Collector, collector), Effect.map(encoded => [encoded, collector.clearUnsafe()]));
  });
};
/**
 * Provides the `InitialMessage` service from a schema and build effect,
 * capturing the layer context and dying if schema encoding fails.
 *
 * @category initial message
 * @since 4.0.0
 */
export const layerInitialMessage = (schema, build) => Layer.effect(InitialMessage)(Effect.contextWith(context => Effect.succeed(Effect.provideContext(Effect.orDie(makeInitialMessage(schema, build)), context))));
/**
 * Reads the protocol initial message and decodes it with the supplied schema,
 * failing if no initial message is available or decoding fails.
 *
 * @category initial message
 * @since 4.0.0
 */
export const initialMessage = schema => ProtocolTag.pipe(Effect.flatMap(protocol => protocol.initialMessage), Effect.flatMap(Effect.fromOption), Effect.flatMap(Schema.decodeUnknownEffect(Schema.toCodecJson(schema))));
//# sourceMappingURL=RpcWorker.js.map