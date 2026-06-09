import { dual } from "../../Function.js";
import * as Param from "./Param.js";
// -------------------------------------------------------------------------------------
// constructors
// -------------------------------------------------------------------------------------
/**
 * Creates a positional string argument.
 *
 * **Example** (Creating a string argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const filename = Argument.string("filename")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const string = name => Param.string(Param.argumentKind, name);
/**
 * Creates a positional integer argument.
 *
 * **Example** (Creating an integer argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const count = Argument.integer("count")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const integer = name => Param.integer(Param.argumentKind, name);
/**
 * Creates a positional file path argument.
 *
 * **Example** (Creating file path arguments)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const inputFile = Argument.file("input", { mustExist: true }) // Must exist
 * const outputFile = Argument.file("output", { mustExist: false }) // Must not exist
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const file = (name, options) => Param.file(Param.argumentKind, name, options);
/**
 * Creates a positional directory path argument.
 *
 * **Example** (Creating a directory path argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const workspace = Argument.directory("workspace", { mustExist: true }) // Must exist
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const directory = (name, options) => Param.directory(Param.argumentKind, name, options);
/**
 * Creates a positional float argument.
 *
 * **Example** (Creating a float argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const ratio = Argument.float("ratio")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const float = name => Param.float(Param.argumentKind, name);
/**
 * Creates a positional date argument.
 *
 * **Example** (Creating a date argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const startDate = Argument.date("start-date")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const date = name => Param.date(Param.argumentKind, name);
/**
 * Creates a positional choice argument.
 *
 * **Example** (Creating a choice argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const environment = Argument.choice("environment", ["dev", "staging", "prod"])
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const choice = (name, choices) => Param.choice(Param.argumentKind, name, choices);
/**
 * Creates a positional path argument.
 *
 * **Example** (Creating a path argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const configPath = Argument.path("config")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const path = (name, options) => Param.path(Param.argumentKind, name, options);
/**
 * Creates a positional redacted argument that obscures its value.
 *
 * **Example** (Creating a redacted argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const secret = Argument.redacted("secret")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const redacted = name => Param.redacted(Param.argumentKind, name);
/**
 * Creates a positional argument that reads file content as a string.
 *
 * **Example** (Reading file text)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const config = Argument.fileText("config-file")
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const fileText = name => Param.fileText(Param.argumentKind, name);
/**
 * Creates a positional argument that reads a file and parses its content.
 *
 * **Details**
 *
 * The parser is chosen from the explicit `format` option or, when omitted, the
 * file extension. The parsed value is `unknown`; use `fileSchema` when the
 * parsed content should also be decoded with a Schema.
 *
 * **Example** (Parsing file content)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const config = Argument.fileParse("config", { format: "json" })
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const fileParse = (name, options) => Param.fileParse(Param.argumentKind, name, options);
/**
 * Creates a positional argument that reads and validates file content using a schema.
 *
 * **Example** (Validating file content with a schema)
 *
 * ```ts
 * import { Schema } from "effect"
 * import { Argument } from "effect/unstable/cli"
 *
 * const ConfigSchema = Schema.Struct({
 *   port: Schema.Number,
 *   host: Schema.String
 * })
 *
 * const config = Argument.fileSchema("config", ConfigSchema)
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const fileSchema = (name, schema, options) => Param.fileSchema(Param.argumentKind, name, schema, options);
/**
 * Creates an empty sentinel argument that always fails to parse.
 *
 * **Example** (Creating a sentinel argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * // Used as a placeholder or default in combinators
 * const noArg = Argument.none
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const none = /*#__PURE__*/Param.none(Param.argumentKind);
// -------------------------------------------------------------------------------------
// combinators
// -------------------------------------------------------------------------------------
/**
 * Makes a positional argument optional.
 *
 * **Example** (Making an argument optional)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const optionalVersion = Argument.string("version").pipe(Argument.optional)
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const optional = arg => Param.optional(arg);
/**
 * Adds a description to a positional argument.
 *
 * **Example** (Adding an argument description)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const filename = Argument.string("filename").pipe(
 *   Argument.withDescription("The input file to process")
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withDescription = /*#__PURE__*/dual(2, (self, description) => Param.withDescription(self, description));
/**
 * Provides a default value for a positional argument.
 *
 * **Example** (Providing a default value)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const port = Argument.integer("port").pipe(Argument.withDefault(8080))
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withDefault = Param.withDefault;
/**
 * Adds a fallback config that is loaded when a required argument is missing.
 *
 * **Example** (Loading a fallback config)
 *
 * ```ts
 * import { Config } from "effect"
 * import { Argument } from "effect/unstable/cli"
 *
 * const repository = Argument.string("repository").pipe(
 *   Argument.withFallbackConfig(Config.string("REPOSITORY"))
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withFallbackConfig = /*#__PURE__*/dual(2, (self, config) => Param.withFallbackConfig(self, config));
/**
 * Adds a fallback prompt that is shown when a required argument is missing.
 *
 * **Example** (Showing a fallback prompt)
 *
 * ```ts
 * import { Argument, Prompt } from "effect/unstable/cli"
 *
 * const filename = Argument.string("filename").pipe(
 *   Argument.withFallbackPrompt(Prompt.text({ message: "Filename" }))
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withFallbackPrompt = /*#__PURE__*/dual(2, (self, prompt) => Param.withFallbackPrompt(self, prompt));
/**
 * Creates a variadic positional argument that accepts multiple values.
 *
 * **Example** (Accepting multiple values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * // Accept any number of files
 * const anyFiles = Argument.string("files").pipe(Argument.variadic)
 *
 * // Accept at least 1 file
 * const atLeastOneFile = Argument.string("files").pipe(
 *   Argument.variadic({ min: 1 })
 * )
 *
 * // Accept between 1 and 5 files
 * const limitedFiles = Argument.string("files").pipe(
 *   Argument.variadic({ min: 1, max: 5 })
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const variadic = /*#__PURE__*/dual(args => Param.isParam(args[0]), (self, options) => Param.variadic(self, options));
/**
 * Transforms the parsed value of a positional argument.
 *
 * **Example** (Mapping parsed values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const port = Argument.integer("port").pipe(
 *   Argument.map((p) => ({ port: p, url: `http://localhost:${p}` }))
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const map = /*#__PURE__*/dual(2, (self, f) => Param.map(self, f));
/**
 * Transforms the parsed value of a positional argument using an effectful function.
 *
 * **Example** (Validating values effectfully)
 *
 * ```ts
 * import { Effect } from "effect"
 * import { Argument, CliError } from "effect/unstable/cli"
 *
 * const files = Argument.string("files").pipe(
 *   Argument.mapEffect((file) =>
 *     file.endsWith(".txt")
 *       ? Effect.succeed(file)
 *       : Effect.fail(
 *         new CliError.UserError({
 *           cause: new Error("Only .txt files allowed")
 *         })
 *       )
 *   )
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const mapEffect = /*#__PURE__*/dual(2, (self, f) => Param.mapEffect(self, f));
/**
 * Transforms the parsed value of a positional argument using a function that may throw.
 *
 * **Example** (Mapping values that may throw)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const json = Argument.string("data").pipe(
 *   Argument.mapTryCatch(
 *     (str) => JSON.parse(str),
 *     (error) =>
 *       `Invalid JSON: ${error instanceof Error ? error.message : String(error)}`
 *   )
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const mapTryCatch = /*#__PURE__*/dual(3, (self, f, onError) => Param.mapTryCatch(self, f, onError));
/**
 * Creates a variadic argument that requires at least n values.
 *
 * **Example** (Requiring a minimum number of values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const files = Argument.string("files").pipe(Argument.atLeast(1))
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const atLeast = /*#__PURE__*/dual(2, (self, min) => Param.atLeast(self, min));
/**
 * Creates a variadic argument that accepts at most n values.
 *
 * **Example** (Limiting the maximum number of values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const files = Argument.string("files").pipe(Argument.atMost(5))
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const atMost = /*#__PURE__*/dual(2, (self, max) => Param.atMost(self, max));
/**
 * Creates a variadic argument that accepts between min and max values.
 *
 * **Example** (Requiring a range of values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const files = Argument.string("files").pipe(Argument.between(1, 5))
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const between = /*#__PURE__*/dual(3, (self, min, max) => Param.between(self, min, max));
/**
 * Validates parsed values against a Schema.
 *
 * **Example** (Validating parsed values with a schema)
 *
 * ```ts
 * import { Schema } from "effect"
 * import { Argument } from "effect/unstable/cli"
 *
 * const input = Argument.string("input").pipe(
 *   Argument.withSchema(Schema.NonEmptyString)
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const withSchema = /*#__PURE__*/dual(2, (self, schema) => Param.withSchema(self, schema));
/**
 * Creates a positional choice argument with custom value mapping.
 *
 * **Example** (Mapping choices to values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const logLevel = Argument.choiceWithValue("level", [
 *   ["debug", 0],
 *   ["info", 1],
 *   ["warn", 2],
 *   ["error", 3]
 * ])
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export const choiceWithValue = (name, choices) => Param.choiceWithValue(Param.argumentKind, name, choices);
// -------------------------------------------------------------------------------------
// metadata
// -------------------------------------------------------------------------------------
/**
 * Sets a custom metavar (placeholder name) for the argument in help documentation.
 *
 * **Details**
 *
 * The metavar is displayed in usage text to indicate what value the user should provide.
 * For example, `<FILE>` shows `FILE` as the metavar.
 *
 * **Example** (Setting a metavar)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const port = Argument.integer("port").pipe(
 *   Argument.withMetavar("PORT")
 * )
 * ```
 *
 * @category metadata
 * @since 4.0.0
 */
