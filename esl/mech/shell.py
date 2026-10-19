"""자체 선형 쉘 FE 솔버 (계약: docs/contracts/esl_core.md §4).

요소 정식화
-----------
- 노드당 6 dof [ux, uy, uz, θx, θy, θz] (전역계, 회전은 오른손 회전벡터).
- 국부계: 노드 평균을 원점으로 하는 평면. 법선 n = QUAD 대각선 외적 (x3−x1)×(x4−x2),
  TRIA 변 외적 (x2−x1)×(x3−x1). 국부 x = 노드1→2 를 평면에 투영한 방향, y = n × x.
  요소 강성은 투영된 평면 요소로 만들고(뒤틀림 강성 무시), 실제 노드와 투영점 사이는
  강체 링크로 연결한다 → 뒤틀린 쿼드·곡면 메시에서도 강체 6모드가 정확히 무에너지.
- QUAD 막: 비적합 모드 Q4 (Wilson 모드 1−ξ², 1−η² + Taylor 보정 = QM6), 2×2 Gauss,
  내부 모드는 요소마다 정적 응축.  굽힘: Mindlin, 2×2.  횡전단: MITC4 (Bathe–Dvorkin
  공변 결합점 보간), 보정계수 5/6.
- TRIA 막: CST.  굽힘: DKT (Batoz 1980, 이산 Kirchhoff, 횡전단 변형 없음) 3점 Gauss.
- 드릴링: 노드마다 k = drill_factor·E·t·A 의 상대 회전 스프링 ½k(θz_i − ω_c)²,
  ω_c = ½(v,x − u,y) 는 요소 중심의 막 회전. 강체 회전에서 0 이므로 강체 모드·막 patch
  test 를 깨지 않는다.
- 변형률 회복: 요소 중심(QUAD ξ=η=0, TRIA 무게중심). 비적합 모드의 미분은 ξ=η=0 에서
  정확히 0 이므로 중심 막 변형률은 호환 Q4 부분만으로 정확하다(모드 진폭 복원 불필요).
  출력 ε = ε_m + z·κ, z = ∓t/2 (layer 0 = bottom, 1 = top), 국부계 텐서 성분 (exx, eyy, exy=γ/2).

조립은 요소 배치(벡터화) + COO→CSR 청크 합산.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse.csgraph import connected_components

from esl.errors import EslError
from esl.mech import _elements as el

_CHUNK = 4096


def _factorize(A: sp.spmatrix):
    """대칭 양정치 희소행렬 LU (SuperLU, 대칭 모드). 정확히 특이하면 SOLVER_SINGULAR."""
    A = sp.csc_matrix(A)
    try:
        return spla.splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                         options={"SymmetricMode": True})
    except RuntimeError as exc:   # "Factor is exactly singular"
        raise EslError("SOLVER_SINGULAR", f"희소 분해 실패: {exc}") from exc


class ShellModel:
    def __init__(self, x0, conn, elem_type, thickness, E, nu, drill_factor: float = 1e-4):
        self.x0 = np.ascontiguousarray(x0, dtype=np.float64)
        self.conn = np.asarray(conn, dtype=np.int64)
        self.elem_type = np.asarray(elem_type).astype(np.int64)
        ne = self.conn.shape[0]
        self.thickness = np.broadcast_to(np.asarray(thickness, dtype=np.float64), (ne,)).copy()
        self.E = np.broadcast_to(np.asarray(E, dtype=np.float64), (ne,)).copy()
        self.nu = np.broadcast_to(np.asarray(nu, dtype=np.float64), (ne,)).copy()
        self.drill_factor = float(drill_factor)
        self.n_nodes = self.x0.shape[0]
        self._validate()
        self.quad = np.flatnonzero(self.elem_type == 4)
        self.tria = np.flatnonzero(self.elem_type == 3)
        self._K = None
        self._krr = None
        self.area = np.zeros(ne)

    # ------------------------------------------------------------------
    def _validate(self):
        N, ne = self.n_nodes, self.conn.shape[0]
        if self.x0.ndim != 2 or self.x0.shape[1] != 3:
            raise EslError("INPUT_INVALID", "x0 는 (N,3)")
        if self.conn.ndim != 2 or self.conn.shape[1] != 4 or self.elem_type.shape != (ne,):
            raise EslError("INPUT_INVALID", "conn (E,4), elem_type (E,)")
        if not np.all(np.isin(self.elem_type, (3, 4))):
            raise EslError("UNSUPPORTED_ELEMENT", "elem_type 은 3(TRIA)·4(QUAD)만")
        q = self.elem_type == 4
        used = np.where(q[:, None], self.conn, np.concatenate([self.conn[:, :3], self.conn[:, :1]], axis=1))
        if used.size and (used.min() < 0 or used.max() >= N):
            raise EslError("INPUT_INVALID", "conn 노드 인덱스 범위 밖")
        if np.any(self.thickness <= 0) or np.any(self.E <= 0) or np.any((self.nu <= -1) | (self.nu >= 0.5)):
            raise EslError("INPUT_INVALID", "두께·E>0, −1<ν<0.5")

    def _batches(self):
        """(요소 인덱스, 노드수) 청크 생성."""
        for idx, nn in ((self.quad, 4), (self.tria, 3)):
            for s in range(0, idx.size, _CHUNK):
                yield idx[s:s + _CHUNK], nn

    def _elem_mats(self, ids, nn, want_K=True):
        """청크의 전역계 요소 강성 (n,6nn,6nn)·변형률 행렬 (n,6,6nn)·전역 dof 인덱스."""
        cn = self.conn[ids, :nn]
        Xe = self.x0[cn]
        R, xy, off = el.local_frames(Xe)
        T = el.transform(R, off)
        fn = el.quad_local if nn == 4 else el.tria_local
        Kl, Sl, A = fn(xy, self.thickness[ids], self.E[ids], self.nu[ids], self.drill_factor)
        self.area[ids] = A
        dofs = (cn[:, :, None] * 6 + np.arange(6)[None, None, :]).reshape(len(ids), 6 * nn)
        S = Sl @ T
        Kg = np.swapaxes(T, 1, 2) @ Kl @ T if want_K else None
        return Kg, S, dofs

    # ------------------------------------------------------------------
    def K(self) -> sp.csr_matrix:
        if self._K is None:
            ndof = 6 * self.n_nodes
            rows, cols, vals = [], [], []
            for ids, nn in self._batches():
                Kg, _, dofs = self._elem_mats(ids, nn)
                Kg = 0.5 * (Kg + np.swapaxes(Kg, 1, 2))     # 반올림 수준 비대칭 제거
                m = 6 * nn
                r = np.repeat(dofs, m, axis=1).ravel()
                c = np.tile(dofs, (1, m)).ravel()
                ck = sp.coo_matrix((Kg.ravel(), (r, c)), shape=(ndof, ndof)).tocsr().tocoo()  # 청크 내 중복 합산
                rows.append(ck.row)
                cols.append(ck.col)
                vals.append(ck.data)
            if rows:
                K = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                  shape=(ndof, ndof)).tocsr()
            else:
                K = sp.csr_matrix((ndof, ndof))
            K.sum_duplicates()
            self._K = K.tocsr()
        return self._K

    # ------------------------------------------------------------------
    def _check_coverage(self):
        q = self.elem_type == 4
        used = np.zeros(self.n_nodes, bool)
        used[self.conn[q].ravel()] = True
        used[self.conn[~q, :3].ravel()] = True
        if not used.all():
            raise EslError("SOLVER_SINGULAR", f"요소에 연결되지 않은 노드 {int((~used).sum())}개")

    def condensed_forces(self, u_t) -> np.ndarray:
        """전 노드 병진 강제(u_t), 회전 자유 → F = (K_tt − K_tr K_rr⁻¹ K_rt) u_t  (N,3)."""
        u_t = np.asarray(u_t, dtype=np.float64)
        if u_t.shape != (self.n_nodes, 3):
            raise EslError("INPUT_INVALID", "u_t 는 (N,3)")
        K = self.K()
        if self._krr is None:
            self._check_coverage()
            t = (np.arange(self.n_nodes)[:, None] * 6 + np.arange(3)).ravel()
            r = t + 3
            self._Ktt = K[t][:, t]
            self._Ktr = K[t][:, r]
            self._krr = _factorize(K[r][:, r])
        x = u_t.ravel()
        y = self._Ktr.T @ x
        F = self._Ktt @ x - self._Ktr @ self._krr.solve(y)
        return F.reshape(self.n_nodes, 3)

    def rotations_for(self, u_t) -> np.ndarray:
        """condensed_forces 상태의 회전 θ = −K_rr⁻¹ K_rt u_t  (N,3) (변형률 평가용 보조)."""
        self.condensed_forces(np.zeros((self.n_nodes, 3)))
        return -self._krr.solve(self._Ktr.T @ np.asarray(u_t, float).ravel()).reshape(self.n_nodes, 3)

    # ------------------------------------------------------------------
    def _check_restraint(self, cons):
        """연결 성분마다 구속 dof 가 강체 6모드를 모두 막는지(구조적 특이 사전검사)."""
        q = self.elem_type == 4
        rows, cols = [], []
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
            mask = q if (a == 3 or b == 3) else np.ones_like(q)
            ca, cb = self.conn[mask, a], self.conn[mask, b]
            rows.append(ca)
            cols.append(cb)
        rows.append(self.conn[~q, 2])
        cols.append(self.conn[~q, 0])
        r = np.concatenate(rows)
        c = np.concatenate(cols)
        G = sp.coo_matrix((np.ones(r.size), (r, c)), shape=(self.n_nodes,) * 2)
        ncomp, lab = connected_components(G, directed=False)
        cons_n = np.array([p for p, _ in cons], dtype=np.int64)
        cons_d = np.array([d for _, d in cons], dtype=np.int64)
        for k in range(ncomp):
            nodes = np.flatnonzero(lab == k)
            X = self.x0[nodes]
            ctr = X.mean(axis=0)
            L = max(float(np.max(np.linalg.norm(X - ctr, axis=1))), 1e-300)
            sel = np.isin(cons_n, nodes)
            if sel.sum() < 6:
                raise EslError("SOLVER_SINGULAR", f"연결 성분 {k}(노드 {nodes.size}개): 구속 dof {int(sel.sum())} < 6")
            P = (self.x0[cons_n[sel]] - ctr) / L
            dd = cons_d[sel]
            A = np.zeros((dd.size, 6))
            A[np.arange(dd.size), dd] = 1.0
            for i in range(3):
                w = np.zeros(3)
                w[i] = 1.0
                A[:, 3 + i] = np.cross(w, P)[np.arange(dd.size), dd]
            s = np.linalg.svd(A, compute_uv=False)
            if s[-1] < 1e-8 * s[0]:
                raise EslError("SOLVER_SINGULAR", f"연결 성분 {k}: 구속이 강체 모드를 막지 못함 (σmin/σmax={s[-1] / s[0]:.2e})")

    def solve(self, F, spc):
        """병진 하중 F (N,3), spc=[(node_idx, "123" 부분집합)] → (u (N,6), R (N,3) 반력)."""
        F = np.asarray(F, dtype=np.float64)
        if F.shape != (self.n_nodes, 3):
            raise EslError("INPUT_INVALID", "F 는 (N,3)")
        cons = set()
        for node, dofs in spc:
            node = int(node)
            if not (0 <= node < self.n_nodes):
                raise EslError("INPUT_INVALID", f"spc 노드 인덱스 {node} 범위 밖")
            ds = str(dofs)
            if not ds or any(ch not in "123" for ch in ds):
                raise EslError("INPUT_INVALID", f"spc dof '{ds}' (병진 1·2·3만)")
            for ch in ds:
                cons.add((node, int(ch) - 1))
        cons = sorted(cons)
        self._check_coverage()
        self._check_restraint(cons)
        K = self.K()
        ndof = 6 * self.n_nodes
        fixed = np.array([6 * p + d for p, d in cons], dtype=np.int64)
        free = np.setdiff1d(np.arange(ndof), fixed)
        f = np.zeros(ndof)
        f[(np.arange(self.n_nodes)[:, None] * 6 + np.arange(3)).ravel()] = F.ravel()
        Kff = K[free][:, free]
        lu = _factorize(Kff)
        u = np.zeros(ndof)
        rhs = f[free]
        uf = lu.solve(rhs)
        res = Kff @ uf - rhs
        uf = uf - lu.solve(res)                      # 반복 개선 1회
        res = Kff @ uf - rhs
        nr = np.linalg.norm(rhs)
        if not np.all(np.isfinite(uf)) or (nr > 0 and np.linalg.norm(res) > 1e-8 * nr):
            raise EslError("SOLVER_SINGULAR", f"해 잔차 과대 ‖Ku−F‖/‖F‖={np.linalg.norm(res) / nr:.2e}")
        u[free] = uf
        reac = (K @ u - f).reshape(self.n_nodes, 6)[:, :3]
        R = np.zeros((self.n_nodes, 3))
        for p, d in cons:
            R[p, d] = reac[p, d]
        return u.reshape(self.n_nodes, 6), R

    # ------------------------------------------------------------------
    def strains(self, u) -> np.ndarray:
        """u (N,6) → eps (E,2,3): 요소 중심, layer 0=bottom(z=−t/2), 1=top(+t/2), 국부 텐서 (exx,eyy,exy)."""
        u = np.asarray(u, dtype=np.float64)
        if u.shape != (self.n_nodes, 6):
            raise EslError("INPUT_INVALID", "u 는 (N,6)")
        uf = u.ravel()
        out = np.zeros((self.conn.shape[0], 2, 3))
        for ids, nn in self._batches():
            _, S, dofs = self._elem_mats(ids, nn, want_K=False)
            e = np.einsum("nij,nj->ni", S, uf[dofs])       # [εm(공학) ; κ(공학)]
            em, ka = e[:, :3], e[:, 3:]
            z = 0.5 * self.thickness[ids][:, None]
            bot = em - z * ka
            top = em + z * ka
            bot[:, 2] *= 0.5
            top[:, 2] *= 0.5
            out[ids, 0] = bot
            out[ids, 1] = top
        return out

    def centroids(self) -> np.ndarray:
        q = self.elem_type == 4
        c = np.empty((self.conn.shape[0], 3))
        c[q] = self.x0[self.conn[q]].mean(axis=1)
        c[~q] = self.x0[self.conn[~q, :3]].mean(axis=1)
        return c
