import * as Cause from "./Cause.js";
import * as Effect from "./Effect.js";
import * as Exit from "./Exit.js";
/**
 * Converts a `Take` into a `Pull`, succeeding with value batches, failing with
 * failure exits, and translating successful exits into pull completion.
 *
 * **When to use**
 *
 * Use to interpret a stored or transferred `Take` as a `Pull` step while
 * preserving emitted batches, ordinary failures, and completion values.
 *
 * @category converting
 * @since 4.0.0
 */
export const toPull = take => Exit.isExit(take) ? Exit.isSuccess(take) ? Cause.done(take.value) : take : Effect.succeed(take);
//# sourceMappingURL=Take.js.map