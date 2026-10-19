// openapi 스키마(docs/contracts/openapi_p1b.json components.schemas) ↔ src/api/types.ts 인터페이스 대조.
// 규칙: 스키마마다 같은 이름의 interface(또는 type 별칭 객체)가 있어야 하고,
//   - 속성 키 집합이 같을 것(TS 에만/스키마에만 있는 키 = 오류),
//   - 스키마 required 키는 TS 에서 선택(?)이 아닐 것,
//   - 스키마가 null 을 허용하면(anyOf null) TS 타입에 null 이 있을 것, 허용하지 않으면 null 이 없을 것.
// 사용: npm run check:api [-- <openapi.json> <types.ts>]
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const openapiPath = process.argv[2] ?? path.resolve(root, "..", "docs", "contracts", "openapi_p1b.json");
const typesPath = process.argv[3] ?? path.resolve(root, "src", "api", "types.ts");

const spec = JSON.parse(readFileSync(openapiPath, "utf8"));
const schemas = spec.components?.schemas ?? {};
const src = ts.createSourceFile(typesPath, readFileSync(typesPath, "utf8"), ts.ScriptTarget.Latest, true);

/** 이름 → {members: Map<key, {optional, nullable}>} (interface + extends 1단계, type 리터럴) */
const decls = new Map();
function membersOf(nodes) {
  const out = new Map();
  for (const m of nodes) {
    if (!ts.isPropertySignature(m) || !m.name) continue;
    const key = m.name.getText(src).replace(/^["']|["']$/g, "");
    const t = m.type ? m.type.getText(src) : "unknown";
    out.set(key, { optional: !!m.questionToken, nullable: topNullable(m.type), unknown: /^unknown$/.test(t.trim()) });
  }
  return out;
}
/** 최상위 유니온에 null 이 있는지(중첩 객체 안의 null 은 무시) */
function topNullable(t) {
  if (!t) return false;
  if (ts.isParenthesizedTypeNode(t)) return topNullable(t.type);
  if (ts.isLiteralTypeNode(t)) return t.literal.kind === ts.SyntaxKind.NullKeyword;
  if (ts.isUnionTypeNode(t)) return t.types.some(topNullable);
  return false;
}
const pending = [];
ts.forEachChild(src, (n) => {
  if (ts.isInterfaceDeclaration(n)) {
    const bases = (n.heritageClauses ?? []).flatMap((h) => h.types.map((t) => t.expression.getText(src)));
    pending.push({ name: n.name.text, members: membersOf(n.members), bases });
  } else if (ts.isTypeAliasDeclaration(n)) {
    if (ts.isTypeLiteralNode(n.type)) pending.push({ name: n.name.text, members: membersOf(n.type.members), bases: [] });
    else if (/^Record<string,\s*never>$/.test(n.type.getText(src))) pending.push({ name: n.name.text, members: new Map(), bases: [] });
  }
});
for (const p of pending) decls.set(p.name, p);
function resolved(name, seen = new Set()) {
  const d = decls.get(name);
  if (!d || seen.has(name)) return null;
  seen.add(name);
  const m = new Map();
  for (const b of d.bases) for (const [k, v] of resolved(b, seen) ?? []) m.set(k, v);
  for (const [k, v] of d.members) m.set(k, v);
  return m;
}

function schemaNullable(s) {
  if (!s) return false;
  if (s.type === "null" || s.nullable === true) return true;
  return (s.anyOf ?? s.oneOf ?? []).some((x) => x.type === "null");
}

const errors = [];
let checked = 0;
for (const [name, schema] of Object.entries(schemas)) {
  const ms = resolved(name);
  if (!ms) {
    errors.push(`${name}: types.ts 에 같은 이름의 interface 가 없습니다`);
    continue;
  }
  checked += 1;
  const props = schema.properties ?? {};
  const req = new Set(schema.required ?? []);
  for (const [k, ps] of Object.entries(props)) {
    const m = ms.get(k);
    if (!m) {
      errors.push(`${name}.${k}: types.ts 에 없음`);
      continue;
    }
    if (req.has(k) && m.optional) errors.push(`${name}.${k}: 스키마 필수인데 TS 에서 선택(?)`);
    const sn = schemaNullable(ps);
    if (!m.unknown && sn !== m.nullable)
      errors.push(`${name}.${k}: null 허용 불일치 (스키마 ${sn ? "null 허용" : "null 불가"}, TS ${m.nullable ? "null 포함" : "null 없음"})`);
  }
  for (const k of ms.keys()) if (!(k in props)) errors.push(`${name}.${k}: 스키마에 없는 키(TS 에만 있음)`);
}

// 경로: types.ts 와 별개로 endpoints.ts 가 쓰는 경로가 openapi 에 있는지
const epPath = path.resolve(path.dirname(typesPath), "endpoints.ts");
try {
  const ep = readFileSync(epPath, "utf8");
  const prefix = "/esl/api";
  const known = Object.keys(spec.paths ?? {}).map((p) => new RegExp("^" + p.replace(/\{[^}]+\}/g, "[^/]+") + "$"));
  const used = [...ep.matchAll(/request<[^>]*>\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*[`"]([^`"]+)[`"]/g)].map((m) => [m[1], m[2]]);
  const dl = [...ep.matchAll(/\$\{API_PREFIX\}(\/[^`]+)`/g)].map((m) => ["GET", m[1]]);
  for (const [method, p] of [...used, ...dl]) {
    const concrete = prefix + p.replace(/\$\{[^}]+\}/g, "x");
    const hit = Object.entries(spec.paths).find(([sp]) => known[Object.keys(spec.paths).indexOf(sp)].test(concrete));
    if (!hit) errors.push(`endpoints.ts ${method} ${p}: openapi 에 없는 경로`);
    else if (!hit[1][method.toLowerCase()]) errors.push(`endpoints.ts ${method} ${p}: openapi 에 없는 메서드`);
  }
} catch (e) {
  errors.push(`endpoints.ts 를 읽을 수 없음: ${e.message}`);
}

if (errors.length) {
  console.error(`check:api 실패 (${errors.length}건)\n` + errors.map((e) => "  - " + e).join("\n"));
  process.exit(1);
}
console.log(`check:api 통과: 스키마 ${checked}개 = types.ts, endpoints.ts 경로 모두 openapi 에 있음`);