export const withMetavar = /*#__PURE__*/dual(2, (self, metavar) => Param.withMetavar(self, metavar));
/**
 * Filters parsed values, failing with a custom error message if the predicate returns false.
 *
 * **Example** (Filtering parsed values)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const positiveInt = Argument.integer("count").pipe(
 *   Argument.filter(
 *     (n) => n > 0,
 *     (n) => `Expected positive integer, got ${n}`
 *   )
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const filter = /*#__PURE__*/dual(3, (self, predicate, onFalse) => Param.filter(self, predicate, onFalse));
/**
 * Filters and transforms parsed values, failing with a custom error message
 * if the filter function returns None.
 *
 * **Example** (Filtering and mapping parsed values)
 *
 * ```ts
 * import { Option } from "effect"
 * import { Argument } from "effect/unstable/cli"
 *
 * const positiveInt = Argument.integer("count").pipe(
 *   Argument.filterMap(
 *     (n) => n > 0 ? Option.some(n) : Option.none(),
 *     (n) => `Expected positive integer, got ${n}`
 *   )
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const filterMap = /*#__PURE__*/dual(3, (self, f, onNone) => Param.filterMap(self, f, onNone));
/**
 * Provides a fallback argument to use if this argument fails to parse.
 *
 * **Example** (Providing a fallback argument)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const value = Argument.integer("value").pipe(
 *   Argument.orElse(() => Argument.string("value"))
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const orElse = /*#__PURE__*/dual(2, (self, that) => Param.orElse(self, that));
/**
 * Provides a fallback argument, wrapping results in Result to distinguish which succeeded.
 *
 * **Example** (Returning which fallback succeeded)
 *
 * ```ts
 * import { Argument } from "effect/unstable/cli"
 *
 * const source = Argument.file("source").pipe(
 *   Argument.orElseResult(() => Argument.string("url"))
 * )
 * // Returns Result<string, string>
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export const orElseResult = /*#__PURE__*/dual(2, (self, that) => Param.orElseResult(self, that));
//# sourceMappingURL=Argument.js.map