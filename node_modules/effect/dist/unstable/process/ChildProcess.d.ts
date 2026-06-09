import type * as Duration from "../../Duration.ts";
import type * as Effect from "../../Effect.ts";
import type * as PlatformError from "../../PlatformError.ts";
import type * as Scope from "../../Scope.ts";
import type * as Sink from "../../Sink.ts";
import type * as Stream from "../../Stream.ts";
import { type ChildProcessHandle, ChildProcessSpawner } from "./ChildProcessSpawner.ts";
/**
 * A command that can be built using `make`, combined using `pipeTo`, and executed using `exec` or `spawn`.
 *
 * @category models
 * @since 4.0.0
 */
export type Command = StandardCommand | PipedCommand;
/**
 * A standard command with pre-parsed command and arguments.
 *
 * @category models
 * @since 4.0.0
 */
export interface StandardCommand extends Effect.Effect<ChildProcessHandle, PlatformError.PlatformError, ChildProcessSpawner | Scope.Scope> {
    readonly _tag: "StandardCommand";
    readonly command: string;
    readonly args: ReadonlyArray<string>;
    readonly options: CommandOptions;
}
/**
 * A pipeline of commands where the output of one is piped to the input of the
 * next.
 *
 * @category models
 * @since 4.0.0
 */
export interface PipedCommand extends Effect.Effect<ChildProcessHandle, PlatformError.PlatformError, ChildProcessSpawner | Scope.Scope> {
    readonly _tag: "PipedCommand";
    readonly left: Command;
    readonly right: Command;
    readonly options: PipeOptions;
}
/**
 * Specifies which stream to pipe from the source subprocess.
 *
 * **Details**
 *
 * - `"stdout"`: Pipe stdout from the source (default)
 * - `"stderr"`: Pipe stderr from the source
 * - `"all"`: Pipe both stdout and stderr interleaved
 * - `` `fd${number}` ``: Pipe from a custom file descriptor (e.g., `"fd3"`)
 *
 * @category models
 * @since 4.0.0
 */
export type PipeFromOption = "stdout" | "stderr" | "all" | `fd${number}`;
/**
 * Specifies which input to pipe to on the destination subprocess.
 *
 * **Details**
 *
 * - `"stdin"`: Pipe to stdin of the destination (default)
 * - `` `fd${number}` ``: Pipe to a custom file descriptor (e.g., `"fd3"`)
 *
 * @category models
 * @since 4.0.0
 */
export type PipeToOption = "stdin" | `fd${number}`;
/**
 * Options for controlling how commands are piped together.
 *
 * **Example** (Piping stderr between commands)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * // Pipe stderr instead of stdout
 * const pipeline = ChildProcess.make`my-program`.pipe(
 *   ChildProcess.pipeTo(ChildProcess.make`grep error`, { from: "stderr" })
 * )
 * ```
 *
 * @category options
 * @since 4.0.0
 */
export interface PipeOptions {
    /**
     * Which stream to pipe from the source subprocess.
     *
     * **Details**
     *
     * - `"stdout"` (default): Pipe stdout from the source
     * - `"stderr"`: Pipe stderr from the source
     * - `"all"`: Pipe both stdout and stderr interleaved
     * - `"fd3"`, `"fd4"`, etc.: Pipe from a custom file descriptor
     */
    readonly from?: PipeFromOption | undefined;
    /**
     * Which input to pipe to on the destination subprocess.
     *
     * **Details**
     *
     * - `"stdin"` (default): Pipe to stdin of the destination
     * - `"fd3"`, `"fd4"`, etc.: Pipe to a custom file descriptor
     */
    readonly to?: PipeToOption | undefined;
}
/**
 * Input type for child process stdin.
 *
 * @category models
 * @since 4.0.0
 */
export type CommandInput = "pipe" | "inherit" | "ignore" | "overlapped" | Stream.Stream<Uint8Array, PlatformError.PlatformError>;
/**
 * Output type for child process stdout/stderr.
 *
 * @category models
 * @since 4.0.0
 */
export type CommandOutput = "pipe" | "inherit" | "ignore" | "overlapped" | Sink.Sink<Uint8Array, Uint8Array, never, PlatformError.PlatformError>;
/**
 * A signal that can be sent to a child process.
 *
 * @category models
 * @since 4.0.0
 */
