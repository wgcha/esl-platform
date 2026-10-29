// openapi 스키마(docs/contracts/openapi_p1b.json components.schemas) ↔ src/api/types.ts 인터페이스 대조.
// 규칙: 스키마마다 같은 이름의 interface(또는 type 별칭 객체)가 있어야 하고,
//   - 속성 키 집합이 같을 것(TS 에만/스키마에만 있는 키 = 오류),
//   - 스키마 required 키는 TS 에서 선택(?)이 아닐 것,
//   - 스키마가 null 을 허용하면(anyOf null) TS 타입에 null 이 있을 것, 허용하지 않으면 null 이 없을 것,
//   - 속성 타입 대조: 원시(string·number·boolean, 별칭·리터럴 유니온 해석), 배열 원소 타입, 중첩 객체($ref 또는
//     인라인 properties)의 키·필수·null·타입을 재귀로(TS 가 다른 이름의 interface·인라인 객체여도 키 대조).
//     unknown·any 와 여러 타입 anyOf 는 대조하지 않음.
// 사용: npm run check:api [-- <openapi.json> <types.ts>]
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const openapiPath = process.argv[2] ?? path.resolve(root, "..", "docs", "contracts", "openapi_p1b.json");
const typesPath = process.argv[3] ?? path.resolve(root, "src", "api", "types.ts");

const spec = JSON.parse(readFileSync(openapiPath, "utf8"));
const schemas = spec.components?.schemas ?? {};
// P3-이력: history.ts 의 interface 도 같은 규칙으로 대조한다(types.ts 와 한 소스로 이어 붙여 파싱 — import 줄은 무시됨).
// v0.9.0: doe.ts(비드 DOE)도, v0.10.0: library.ts(라이브러리 내보내기·재검증 — ExportBatch* 등)도 — Doe* interface 는 types.ts, doe.ts 의 보조 interface 는 스키마가 없어 키 대조 대상 아님
const extraTypeFiles = ["history.ts", "doe.ts", "library.ts"].map((f) => path.resolve(path.dirname(typesPath), f)).filter((f) => f !== typesPath && existsSync(f));
const srcText = [typesPath, ...extraTypeFiles].map((f) => readFileSync(f, "utf8")).join("\n");
const src = ts.createSourceFile(typesPath, srcText, ts.ScriptTarget.Latest, true);

