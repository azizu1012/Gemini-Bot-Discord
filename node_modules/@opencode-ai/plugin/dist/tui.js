import { createBindingLookup as createKeymapBindingLookup, } from "@opentui/keymap/extras";
export { stringifyKeySequence, stringifyKeyStroke } from "@opentui/keymap";
export { formatCommandBindings, formatKeySequence } from "@opentui/keymap/extras";
export function createBindingLookup(config, options) {
    return createKeymapBindingLookup(config ?? {}, options);
}
export const TuiAttentionSoundNames = ["default", "question", "permission", "error", "done", "subagent_done"];