export type Signal = "SIGABRT" | "SIGALRM" | "SIGBUS" | "SIGCHLD" | "SIGCONT" | "SIGFPE" | "SIGHUP" | "SIGILL" | "SIGINT" | "SIGIO" | "SIGIOT" | "SIGKILL" | "SIGPIPE" | "SIGPOLL" | "SIGPROF" | "SIGPWR" | "SIGQUIT" | "SIGSEGV" | "SIGSTKFLT" | "SIGSTOP" | "SIGSYS" | "SIGTERM" | "SIGTRAP" | "SIGTSTP" | "SIGTTIN" | "SIGTTOU" | "SIGUNUSED" | "SIGURG" | "SIGUSR1" | "SIGUSR2" | "SIGVTALRM" | "SIGWINCH" | "SIGXCPU" | "SIGXFSZ" | "SIGBREAK" | "SIGLOST" | "SIGINFO";
/**
 * The encoding format to use for binary data.
 *
 * @category models
 * @since 4.0.0
 */
export type Encoding = "ascii" | "utf8" | "utf-8" | "utf16le" | "utf-16le" | "ucs2" | "ucs-2" | "base64" | "base64url" | "latin1" | "binary" | "hex";
/**
 * Options that can be used to control how a child process is terminated.
 *
 * @category options
 * @since 4.0.0
 */
export interface KillOptions {
    /**
     * The default signal used to terminate the child process. Defaults to `"SIGTERM"`.
     */
    readonly killSignal?: Signal | undefined;
    /**
     * The duration of time to wait after the child process has been terminated
     * before forcefully killing the child process by sending it the `"SIGKILL"`
     * signal. Defaults to `undefined`, which means that no timeout will be
     * enforced by default.
     */
    readonly forceKillAfter?: Duration.Input | undefined;
}
/**
 * Configuration for the child process standard input stream.
 *
 * @category models
 * @since 4.0.0
 */
export interface StdinConfig {
    /**
     * The configuration for the standard input stream of the child process.
     *
     * **Details**
     *
     * Can be a string indicating how the operating system should configure the
     * pipe established between the child process `stdin` and the parent process.
     *
     * Can also be a `Stream`, which will pipe all elements produced into the
     * `stdin` of the child process.
     *
     * Defaults to "pipe".
     */
    readonly stream: CommandInput;
    /**
     * Whether or not the child process `stdin` should be closed after the input
     * stream is finished. Defaults to `true`.
     */
    readonly endOnDone?: boolean | undefined;
    /**
     * The buffer encoding to use to decode string chunks. Defaults to `utf-8`.
     */
    readonly encoding?: Encoding | undefined;
}
/**
 * Configuration for the child process standard output stream.
 *
 * @category models
 * @since 4.0.0
 */
export interface StdoutConfig {
    /**
     * The configuration for the standard output stream of the child process.
     *
     * **Details**
     *
     * Can be a string indicating how the operating system should configure the
     * pipe established between the child process `stdout` and the parent process.
     *
     * A `Sink` can also be passed, which will receive all elements produced by
     * the `stdout` of the child process.
     *
     * Defaults to "pipe".
     */
    readonly stream?: CommandOutput | undefined;
}
/**
 * Configuration for the child process standard error stream.
 *
 * @category models
 * @since 4.0.0
 */
export interface StderrConfig {
    /**
     * The configuration for the standard error stream of the child process.
     *
     * **Details**
     *
     * Can be a string indicating how the operating system should configure the
     * pipe established between the child process `stderr` and the parent process.
     *
     * A `Sink` can also be passed, which will receive all elements produced by
     * the `stderr` of the child process.
     *
     * Defaults to "pipe".
     */
    readonly stream?: CommandOutput | undefined;
}
/**
 * Configuration for additional file descriptors to expose to the child process.
 *
 * @category models
 * @since 4.0.0
 */
