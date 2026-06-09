/**
 * The `HelpDoc` module defines the structured documentation model used by the
 * unstable CLI package to describe command help. A `HelpDoc` value captures the
 * user-facing parts of a command, including its description, usage string,
 * positional arguments, flags, global flags, subcommands, and examples.
 *
 * **Common tasks**
 *
 * - Build help data from command definitions before rendering it
 * - Pass command documentation to `CliOutput.Formatter` implementations
 * - Represent custom help output formats without changing command parsing
 * - Group subcommands and distinguish local flags from global flags
 *
 * **Gotchas**
 *
 * - `HelpDoc` is format-agnostic; layout, ANSI styling, and table alignment are
 *   handled by the output formatter
 * - Optional argument and flag descriptions use `Option.Option<string>`, while
 *   optional sections are omitted when they have no entries
 * - Long names, aliases, and descriptions may require formatter-specific width
 *   handling when rendering terminal help
 *
 * @since 4.0.0
 */
export {};
//# sourceMappingURL=HelpDoc.js.map