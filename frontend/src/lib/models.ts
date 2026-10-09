/**
 * Short, user-facing names for the switchable AI networks.
 *
 * The ids come from the backend whitelist (`app/ai/models.py`); these are the one
 * or two words the operator actually reads in the interface.
 */

export const MODEL_NAMES: Record<string, string> = {
  detection: "Detection",
  pose: "Pose",
};

export function shortModelName(id: string | null): string | null {
  if (id === null) return null;
  return MODEL_NAMES[id] ?? id;
}