// Writes a Brotli variant (`<name>.br`) next to each built script, style and SVG under `<outDir>/assets`,
// and returns the names it wrote (AGH-615, AC-8, AC-17).
export function compressAssets(outDir: string): Promise<string[]> {
  throw new Error(`compressAssets is not implemented yet (${outDir})`);
}
