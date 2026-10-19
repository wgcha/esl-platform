import { Link } from "react-router-dom";
import { useApp } from "../app/AppContext";
import { Shell } from "../shell/Shell";
import { Empty } from "../components/ui";

export function ProjectList() {
  const { projects, me } = useApp();
  return (
    <Shell crumbs={[{ label: "ESL" }]}>
      <h2>프로젝트 선택</h2>
      {!me ? (
        <Empty>불러오는 중…</Empty>
      ) : projects.length === 0 ? (
        <Empty>볼 수 있는 프로젝트가 없습니다.</Empty>
      ) : (
        <ul className="tiles">
          {projects.map((p) => (
            <li key={p.id}>
              <Link className="tile" to={`/p/${p.id}`}>
                <strong>{p.name}</strong>
                <span className="muted">{p.product_name ?? ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}
