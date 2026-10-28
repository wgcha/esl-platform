// 시험 전용: @types/node 없이 fixture 파일을 읽기 위한 최소 선언(vitest 는 node 에서 실행됨).
declare module "node:fs" {
  export function readFileSync(path: string): Uint8Array;
  export function readFileSync(path: string, encoding: "utf8"): string;
}
declare module "node:path" {
  const path: { resolve(...p: string[]): string; join(...p: string[]): string };
  export default path;
}
declare const __dirname: string;
