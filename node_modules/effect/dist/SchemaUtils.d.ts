import * as Schema from "./Schema.ts";
/**
 * Builds an experimental schema for instances of a native class using a struct
 * schema as the encoded representation.
 *
 * **When to use**
 *
 * Use when you need a schema for an existing native class while keeping a
 * `Struct` schema as its encoded representation.
 *
 * **Details**
 *
 * Decoding constructs `new constructor(props)` from the encoded fields.
 * Encoding uses the instance as the encoded shape, so the class should expose
 * properties compatible with the provided encoding schema.
 *
 * @see {@link Schema.instanceOf} for validating existing class instances without a struct encoding
 * @see {@link Schema.Class} for defining schema-backed classes directly
 * @see {@link Schema.ErrorClass} for defining schema-backed error classes
 *
 * @category schemas
 * @since 4.0.0
 */
export declare function getNativeClassSchema<C extends new (...args: any) => any, S extends Schema.Struct<Schema.Struct.Fields>>(constructor: C, options: {
    readonly encoding: S;
    readonly annotations?: Schema.Annotations.Declaration<InstanceType<C>>;
}): Schema.decodeTo<Schema.instanceOf<InstanceType<C>, S["Iso"]>, S>;
//# sourceMappingURL=SchemaUtils.d.ts.map