export type AdditionalFdConfig = {
    /**
     * The direction of data flow for this file descriptor.
     * - "input": Data flows from parent to child (writable by parent)
     * - "output": Data flows from child to parent (readable by parent)
     */
    readonly type: "input";
    /**
     * For input file descriptors, an optional stream to pipe into the file
     * descriptor..
     */
    readonly stream?: Stream.Stream<Uint8Array, PlatformError.PlatformError> | undefined;
} | {
    /**
     * The direction of data flow for this file descriptor.
     * - "input": Data flows from parent to child (writable by parent)
     * - "output": Data flows from child to parent (readable by parent)
     */
    readonly type: "output";
    /**
     * For output file descriptors, an optional sink which receives data from
     * the file descriptor.
     */
    readonly sink?: Sink.Sink<Uint8Array, Uint8Array, never, PlatformError.PlatformError> | undefined;
};
/**
 * Options for command execution.
 *
 * @category options
 * @since 4.0.0
 */
export interface CommandOptions extends KillOptions {
    /**
     * The current working directory of the child process.
     */
    readonly cwd?: string | undefined;
    /**
     * The environment of the child process.
     *
     * **Details**
     *
     * If `extendEnv` is set to `true`, the value of `env` will be merged with
     * the value of `globalThis.process.env`, prioritizing the values in `env`
     * when conflicts exist.
     */
    readonly env?: Record<string, string | undefined> | undefined;
    /**
     * If set to `true`, the child process uses both the values in `env` as well
     * as the values in `globalThis.process.env`, prioritizing the values in `env`
     * when conflicts exist.
     *
     * **Details**
     *
     * If set to `false`, only the value of `env` is used.
     */
    readonly extendEnv?: boolean | undefined;
    /**
     * If set to `true`, runs the command inside of a shell, defaulting to `/bin/sh`
     * on UNIX systems and `cmd.exe` on Windows.
     *
     * **Details**
     *
     * Can also be set to a string representing the absolute path to a shell to
     * use on the system.
     *
     * **Gotchas**
     *
     * It is generally disadvised to use this option.
     */
    readonly shell?: boolean | string | undefined;
    /**
     * If set to `true`, the child process will run independently of the parent
     * process.
     *
     * **Details**
     *
     * The specific behavior of this option depends upon the platform. For
     * example, the NodeJS documentation outlines the differences between Windows
     * and non-Windows platforms.
     *
     * See https://nodejs.org/api/child_process.html#child_process_options_detached.
     *
     * Defaults to `true` on non-Windows platforms and `false` on Windows platforms.
     */
    readonly detached?: boolean | undefined;
    /**
     * Configuration options for the standard input stream for the child process.
     */
    readonly stdin?: CommandInput | StdinConfig | undefined;
    /**
     * Configuration options for the standard output stream for the child process.
     */
    readonly stdout?: CommandOutput | StdoutConfig | undefined;
    /**
     * Configuration options for the standard error stream for the child process.
     */
    readonly stderr?: CommandOutput | StderrConfig | undefined;
    /**
     * Additional file descriptors to expose to the child process beyond `stdin` /
     * `stdout` / `stderr`.
     *
     * **Details**
     *
     * Keys must be in the format `"fd3"`, `"fd4"`, etc. with a file descriptor
     * index >= 3.
     *
     * The file descriptor index is determined by the numeric suffix (i.e. `fd3`
     * has a file descriptor index of 3).
     *
     * **Example** (Configuring additional file descriptors)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Output fd3 - read data from child
     * const cmd1 = ChildProcess.make("my-program", [], {
     *   additionalFds: {
     *     fd3: { type: "output" }
     *   }
     * })
     *
     * // Input fd3 - write data to child
     * const cmd2 = ChildProcess.make("my-program", [], {
     *   additionalFds: {
     *     fd3: { type: "input" }
     *   }
     * })
     * ```
     */
    readonly additionalFds?: Record<`fd${number}`, AdditionalFdConfig> | undefined;
}
/**
 * Valid template expression item types.
 *
 * @category models
 * @since 4.0.0
 */
export type TemplateExpressionItem = string | number | boolean;
/**
 * Template expression type for interpolated values.
 *
 * @category models
 * @since 4.0.0
 */
