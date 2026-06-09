import * as Context from "../../Context.js";
import { pipeArguments } from "../../Pipeable.js";
import * as Predicate from "../../Predicate.js";
import * as Record from "../../Record.js";
const TypeId = "~effect/httpapi/HttpApiGroup";
/**
 * Returns `true` when a value is an `HttpApiGroup`, narrowing the value to the
 * group interface.
 *
 * @category guards
 * @since 4.0.0
 */
export const isHttpApiGroup = u => Predicate.hasProperty(u, TypeId);
const Proto = {
  [TypeId]: TypeId,
  add(...toAdd) {
    const endpoints = {
      ...this.endpoints
    };
    for (const endpoint of toAdd) {
      endpoints[endpoint.name] = endpoint;
    }
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints,
      annotations: this.annotations
    });
  },
  prefix(prefix) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: Record.map(this.endpoints, endpoint => endpoint.prefix(prefix)),
      annotations: this.annotations
    });
  },
  middleware(middleware) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: Record.map(this.endpoints, endpoint => endpoint.middleware(middleware)),
      annotations: this.annotations
    });
  },
  annotateMerge(annotations) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: this.endpoints,
      annotations: Context.merge(this.annotations, annotations)
    });
  },
  annotate(annotation, value) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: this.endpoints,
      annotations: Context.add(this.annotations, annotation, value)
    });
  },
  annotateEndpointsMerge(annotations) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: Record.map(this.endpoints, endpoint => endpoint.annotateMerge(annotations)),
      annotations: this.annotations
    });
  },
  annotateEndpoints(annotation, value) {
    return makeProto({
      identifier: this.identifier,
      topLevel: this.topLevel,
      endpoints: Record.map(this.endpoints, endpoint => endpoint.annotate(annotation, value)),
      annotations: this.annotations
    });
  },
  pipe() {
    return pipeArguments(this, arguments);
  }
};
const makeProto = options => {
  function HttpApiGroup() {}
  Object.setPrototypeOf(HttpApiGroup, Proto);
  HttpApiGroup.key = `effect/httpapi/HttpApiGroup/${options.identifier}`;
  return Object.assign(HttpApiGroup, options);
};
/**
 * Creates an empty `HttpApiGroup` with the supplied identifier.
 *
 * **Details**
 *
 * Add endpoints with `add`, provide implementations with `HttpApiBuilder.group`,
 * and set `topLevel` when the generated client should expose endpoint methods
 * directly instead of nesting them under the group name.
 *
 * @category constructors
 * @since 4.0.0
 */
export const make = (identifier, options) => makeProto({
  identifier,
  topLevel: options?.topLevel ?? false,
  endpoints: Record.empty(),
  annotations: Context.empty()
});
//# sourceMappingURL=HttpApiGroup.js.map