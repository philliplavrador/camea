/** Join class names, dropping falsy parts. The one utility the primitives share. */
export type ClassArg = string | false | null | undefined;

export function cx(...parts: ClassArg[]): string {
  return parts.filter(Boolean).join(' ');
}
