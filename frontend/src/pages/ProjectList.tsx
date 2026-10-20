import { Link } from "react-router-dom";
import { useApp } from "../app/AppContext";
import { Shell } from "../shell/Shell";
import { Empty } from "../components/ui";

export function ProjectList() {
  const { projects, me } = useApp();
  return (
    <Shell crumbs={[]}>
      <h1 className="page-title">프로젝트 선택</h1>
      {!me ? (
        <Empty>불러오는 중…</Empty>
      ) : projects.length === 0 ? (
        <Empty>표시할 프로젝트가 없습니다</Empty>
      ) : (
        <ul className="tile-list">
          {projects.map((p) => (
            <li key={p.id}>
              <Link className="tile" to={`/p/${p.id}`}>
                <span className="tile-title">{p.name}</span>
                <span className="muted small">{p.product_name ?? ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}