/** 이름 → {members: Map<key, {optional, nullable, type}>} (interface + extends, type 리터럴) */
const decls = new Map();
/** type 별칭 이름 → TypeNode (원시·유니온·참조 별칭 해석용) */
const aliases = new Map();
function membersOf(nodes) {
  const out = new Map();
  for (const m of nodes) {
    if (!ts.isPropertySignature(m) || !m.name) continue;
    const key = m.name.getText(src).replace(/^["']|["']$/g, "");
    const t = m.type ? m.type.getText(src) : "unknown";
    out.set(key, { optional: !!m.questionToken, nullable: topNullable(m.type), unknown: /^unknown$/.test(t.trim()), type: m.type });
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
    aliases.set(n.name.text, n.type);
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

// ---------------------------------------------------------------- 타입 대조(중첩 객체 키·배열 원소 타입까지)
const refName = (s) => (s && s.$ref ? s.$ref.split("/").pop() : null);
/** 스키마에서 null 분기를 뺀 것(분기가 여럿이면 anyOf 그대로) */
function schemaCore(s) {
  if (!s) return s;
  const alts = s.anyOf ?? s.oneOf;
  if (alts) {
    const rest = alts.filter((x) => x.type !== "null");
    return rest.length === 1 ? rest[0] : { anyOf: rest };
  }
  return s;
}
function unwrap(t) {
  while (t && ts.isParenthesizedTypeNode(t)) t = t.type;
  return t;
}
const isNullish = (t) =>
  (ts.isLiteralTypeNode(t) && t.literal.kind === ts.SyntaxKind.NullKeyword) || t.kind === ts.SyntaxKind.UndefinedKeyword;
/** TS 타입에서 null·undefined 를 뺀 것 */
function tsCore(t) {
  t = unwrap(t);
  if (t && ts.isUnionTypeNode(t)) {
    const rest = t.types.filter((x) => !isNullish(unwrap(x)));
    return rest.length === 1 ? tsCore(rest[0]) : rest.length ? { union: rest } : null;
  }
  return t;
}
const refText = (t) => (t && ts.isTypeReferenceNode(t) ? t.typeName.getText(src) : null);
/** 별칭(type X = Y)을 따라가 실제 TypeNode. 인터페이스·Array·Record 는 그대로 */
function deAlias(t, seen = new Set()) {
  t = unwrap(t);
  const n = refText(t);
  if (n && aliases.has(n) && !seen.has(n) && !(t.typeArguments && t.typeArguments.length)) {
    seen.add(n);
    return deAlias(aliases.get(n), seen);
  }
  return t;
}
/** 원시 종류: string | number | boolean | object | array | any | mixed */
function kindOf(t0, seen = new Set()) {
  const c = tsCore(t0);
  if (!c) return "any";
  if (c.union) {
    const ks = new Set(c.union.map((x) => kindOf(x, seen)));
    ks.delete("any");
    return ks.size === 1 ? [...ks][0] : ks.size === 0 ? "any" : "mixed";
  }
  const t = deAlias(c);
  if (t !== c) return kindOf(t, seen);
  switch (t.kind) {
    case ts.SyntaxKind.StringKeyword:
      return "string";
    case ts.SyntaxKind.NumberKeyword:
      return "number";
    case ts.SyntaxKind.BooleanKeyword:
      return "boolean";
    case ts.SyntaxKind.AnyKeyword:
    case ts.SyntaxKind.UnknownKeyword:
      return "any";
  }
  if (ts.isLiteralTypeNode(t)) {
    const k = t.literal.kind;
    if (k === ts.SyntaxKind.StringLiteral) return "string";
    if (k === ts.SyntaxKind.NumericLiteral || k === ts.SyntaxKind.PrefixUnaryExpression) return "number";
    if (k === ts.SyntaxKind.TrueKeyword || k === ts.SyntaxKind.FalseKeyword) return "boolean";
  }
  if (ts.isTemplateLiteralTypeNode(t)) return "string";
  if (ts.isArrayTypeNode(t) || ts.isTupleTypeNode(t)) return "array";
  if (ts.isTypeLiteralNode(t) || ts.isMappedTypeNode(t)) return "object";
  const n = refText(t);
  if (n === "Array" || n === "ReadonlyArray") return "array";
  if (n === "Record" || decls.has(n)) return "object";
  if (ts.isUnionTypeNode(t)) return kindOf(t, seen);
  return "any";
}
function arrayElem(t) {
  t = deAlias(tsCore(t));
  if (!t || t.union) return null;
  if (ts.isArrayTypeNode(t)) return t.elementType;
  const n = refText(t);
  if ((n === "Array" || n === "ReadonlyArray") && t.typeArguments?.length === 1) return t.typeArguments[0];
  return null;
}
const PRIM = { string: "string", integer: "number", number: "number", boolean: "boolean", array: "array", object: "object" };

/** 스키마 속성 s ↔ TS 타입 t (경로 where) */
function cmpType(where, s, t) {
  const sc = schemaCore(s);
  if (!sc || !t) return;
  const tk = kindOf(t);
  if (tk === "any") return; // unknown·any 는 대조하지 않음
  const rn = refName(sc);
  if (rn) {
    const target = schemas[rn];
    if (!target) return;
    if (target.enum) return cmpType(where, target, t);
    const c = deAlias(tsCore(t));
    if (!c || c.union) return errors.push(`${where}: 스키마 ${rn}, TS 유니온 ${t.getText(src)}`);
    const n = refText(c);
    if (n === rn) return; // 같은 이름 interface — 그 interface 는 최상위에서 대조
    if (n && decls.has(n)) return cmpObject(`${where}(${n}↔${rn})`, target, resolved(n));
    if (ts.isTypeLiteralNode(c)) return cmpObject(where, target, membersOf(c.members));
    return errors.push(`${where}: 스키마 ${rn}(객체), TS ${t.getText(src)}`);
  }
  if (sc.anyOf || sc.oneOf || sc.allOf) return; // 여러 타입 허용 — 대조 생략
  const want = PRIM[sc.type] ?? (sc.properties ? "object" : sc.enum ? (typeof sc.enum[0] === "number" ? "number" : "string") : null);
  if (!want) return;
  if (tk === "mixed") return errors.push(`${where}: 스키마 ${want}, TS ${t.getText(src)}(여러 종류)`);
  if (tk !== want) return errors.push(`${where}: 타입 불일치 (스키마 ${sc.type ?? want}, TS ${t.getText(src)})`);
  if (want === "array" && sc.items) {
    const el = arrayElem(t);
    if (el) cmpType(`${where}[]`, sc.items, el);
  } else if (want === "object" && sc.properties) {
    const c = deAlias(tsCore(t));
    const n = refText(c);
    if (n && decls.has(n)) cmpObject(where, sc, resolved(n));
    else if (c && ts.isTypeLiteralNode(c)) cmpObject(where, sc, membersOf(c.members));
  }
}

/** 객체 스키마 ↔ TS 속성 맵: 키 집합·필수·null 허용·속성 타입(재귀) */
function cmpObject(where, schema, ms) {
  const props = schema.properties ?? {};
  const req = new Set(schema.required ?? []);
  for (const [k, ps] of Object.entries(props)) {
    const m = ms.get(k);
    if (!m) {
      errors.push(`${where}.${k}: types.ts 에 없음`);
      continue;
    }
    if (req.has(k) && m.optional) errors.push(`${where}.${k}: 스키마 필수인데 TS 에서 선택(?)`);
    const sn = schemaNullable(ps);
    if (!m.unknown && sn !== m.nullable)
      errors.push(`${where}.${k}: null 허용 불일치 (스키마 ${sn ? "null 허용" : "null 불가"}, TS ${m.nullable ? "null 포함" : "null 없음"})`);
    cmpType(`${where}.${k}`, ps, m.type);
  }
  if (Object.keys(props).length || schema.additionalProperties === false)
    for (const k of ms.keys()) if (!(k in props)) errors.push(`${where}.${k}: 스키마에 없는 키(TS 에만 있음)`);
}

const errors = [];
let checked = 0;
for (const [name, schema] of Object.entries(schemas)) {
  if (schema.enum) continue; // 열거형은 참조하는 쪽에서 원시 타입으로 대조
  const ms = resolved(name);
  if (!ms) {
    errors.push(`${name}: types.ts 에 같은 이름의 interface 가 없습니다`);
    continue;
  }
  checked += 1;
  cmpObject(name, schema, ms);
}

// 경로: types.ts 와 별개로 endpoints.ts 가 쓰는 경로가 openapi 에 있는지
// P3: p3.ts·history.ts(있으면)도 같은 규칙으로 대조
const epFiles = ["endpoints.ts", "p3.ts", "history.ts", "opt.ts", "doe.ts", "library.ts"].map((f) => path.resolve(path.dirname(typesPath), f));
for (const epPath of epFiles) {
try {
  if (/(p3|history|opt|doe|library)\.ts$/.test(epPath) && !existsSync(epPath)) continue;
  const ep = readFileSync(epPath, "utf8");
  const epName = path.basename(epPath);
  const prefix = "/esl/api";
  const known = Object.keys(spec.paths ?? {}).map((p) => new RegExp("^" + p.replace(/\{[^}]+\}/g, "[^/]+") + "$"));
  const used = [...ep.matchAll(/request<[^>]*>\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*[`"]([^`"]+)[`"]/g)].map((m) => [m[1], m[2]]);
  const dl = [...ep.matchAll(/\$\{API_PREFIX\}(\/[^`]+)`/g)].map((m) => ["GET", m[1]]);
  for (const [method, p] of [...used, ...dl]) {
    const concrete = prefix + p.replace(/\$\{[^}]+\}/g, "x").replace(/\?.*$/, "");
    const hit = Object.entries(spec.paths).find(([sp]) => known[Object.keys(spec.paths).indexOf(sp)].test(concrete));
    if (!hit) errors.push(`${epName} ${method} ${p}: openapi 에 없는 경로`);
    else if (!hit[1][method.toLowerCase()]) errors.push(`${epName} ${method} ${p}: openapi 에 없는 메서드`);
  }
} catch (e) {
  errors.push(`${path.basename(epPath)} 를 읽을 수 없음: ${e.message}`);
}
}

if (errors.length) {
  console.error(`check:api 실패 (${errors.length}건)\n` + errors.map((e) => "  - " + e).join("\n"));
  process.exit(1);
}
console.log(`check:api 통과: 스키마 ${checked}개 = types.ts, endpoints.ts·p3.ts·history.ts·opt.ts·doe.ts·library.ts 경로 모두 openapi 에 있음`);
