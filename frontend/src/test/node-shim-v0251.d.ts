// 시험 전용(v0.25.1 F1a): 정적 확인·색 일치 시험이 쓰는 node 선언 보충 — node-shim.d.ts 와 병합된다.
declare module "node:fs" {
  export function readdirSync(path: string): string[];
  export function statSync(path: string): { isDirectory(): boolean };
}
declare module "node:crypto" {
  export function createHash(alg: string): { update(b: Uint8Array): { digest(enc: "hex"): string } };
}