export type TemplateExpression = TemplateExpressionItem | ReadonlyArray<TemplateExpressionItem>;
/**
 * Checks whether a value is a `Command`.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isCommand: (u: unknown) => u is Command;
/**
 * Checks whether a command is a `StandardCommand`.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isStandardCommand: (command: Command) => command is StandardCommand;
/**
 * Checks whether a command is a `PipedCommand`.
 *
 * @category guards
 * @since 4.0.0
 */
export declare const isPipedCommand: (command: Command) => command is PipedCommand;
/**
 * Create a command from a template literal, options + template, or array form.
 *
 * **Details**
 *
 * This function supports three calling conventions:
 * 1. Template literal: `make\`npm run build\``
 * 2. Options + template literal: `make({ cwd: "/app" })\`npm run build\``
 * 3. Array form: `make("npm", ["run", "build"], options?)`
 *
 * Template literals are not parsed until execution time, allowing parsing
 * errors to flow through Effect's error channel.
 *
 * **Example** (Creating commands)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * // Template literal form
 * const cmd1 = ChildProcess.make`echo "hello"`
 *
 * // With options
 * const cmd2 = ChildProcess.make({ cwd: "/tmp" })`ls -la`
 *
 * // Array form
 * const cmd3 = ChildProcess.make("git", ["status"])
 * ```
 *
 * @category constructors
 * @since 4.0.0
 */
