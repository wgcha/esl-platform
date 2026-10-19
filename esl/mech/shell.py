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

조립: 노드 인접 패턴(int32)을 먼저 만들고 요소 청크(_CHUNK)마다 6×6 노드 블록을 패턴 위치에
바로 누적(BSR) → 요소별 COO 전체(QUAD 576항/요소)를 만들지 않는다. K_tt·K_tr·K_rr 는 BSR 블록에서
직접 분리한다.

선형 해법 (esl_core §7.5): backend = auto | cholmod | pardiso | superlu | iterative.
auto = 설치된 직접법 중 cholmod → pardiso → superlu 우선, 직접법 예상 메모리가 가용 메모리를
넘으면 반복법(CG; K_rr 노드 3×3 블록 야코비, K_ff pyamg 평활 집적 AMG)으로 전환하고 경고.
규모 상한은 없다. 분해 정보는 `ShellModel.stats` 에 기록(백엔드, 분해 시간, nnz(L), 메모리 추정,
피크 RSS, 반복 수·잔차).
"""
from __future__ import annotations

import glob
import os
import sys
import time
import warnings
from ctypes.util import find_library

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse.csgraph import connected_components

from esl.errors import EslError
from esl.mech import _elements as el

_CHUNK = 4096
BACKENDS = ("auto", "cholmod", "pardiso", "superlu", "iterative")
DIRECT = ("cholmod", "pardiso", "superlu")
# auto: 직접법 예상 메모리가 가용 메모리 × 이 비율을 넘으면 반복법(CG)으로 전환
_MEM_SAFETY = 0.95
# backend="auto" 가 SuperLU 로 떨어질 때 경고하는 요소 수
_SUPERLU_WARN_ELEMS = 50_000


# ======================================================================
# 희소 대칭 양정치 분해 백엔드
# ======================================================================
def _rss_peak_mb():
    """프로세스 최대 RSS(MB). resource 가 없는 플랫폼(Windows)은 psutil 로, 둘 다 없으면 None."""
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1024.0 / (1024.0 if sys.platform == "darwin" else 1.0)
    except Exception:
        pass
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return getattr(mi, "peak_wset", mi.rss) / 2 ** 20
    except Exception:
        return None


def _cholmod_module():
    try:
        from sksparse import cholmod
        return cholmod
    except Exception:
        return None


def _pardiso_solver_cls():
    """pypardiso.PyPardisoSolver (mkl_rt 를 찾지 못하면 None).

    pip 의 mkl 휠은 Linux 에서 libmkl_rt.so.N 만 설치해 ctypes.find_library 가 못 찾는 경우가 있어,
    PYPARDISO_MKL_RT 가 비어 있으면 표준 위치를 검색해 채운다(import 전에 필요).
    """
    if not os.environ.get("PYPARDISO_MKL_RT") and find_library("mkl_rt") is None:
        roots = {sys.prefix, sys.base_prefix, sys.exec_prefix}
        try:
            import site
            roots.update(site.getsitepackages())
            roots.add(site.USER_BASE or "")
        except Exception:
            pass
        try:
            import sysconfig
            for scheme in sysconfig.get_scheme_names():   # pip 이 데이터 파일(lib/) 을 까는 접두 경로
                roots.add(sysconfig.get_paths(scheme)["data"])
        except Exception:
            pass
        roots.update(os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep))
        pats = ("libmkl_rt.so*", "mkl_rt*.dll", "libmkl_rt*.dylib")
        hits = []
        for r in filter(None, roots):
            for sub in ("lib", "lib64", "Library/bin", ""):
                for p in pats:
                    hits += glob.glob(os.path.join(r, sub, p))
        if hits:
            os.environ["PYPARDISO_MKL_RT"] = sorted(hits, key=len)[0]
    try:
        from pypardiso.pardiso_wrapper import PyPardisoSolver
        return PyPardisoSolver
    except Exception:
        return None


def available_backends():
    """설치된 분해 백엔드 목록(우선순위 순)."""
    out = []
    if _cholmod_module() is not None:
        out.append("cholmod")
    if _pardiso_solver_cls() is not None:
        out.append("pardiso")
    out.append("superlu")
    return out


def _pyamg():
    try:
        import pyamg
        return pyamg
    except Exception:
        return None


def available_memory_bytes():
    """가용 물리 메모리(바이트). psutil → /proc/meminfo → Windows GlobalMemoryStatusEx, 모두 실패 시 None."""
    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except Exception:
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for ln in fh:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) * 1024
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MS()
            st.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullAvailPhys)
        except Exception:
            pass
    return None


# 직접법 nnz(L) 경험식 (scripts/bench_shell.py, 원통 패널 223,415 요소 실측 보정):
#   nnz(L) ≈ c · n · (n / n_ref)^0.14   (2D형 쉘 메시 + 중첩 절단/AMD 순서의 준선형 증가)
#   K_ff(노드당 6 dof): c=289, n_ref=1.33e6 · K_rr(노드당 3 dof): c=145, n_ref=6.65e5
_FILL = {6: (289.0, 1.33e6), 3: (145.0, 6.65e5)}
_BYTES_PER_L = {"cholmod": 12.0, "pardiso": 13.0, "superlu": 36.0}


def estimate_direct_bytes(n: int, nnz_A: int, backend: str, dof_per_node: int = 6) -> float:
    """직접 분해 예상 피크(바이트): 인수 + 행렬 사본 2개."""
    c, nref = _FILL.get(dof_per_node, _FILL[6])
    nnz_L = c * n * max(n / nref, 1e-3) ** 0.14
    return nnz_L * _BYTES_PER_L.get(backend, 36.0) + 2 * 12.0 * nnz_A


def resolve_backend(backend: str) -> str:
    b = str(backend).lower()
    if b not in BACKENDS:
        raise EslError("INPUT_INVALID", f"solver backend '{backend}' (허용: {', '.join(BACKENDS)})")
    if b == "auto":
        return available_backends()[0]
    if b == "iterative":
        return b
    if b not in available_backends():
        hint = {"cholmod": "pip install scikit-sparse (libsuitesparse 필요)",
                "pardiso": "pip install pypardiso"}.get(b, "")
        raise EslError("INPUT_INVALID", f"solver backend '{b}' 미설치 — {hint} 또는 backend='auto'")
    return b


class _NotPD(Exception):
    """양정치가 아님(분해 중 0/음 피벗)."""


class _SuperLU:
    name = "superlu"

    def __init__(self, A):
        A = sp.csc_matrix(A)
        try:
            self._lu = spla.splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                                 options={"SymmetricMode": True})
        except RuntimeError as exc:   # "Factor is exactly singular"
            raise EslError("SOLVER_SINGULAR", f"희소 분해 실패: {exc}") from exc
        self.nnz_L = int(self._lu.L.nnz + self._lu.U.nnz)
        self.mem_est_mb = self.nnz_L * 12 / 2 ** 20

    def solve(self, b):
        return self._lu.solve(b)


class _Cholmod:
    """CHOLMOD 초마디 Cholesky (scikit-sparse ≥0.5 의 CholeskyFactor, <0.5 의 cholesky() 모두 지원)."""
    name = "cholmod"

    def __init__(self, A):
        ch = _cholmod_module()
        new_api = hasattr(ch, "CholeskyFactor") and hasattr(ch.CholeskyFactor, "factorize") \
            and hasattr(ch.CholeskyFactor, "solve")
        if new_api:
            # 대칭 A 의 위삼각 CSR 배열 = 아래삼각 CSC (CholeskyFactor(lower=True) 가 사용) → 사본 절반
            Uc = sp.triu(sp.csr_matrix(A), format="csr")
            A = sp.csc_matrix((Uc.data, Uc.indices, Uc.indptr), shape=Uc.shape)
            del Uc
        else:
            A = sp.csc_matrix(A)
        not_pd = getattr(ch, "CholmodNotPositiveDefiniteError", None) or getattr(ch, "CholmodError")
        try:
            if new_api:
                f = ch.CholeskyFactor(A, lower=True)     # 기호 분석 (AMD, 필요 시 METIS)
                f.factorize(A)
                self._solve = f.solve
                nnz = f.nnz
                self.order = str(getattr(f, "order", ""))
            else:                            # scikit-sparse 0.4.x
                f = ch.cholesky(A)
                self._solve = f
                try:
                    nnz = f.L().nnz
                except Exception:
                    nnz = -1
                self.order = ""
        except not_pd as exc:
            raise _NotPD(str(exc)) from exc
        self._f = f
        self.nnz_L = int(nnz)
        self.mem_est_mb = max(self.nnz_L, 0) * 12 / 2 ** 20

    def solve(self, b):
        return np.asarray(self._solve(b)).reshape(np.shape(b))


class _Pardiso:
    """MKL PARDISO, mtype=2 (실수 대칭 양정치), 위삼각 CSR."""
    name = "pardiso"

    def __init__(self, A):
        cls = _pardiso_solver_cls()
        self._A = sp.triu(sp.csr_matrix(A), format="csr")
        self._A.sort_indices()
        self._s = cls(mtype=2)
        self._s.set_iparm(1, 1)          # iparm 직접 지정
        self._s.set_iparm(2, 3)          # METIS 순서 (병렬 OpenMP 판)
        self._s.set_iparm(8, 0)          # 반복 개선 없음 (밖에서 1회 수행)
        self._s.set_iparm(10, 8)         # 피벗 섭동 1e-8 (SPD 에서는 미사용)
        self._s.set_iparm(18, -1)        # nnz(L) 출력
        try:
            self._s.factorize(self._A)
        except Exception as exc:
            code = getattr(exc, "value", None)
            if code == -4:               # zero pivot
                raise _NotPD(f"PARDISO error {code}") from exc
            if code == -2:
                raise EslError("SOLVER_SINGULAR", f"PARDISO 메모리 부족 (error {code})") from exc
            raise EslError("SOLVER_SINGULAR", f"PARDISO 분해 실패: {exc}") from exc
        ip = self._s.get_iparm
        self.nnz_L = int(ip(18))
        # iparm(15) 해석 단계 피크 KB, iparm(16)+(17) 분해·해 단계 KB
        self.mem_est_mb = max(int(ip(15)), int(ip(16)) + int(ip(17))) / 1024.0
        neg = int(ip(23))
        if neg > 0:
            raise _NotPD(f"음의 고유값 {neg}개")

    def solve(self, b):
        return np.asarray(self._s.solve(self._A, np.ascontiguousarray(b, dtype=np.float64))).reshape(np.shape(b))

    def __del__(self):
        try:
            self._s.free_memory(everything=False)
        except Exception:
            pass


class _CG:
    """전처리 CG (대칭 양정치). 전처리: pyamg 평활 집적 AMG(근영공간 B 주어지면) 또는 노드 블록 야코비."""
    name = "iterative"

    def __init__(self, A, rtol=1e-10, maxiter=None, blocks=None, near_null=None, amg=True):
        self._A = sp.csr_matrix(A)
        n = self._A.shape[0]
        self.rtol = float(rtol)
        self.maxiter = int(maxiter) if maxiter else max(2000, min(20000, n // 10))
        self.precond = "none"
        self._M = None
        pa = _pyamg() if amg else None
        if pa is not None and near_null is not None:
            ml = pa.smoothed_aggregation_solver(self._A, B=near_null, symmetry="hermitian",
                                                strength=("symmetric", {"theta": 0.0}), max_coarse=2000)
            self._M = ml.aspreconditioner(cycle="V")
            self.precond = f"pyamg-SA({len(ml.levels)} levels)"
        elif blocks is not None:
            self._M = blocks
            self.precond = "block-jacobi"
        else:
            d = self._A.diagonal()
            self._M = sp.diags(1.0 / d)
            self.precond = "jacobi"
        self.nnz_L = 0
        self.mem_est_mb = 0.0
        self.iters = []
        self.resid = []

    def solve(self, b):
        b = np.asarray(b, dtype=np.float64)
        nb = np.linalg.norm(b)
        if nb == 0:
            return np.zeros_like(b)
        cnt = [0]

        def cb(_xk):
            cnt[0] += 1
        x, info = spla.cg(self._A, b, rtol=self.rtol, atol=0.0, maxiter=self.maxiter, M=self._M, callback=cb)
        r = float(np.linalg.norm(self._A @ x - b) / nb)
        self.iters.append(cnt[0])
        self.resid.append(r)
        if info != 0 or not np.all(np.isfinite(x)) or r > 10 * self.rtol:
            raise EslError("SOLVER_NOT_CONVERGED",
                           f"CG 미수렴 (반복 {cnt[0]}/{self.maxiter}, 상대잔차 {r:.2e} > rtol {self.rtol:.0e}, "
                           f"전처리 {self.precond})")
        return x


_IMPL = {"superlu": _SuperLU, "cholmod": _Cholmod, "pardiso": _Pardiso}


def _factorize(A, backend: str = "superlu", stats: dict | None = None, label: str = "A", *,
               auto: bool = False, dof_per_node: int = 6, iter_opts: dict | None = None,
               iter_setup=None):
    """대칭 양정치 희소행렬 분해(또는 반복 해법 준비).

    - auto=True: 직접법 예상 메모리(estimate_direct_bytes)가 가용 메모리의 _MEM_SAFETY 배를 넘으면
      반복법(CG)으로 전환하고 경고. 규모 상한으로 거부하지 않는다.
    - 비양정치(분해 중 0/음 피벗): SuperLU 예상 메모리가 가용 메모리 안이면 SuperLU 폴백 + 경고,
      아니면 SOLVER_SINGULAR.
    - iter_setup(): 반복법 전처리 정보 dict(blocks, near_null) 를 지연 생성.
    """
    n = A.shape[0]
    t0 = time.perf_counter()
    info = {"backend": backend, "n": int(n), "nnz_A": int(A.nnz)}
    avail = available_memory_bytes()
    if backend in DIRECT:
        est = estimate_direct_bytes(n, A.nnz, backend, dof_per_node)
        info["mem_direct_est_mb"] = round(est / 2 ** 20, 1)
        if avail is not None:
            info["mem_avail_mb"] = round(avail / 2 ** 20, 1)
            if est > _MEM_SAFETY * avail:
                msg = (f"{label}: {backend} 예상 메모리 {est / 2 ** 30:.1f} GB > 가용 {avail / 2 ** 30:.1f} GB"
                       f"×{_MEM_SAFETY}")
                if auto:
                    backend = "iterative"
                    msg += " → 반복법(CG) 전환"
                warnings.warn(msg, RuntimeWarning, stacklevel=3)
                info["warning"] = msg
    if backend == "iterative":
        opts = dict(iter_opts or {})
        if iter_setup is not None:
            opts.update(iter_setup())
        f = _CG(A, **opts)
        info["precond"] = f.precond
        info["rtol"] = f.rtol
        info["maxiter"] = f.maxiter
    else:
        try:
            f = _IMPL[backend](A)
        except _NotPD as exc:
            need = estimate_direct_bytes(n, A.nnz, "superlu", dof_per_node)
            if avail is not None and need > _MEM_SAFETY * avail:
                raise EslError("SOLVER_SINGULAR", f"{label} 가 양정치가 아님({backend}: {exc})") from exc
            msg = f"{label}: {backend} 분해 실패(비양정치: {exc}) → SuperLU 폴백"
            warnings.warn(msg, RuntimeWarning, stacklevel=3)
            info["fallback"] = msg
            f = _SuperLU(A)
    info.update(backend_used=f.name, factor_s=round(time.perf_counter() - t0, 3), nnz_L=f.nnz_L,
                mem_est_mb=round(f.mem_est_mb, 1), rss_peak_mb=_rss_peak_mb())
    if stats is not None:
        stats[label] = info
    f.info = info
    return f


def _record_iter(f, info):
    if isinstance(f, _CG) and f.iters:
        info["iterations"] = list(f.iters[-10:])
        info["resid_rel"] = list(f.resid[-10:])


def _principal_submatrix(K: sp.csr_matrix, keep: np.ndarray) -> sp.csr_matrix:
    """K[keep][:, keep] 를 한 번의 열 사상으로 (중간 행 사본 1회)."""
    n = K.shape[0]
    newid = np.full(n, -1, dtype=np.int64)
    newid[keep] = np.arange(keep.size)
    A = K[keep]                                   # 행 선택
    m = newid[A.indices]
    ok = m >= 0
    cnt = np.add.reduceat(ok, A.indptr[:-1]) if A.nnz else np.zeros(keep.size, int)
    cnt[np.diff(A.indptr) == 0] = 0
    indptr = np.r_[0, np.cumsum(cnt)].astype(A.indptr.dtype)
    out = sp.csr_matrix((A.data[ok], m[ok].astype(A.indices.dtype), indptr), shape=(keep.size, keep.size))
    out.has_sorted_indices = True
    return out


# ======================================================================
class ShellModel:
    def __init__(self, x0, conn, elem_type, thickness, E, nu, drill_factor: float = 1e-4,
                 backend: str = "auto", iter_rtol: float = 1e-10, iter_maxiter: int | None = None):
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
        self.backend = resolve_backend(backend)
        self._auto = str(backend).lower() == "auto"
        self.iter_opts = {"rtol": float(iter_rtol), "maxiter": iter_maxiter}
        self.stats = {"backend": self.backend, "backend_requested": str(backend).lower(),
                      "n_nodes": int(self.n_nodes), "n_elems": int(ne)}
        if self.backend == "superlu" and str(backend).lower() == "auto" and ne > _SUPERLU_WARN_ELEMS:
            msg = (f"요소 {ne}개를 SuperLU 로 풉니다 — 메모리·시간 과다 가능. "
                   "pip install scikit-sparse 또는 pypardiso 권장")
            warnings.warn(msg, RuntimeWarning, stacklevel=2)
            self.stats["warning"] = msg
        self.quad = np.flatnonzero(self.elem_type == 4)
        self.tria = np.flatnonzero(self.elem_type == 3)
        self._K = None
        self._Kb = None
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
        """청크의 전역계 요소 강성 (n,6nn,6nn)·변형률 행렬 (n,6,6nn)·요소 노드 (n,nn)."""
        cn = self.conn[ids, :nn]
        Xe = self.x0[cn]
        R, xy, off = el.local_frames(Xe)
        T = el.transform(R, off)
        fn = el.quad_local if nn == 4 else el.tria_local
        Kl, Sl, A = fn(xy, self.thickness[ids], self.E[ids], self.nu[ids], self.drill_factor)
        self.area[ids] = A
        S = Sl @ T
        Kg = np.swapaxes(T, 1, 2) @ Kl @ T if want_K else None
        return Kg, S, cn

    # ------------------------------------------------------------------
    def _block_K(self) -> sp.bsr_matrix:
        """6×6 노드 블록 BSR 강성 (조립 본체).

        1) 노드 인접 패턴(int32 CSR)을 먼저 만들고, 2) 요소 청크마다 (i,j) 노드쌍 블록을
        패턴 위치로 사상해 블록 배열에 바로 누적한다. 요소별 COO 전체(QUAD 576항/요소)를
        만들지 않으므로 피크 메모리 ≈ 블록 배열(nnz_blocks·36·8 B) + 청크 임시.
        """
        if self._Kb is not None:
            return self._Kb
        t0 = time.perf_counter()
        N = self.n_nodes
        itype = np.int32 if N < 2 ** 31 - 1 else np.int64
        # 노드 인접 패턴
        rows, cols = [], []
        for idx, nn in ((self.quad, 4), (self.tria, 3)):
            if idx.size == 0:
                continue
            cn = self.conn[idx, :nn].astype(itype)
            rows.append(np.repeat(cn, nn, axis=1).ravel())
            cols.append(np.tile(cn, (1, nn)).ravel())
        if not rows:
            P = sp.csr_matrix((N, N))
        else:
            r = np.concatenate(rows)
            c = np.concatenate(cols)
            del rows, cols
            P = sp.csr_matrix((np.ones(r.size, np.float32), (r, c)), shape=(N, N))
            del r, c
            P.sum_duplicates()
            P.sort_indices()
        nb = P.nnz
        rowid = np.repeat(np.arange(N, dtype=np.int64), np.diff(P.indptr))
        gkeys = rowid * N + P.indices                     # 정렬됨 (행 우선, 행 내 열 정렬)
        del rowid
        data = np.zeros((nb, 36))
        for ids, nn in self._batches():
            Kg, _, cn = self._elem_mats(ids, nn)
            Kg = 0.5 * (Kg + np.swapaxes(Kg, 1, 2))      # 반올림 수준 비대칭 제거
            n = len(ids)
            # (n, nn, nn, 6, 6) 노드쌍 블록
            Kb = Kg.reshape(n, nn, 6, nn, 6).transpose(0, 1, 3, 2, 4).reshape(-1, 36)
            del Kg
            a = np.repeat(cn, nn, axis=1).ravel()
            b = np.tile(cn, (1, nn)).ravel()
            pos = np.searchsorted(gkeys, a * N + b)
            # 청크 내 같은 블록끼리 먼저 합산 → 패턴 위치에 누적
            order = np.argsort(pos, kind="stable")
            ps = pos[order]
            st = np.flatnonzero(np.r_[True, ps[1:] != ps[:-1]])
            data[ps[st]] += np.add.reduceat(Kb[order], st, axis=0)
        del gkeys
        data = data.reshape(nb, 6, 6)
        self._Kb = sp.bsr_matrix((data, P.indices, P.indptr), shape=(6 * N, 6 * N), blocksize=(6, 6))
        self.stats["assembly_s"] = round(time.perf_counter() - t0, 3)
        self.stats["nnz_blocks"] = int(nb)
        return self._Kb

    def K(self) -> sp.csr_matrix:
        if self._K is None:
            Kb = self._block_K()
            t0 = time.perf_counter()
            K = Kb.tocsr()
            K.has_sorted_indices = True
            self._K = K
            self.stats["nnz_K"] = int(K.nnz)
            self.stats["tocsr_s"] = round(time.perf_counter() - t0, 3)
        return self._K

    def _diag_blocks(self, i0, bs):
        Kb = self._block_K()
        rows = np.repeat(np.arange(self.n_nodes), np.diff(Kb.indptr))
        dk = np.flatnonzero(Kb.indices == rows)
        return Kb.data[dk][:, i0:i0 + bs, i0:i0 + bs].copy()

    def _block_jacobi(self, i0, bs, fixed=None):
        """노드 대각 블록 역행렬 전처리 (bs·N 정방, BSR). fixed(전역 dof)는 블록에서 분리."""
        D = self._diag_blocks(i0, bs)
        if fixed is not None:
            nd, dd = np.divmod(fixed, bs)
            D[nd, dd, :] = 0.0
            D[nd, :, dd] = 0.0
            D[nd, dd, dd] = 1.0
        N = self.n_nodes
        return sp.bsr_matrix((np.linalg.inv(D), np.arange(N), np.arange(N + 1)), shape=(bs * N, bs * N))

    def _sub_block(self, i0, j0) -> sp.csr_matrix:
        """K 의 노드별 3×3 부분 블록 (i0,j0 ∈ {0: 병진, 3: 회전}) → (3N,3N) CSR."""
        Kb = self._block_K()
        d = np.ascontiguousarray(Kb.data[:, i0:i0 + 3, j0:j0 + 3])
        N = self.n_nodes
        return sp.bsr_matrix((d, Kb.indices, Kb.indptr), shape=(3 * N, 3 * N), blocksize=(3, 3)).tocsr()

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
        if self._krr is None:
            self._check_coverage()
            # 노드 블록에서 직접 분리 (전역 K 의 팬시 인덱싱 사본 없음)
            self._Ktt = self._sub_block(0, 0)
            self._Ktr = self._sub_block(0, 3)
            self._krr = _factorize(self._sub_block(3, 3), self.backend, self.stats, "K_rr", auto=self._auto,
                                   dof_per_node=3, iter_opts=dict(self.iter_opts, amg=False),
                                   iter_setup=lambda: {"blocks": self._block_jacobi(3, 3)})
        x = u_t.ravel()
        y = self._Ktr.T @ x
        F = self._Ktt @ x - self._Ktr @ self._krr.solve(y)
        _record_iter(self._krr, self.stats["K_rr"])
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
        rhs = f[free]

        def iter_setup():
            M = _principal_submatrix(self._block_jacobi(0, 6, fixed).tocsr(), free)
            X = self.x0 - self.x0.mean(axis=0)
            B = np.zeros((self.n_nodes, 6, 6))
            for i in range(3):
                w = np.zeros(3)
                w[i] = 1.0
                B[:, i, i] = 1.0
                B[:, :3, 3 + i] = np.cross(w, X)
                B[:, 3 + i, 3 + i] = 1.0
            return {"blocks": M, "near_null": B.reshape(-1, 6)[free]}

        Kff = _principal_submatrix(K, free)
        lu = _factorize(Kff, self.backend, self.stats, "K_ff", auto=self._auto, dof_per_node=6,
                        iter_opts=self.iter_opts, iter_setup=iter_setup)
        if not isinstance(lu, _CG):
            del Kff                                  # 직접법: 잔차는 전역 K 로 계산
        u = np.zeros(ndof)

        def resid(uf):
            u[free] = uf
            return (K @ u - f)[free]

        uf = lu.solve(rhs)
        if not isinstance(lu, _CG):
            uf = uf - lu.solve(resid(uf))            # 반복 개선 1회
        res = resid(uf)
        nr = np.linalg.norm(rhs)
        rr = float(np.linalg.norm(res) / nr) if nr > 0 else 0.0
        _record_iter(lu, self.stats["K_ff"])
        tol = 1e-8 if not isinstance(lu, _CG) else max(1e-8, 100 * lu.rtol)
        if not np.all(np.isfinite(uf)) or rr > tol:
            raise EslError("SOLVER_SINGULAR", f"해 잔차 과대 ‖Ku−F‖/‖F‖={rr:.2e}")
        self.stats["solve_resid_rel"] = rr
        del lu
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
            _, S, cn = self._elem_mats(ids, nn, want_K=False)
            dofs = (cn[:, :, None] * 6 + np.arange(6)).reshape(len(ids), 6 * nn)
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