export declare const make: {
    /**
     * Create a command from a template literal, options + template, or array form.
     *
     * **Details**
     *
     * This function supports three calling conventions:
     * 1. Template literal: `make\`npm run build\``
     * 2. Options + template literal: `make({ cwd: "/app" })\`npm run build\``
     * 3. Array form: `make("npm", ["run", "build"], options?)`
     *
     * Template literals are not parsed until execution time, allowing parsing
     * errors to flow through Effect's error channel.
     *
     * **Example** (Creating commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Template literal form
     * const cmd1 = ChildProcess.make`echo "hello"`
     *
     * // With options
     * const cmd2 = ChildProcess.make({ cwd: "/tmp" })`ls -la`
     *
     * // Array form
     * const cmd3 = ChildProcess.make("git", ["status"])
     * ```
     *
     * @category constructors
     * @since 4.0.0
     */
    (command: string, options?: CommandOptions): StandardCommand;
    /**
     * Create a command from a template literal, options + template, or array form.
     *
     * **Details**
     *
     * This function supports three calling conventions:
     * 1. Template literal: `make\`npm run build\``
     * 2. Options + template literal: `make({ cwd: "/app" })\`npm run build\``
     * 3. Array form: `make("npm", ["run", "build"], options?)`
     *
     * Template literals are not parsed until execution time, allowing parsing
     * errors to flow through Effect's error channel.
     *
     * **Example** (Creating commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Template literal form
     * const cmd1 = ChildProcess.make`echo "hello"`
     *
     * // With options
     * const cmd2 = ChildProcess.make({ cwd: "/tmp" })`ls -la`
     *
     * // Array form
     * const cmd3 = ChildProcess.make("git", ["status"])
     * ```
     *
     * @category constructors
     * @since 4.0.0
     */
    (command: string, args: ReadonlyArray<string>, options?: CommandOptions): StandardCommand;
    /**
     * Create a command from a template literal, options + template, or array form.
     *
     * **Details**
     *
     * This function supports three calling conventions:
     * 1. Template literal: `make\`npm run build\``
     * 2. Options + template literal: `make({ cwd: "/app" })\`npm run build\``
     * 3. Array form: `make("npm", ["run", "build"], options?)`
     *
     * Template literals are not parsed until execution time, allowing parsing
     * errors to flow through Effect's error channel.
     *
     * **Example** (Creating commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Template literal form
     * const cmd1 = ChildProcess.make`echo "hello"`
     *
     * // With options
     * const cmd2 = ChildProcess.make({ cwd: "/tmp" })`ls -la`
     *
     * // Array form
     * const cmd3 = ChildProcess.make("git", ["status"])
     * ```
     *
     * @category constructors
     * @since 4.0.0
     */
    (options: CommandOptions): (templates: TemplateStringsArray, ...expressions: ReadonlyArray<TemplateExpression>) => StandardCommand;
    /**
     * Create a command from a template literal, options + template, or array form.
     *
     * **Details**
     *
     * This function supports three calling conventions:
     * 1. Template literal: `make\`npm run build\``
     * 2. Options + template literal: `make({ cwd: "/app" })\`npm run build\``
     * 3. Array form: `make("npm", ["run", "build"], options?)`
     *
     * Template literals are not parsed until execution time, allowing parsing
     * errors to flow through Effect's error channel.
     *
     * **Example** (Creating commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Template literal form
     * const cmd1 = ChildProcess.make`echo "hello"`
     *
     * // With options
     * const cmd2 = ChildProcess.make({ cwd: "/tmp" })`ls -la`
     *
     * // Array form
     * const cmd3 = ChildProcess.make("git", ["status"])
     * ```
     *
     * @category constructors
     * @since 4.0.0
     */
    (templates: TemplateStringsArray, ...expressions: ReadonlyArray<TemplateExpression>): StandardCommand;
};
/**
 * Pipes the output of one command to the input of another.
 *
 * **Details**
 *
 * By default, pipes `stdout` from the source to `stdin` of the destination.
 * Use the `options` parameter to customize which streams are connected.
 *
 * **Example** (Piping command output)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * // Pipe stdout (default)
 * const pipeline1 = ChildProcess.make`cat file.txt`.pipe(
 *   ChildProcess.pipeTo(ChildProcess.make`grep pattern`)
 * )
 *
 * // Pipe stderr instead of stdout
 * const pipeline2 = ChildProcess.make`my-program`.pipe(
 *   ChildProcess.pipeTo(ChildProcess.make`grep error`, { from: "stderr" })
 * )
 *
 * // Pipe combined stdout and stderr
 * const pipeline3 = ChildProcess.make`my-program`.pipe(
 *   ChildProcess.pipeTo(ChildProcess.make`tee output.log`, { from: "all" })
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export declare const pipeTo: {
    /**
     * Pipes the output of one command to the input of another.
     *
     * **Details**
     *
     * By default, pipes `stdout` from the source to `stdin` of the destination.
     * Use the `options` parameter to customize which streams are connected.
     *
     * **Example** (Piping command output)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Pipe stdout (default)
     * const pipeline1 = ChildProcess.make`cat file.txt`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`grep pattern`)
     * )
     *
     * // Pipe stderr instead of stdout
     * const pipeline2 = ChildProcess.make`my-program`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`grep error`, { from: "stderr" })
     * )
     *
     * // Pipe combined stdout and stderr
     * const pipeline3 = ChildProcess.make`my-program`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`tee output.log`, { from: "all" })
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (that: Command, options?: PipeOptions): (self: Command) => PipedCommand;
    /**
     * Pipes the output of one command to the input of another.
     *
     * **Details**
     *
     * By default, pipes `stdout` from the source to `stdin` of the destination.
     * Use the `options` parameter to customize which streams are connected.
     *
     * **Example** (Piping command output)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * // Pipe stdout (default)
     * const pipeline1 = ChildProcess.make`cat file.txt`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`grep pattern`)
     * )
     *
     * // Pipe stderr instead of stdout
     * const pipeline2 = ChildProcess.make`my-program`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`grep error`, { from: "stderr" })
     * )
     *
     * // Pipe combined stdout and stderr
     * const pipeline3 = ChildProcess.make`my-program`.pipe(
     *   ChildProcess.pipeTo(ChildProcess.make`tee output.log`, { from: "all" })
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (self: Command, that: Command, options?: PipeOptions): PipedCommand;
};
/**
 * Prepends another command to a command.
 *
 * **Details**
 *
 * For pipelines, only the leftmost command is prefixed.
 *
 * **Example** (Prefixing commands)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * const command = ChildProcess.make`echo "foo"`
 *
 * const prefixed = command.pipe(
 *   ChildProcess.prefix`time`
 * )
 *
 * // now prefixed will execute `time echo "foo"`
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export declare const prefix: {
    /**
     * Prepends another command to a command.
     *
     * **Details**
     *
     * For pipelines, only the leftmost command is prefixed.
     *
     * **Example** (Prefixing commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const command = ChildProcess.make`echo "foo"`
     *
     * const prefixed = command.pipe(
     *   ChildProcess.prefix`time`
     * )
     *
     * // now prefixed will execute `time echo "foo"`
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (command: string, args?: ReadonlyArray<string>): (self: Command) => Command;
    /**
     * Prepends another command to a command.
     *
     * **Details**
     *
     * For pipelines, only the leftmost command is prefixed.
     *
     * **Example** (Prefixing commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const command = ChildProcess.make`echo "foo"`
     *
     * const prefixed = command.pipe(
     *   ChildProcess.prefix`time`
     * )
     *
     * // now prefixed will execute `time echo "foo"`
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (templates: TemplateStringsArray, ...expressions: ReadonlyArray<TemplateExpression>): (self: Command) => Command;
    /**
     * Prepends another command to a command.
     *
     * **Details**
     *
     * For pipelines, only the leftmost command is prefixed.
     *
     * **Example** (Prefixing commands)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const command = ChildProcess.make`echo "foo"`
     *
     * const prefixed = command.pipe(
     *   ChildProcess.prefix`time`
     * )
     *
     * // now prefixed will execute `time echo "foo"`
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (self: Command, command: string, args?: ReadonlyArray<string>): Command;
};
/**
 * Sets the current working directory for a command.
 *
 * **Details**
 *
 * For pipelines, applies to each command in the pipeline.
 *
 * **Example** (Setting command working directories)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * const cmd = ChildProcess.make`ls -la`.pipe(
 *   ChildProcess.setCwd("/tmp")
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export declare const setCwd: {
    /**
     * Sets the current working directory for a command.
     *
     * **Details**
     *
     * For pipelines, applies to each command in the pipeline.
     *
     * **Example** (Setting command working directories)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const cmd = ChildProcess.make`ls -la`.pipe(
     *   ChildProcess.setCwd("/tmp")
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (cwd: string): (self: Command) => Command;
    /**
     * Sets the current working directory for a command.
     *
     * **Details**
     *
     * For pipelines, applies to each command in the pipeline.
     *
     * **Example** (Setting command working directories)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const cmd = ChildProcess.make`ls -la`.pipe(
     *   ChildProcess.setCwd("/tmp")
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (self: Command, cwd: string): Command;
};
/**
 * Adds environment variables to a command, merging them with any existing
 * command environment and overriding duplicate keys.
 *
 * **Details**
 *
 * For pipelines, applies to each command in the pipeline.
 *
 * **Example** (Setting command environment variables)
 *
 * ```ts
 * import { ChildProcess } from "effect/unstable/process"
 *
 * const cmd = ChildProcess.make`node script.js`.pipe(
 *   ChildProcess.setEnv({ NODE_ENV: "test" })
 * )
 * ```
 *
 * @category combinators
 * @since 4.0.0
 */
export declare const setEnv: {
    /**
     * Adds environment variables to a command, merging them with any existing
     * command environment and overriding duplicate keys.
     *
     * **Details**
     *
     * For pipelines, applies to each command in the pipeline.
     *
     * **Example** (Setting command environment variables)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const cmd = ChildProcess.make`node script.js`.pipe(
     *   ChildProcess.setEnv({ NODE_ENV: "test" })
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (env: Record<string, string>): (self: Command) => Command;
    /**
     * Adds environment variables to a command, merging them with any existing
     * command environment and overriding duplicate keys.
     *
     * **Details**
     *
     * For pipelines, applies to each command in the pipeline.
     *
     * **Example** (Setting command environment variables)
     *
     * ```ts
     * import { ChildProcess } from "effect/unstable/process"
     *
     * const cmd = ChildProcess.make`node script.js`.pipe(
     *   ChildProcess.setEnv({ NODE_ENV: "test" })
     * )
     * ```
     *
     * @category combinators
     * @since 4.0.0
     */
    (self: Command, env: Record<string, string>): Command;
};
/**
 * Parses an fd name like "fd3" to its numeric index.
 * Returns undefined if the name is invalid.
 *
 * @category converting
 * @since 4.0.0
 */
export declare const parseFdName: (name: string) => number | undefined;
/**
 * Create an fd name from its numeric index.
 *
 * @category converting
 * @since 4.0.0
 */
export declare const fdName: (fd: number) => string;
//# sourceMappingURL=ChildProcess.d.ts.map