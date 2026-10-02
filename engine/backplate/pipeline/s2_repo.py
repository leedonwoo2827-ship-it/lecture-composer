# -*- coding: utf-8 -*-
"""S2 레포 수집 — 결정론. Claude 를 부르지 않는다.

**에이전트는 네트워크도 `gh` 도 만지지 않는다.** 여기서 호스트의 기존 `gh` 인증으로
shallow clone 하고, Claude 스테이지는 그 폴더를 `Read/Grep/Glob` 로만 본다.
토큰이 에이전트 컨텍스트에 들어갈 일이 없다.

산출:
    02_레포/repo/          shallow clone (gitignore 대상)
    cache/s2-repo.json     파일 트리 · 커밋 · README · 스택 추정

clone 직후 `.env*` · `*.pem` · `id_rsa*` 를 지운다. 지우지 않으면 Claude 가
`Read` 로 열어 볼 수 있고, 그 내용이 캐시 JSON 과 최종 덱에 새어 나갈 수 있다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from core import workspace as ws
from pipeline.registry import STAGES, write_cache

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# clone 후 즉시 제거 — 비밀이 에이전트 시야에 들어가지 않게
SECRET_GLOBS = ["**/.env", "**/.env.*", "**/*.pem", "**/id_rsa*", "**/*.p12", "**/*.pfx"]

# 트리에서 뺄 것 — 넣어 봐야 토큰만 먹는다
NOISE = {"node_modules", ".next", "dist", "build", ".git", "__pycache__",
         ".venv", "venv", ".turbo", "coverage", ".cache", "out"}
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java", ".kt",
            ".rb", ".php", ".cs", ".sql", ".prisma", ".sh", ".ps1",
            ".md", ".json", ".yaml", ".yml", ".toml", ".css", ".scss", ".html"}

# 스택 추정 — 파일 존재로만 판단한다(내용을 읽지 않는다)
STACK_HINTS = [
    ("next.config.js", "Next.js"), ("next.config.mjs", "Next.js"),
    ("next.config.ts", "Next.js"), ("nuxt.config.ts", "Nuxt"),
    ("vite.config.ts", "Vite"), ("svelte.config.js", "SvelteKit"),
    ("prisma/schema.prisma", "Prisma"), ("drizzle.config.ts", "Drizzle"),
    ("requirements.txt", "Python"), ("pyproject.toml", "Python"),
    ("go.mod", "Go"), ("Cargo.toml", "Rust"), ("pom.xml", "Java"),
    ("Dockerfile", "Docker"), ("docker-compose.yml", "Docker Compose"),
    ("ecosystem.config.js", "PM2"), ("tailwind.config.js", "Tailwind"),
    ("tailwind.config.ts", "Tailwind"), ("composer.json", "PHP"),
]


def _gh(args: List[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          shell=False, creationflags=CREATE_NO_WINDOW)


def _git(cwd: Path, args: List[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, shell=False,
                          creationflags=CREATE_NO_WINDOW)


def strip_secrets(root: Path) -> List[str]:
    removed = []
    for pat in SECRET_GLOBS:
        for f in root.glob(pat):
            if f.is_file():
                try:
                    f.unlink()
                    removed.append(str(f.relative_to(root)))
                except OSError:
                    pass
    return removed


def walk_tree(root: Path, *, limit: int = 1200) -> List[Dict[str, Any]]:
    """파일 트리. 잡음 폴더를 빼고 코드/문서만. 경로+크기만 담는다(내용 아님)."""
    out: List[Dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if len(out) >= limit:
            break
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in NOISE for part in rel.parts):
            continue
        if p.suffix.lower() not in CODE_EXT:
            continue
        try:
            out.append({"path": rel.as_posix(), "bytes": p.stat().st_size})
        except OSError:
            continue
    return out


HOST_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com[/:]", re.I)
SEG_RE = re.compile(r"^[\w.-]+$")

# 레포 주소 뒤에 붙는 것들 — 여기부터는 레포 이름이 아니라 그 안의 위치다
INNER = {"tree", "blob", "commit", "commits", "pull", "issues", "releases",
         "actions", "wiki", "branches", "tags", "compare", "raw"}


def norm_nwo(raw: str) -> str:
    """`owner/name` · 전체 URL · `git@` 을 모두 `owner/name` 으로.

    ★ 브라우저 주소창에서 그대로 복사해 붙이는 일이 잦다. 그러면
      `.../example-service/tree/main/relay` 처럼 **레포 안의 위치**가 딸려 온다.
      예전엔 정규식이 끝에서부터 두 칸을 집어서 `main/relay` 를 레포 이름으로
      읽었고, 있지도 않은 레포를 받으러 갔다. 앞에서부터 두 칸만 쓴다.
    """
    x = str(raw or "").strip().strip('"').rstrip("/")
    if not x:
        return ""
    x = re.sub(r"^git@github\.com:", "", x, flags=re.I)
    x = HOST_RE.sub("", x)
    x = re.sub(r"\.git$", "", x)
    x = x.split("?")[0].split("#")[0]

    seg = [s for s in x.split("/") if s]
    if len(seg) < 2 or not (SEG_RE.match(seg[0]) and SEG_RE.match(seg[1])):
        return ""
    return f"{seg[0]}/{seg[1]}"


def inner_path(raw: str) -> str:
    """레포 주소 뒤에 딸려 온 안쪽 경로. 있으면 "그건 하위 폴더" 라고 말해 준다."""
    x = HOST_RE.sub("", str(raw or "").strip().rstrip("/"))
    seg = [s for s in x.split("/") if s]
    if len(seg) > 2 and seg[2].lower() in INNER:
        return "/".join(seg[2:])
    return ""


def parse_sources(project: Dict[str, Any]) -> List[Dict[str, str]]:
    """좌표를 **[레포, 라이브 URL] 쌍의 목록**으로 읽는다.

    새 화면은 `sources` 를 준다. 예전 프로젝트는 `repo.name_with_owner` 하나와
    `urls` 를 따로 갖고 있으므로 그것도 받아 준다 — 이미 만든 것이 안 깨져야 한다.
    """
    out: List[Dict[str, str]] = []
    seen = set()

    def add(repo: str, url: str = "", label: str = "") -> None:
        nwo = norm_nwo(repo)
        url = (url or "").strip()
        if not nwo:
            # ★ 레포 없이 **사이트만** 있는 줄도 버리지 않는다. 릴레이 서버처럼
            #   코드는 다른 레포 안에 있고 주소만 따로인 경우가 실제로 있다.
            if url:
                out.append({"repo": "", "url": url, "label": (label or "").strip()})
            return
        if nwo in seen:
            # 같은 레포를 두 줄에 걸쳐 넣었다면(하위 폴더 주소 등) 사이트만 살린다
            if url:
                out.append({"repo": "", "url": url, "label": (label or "").strip()})
            return
        seen.add(nwo)
        out.append({"repo": nwo, "url": url, "label": (label or "").strip()})

    for s in (project.get("sources") or []):
        add(s.get("repo", ""), s.get("url", ""), s.get("label", ""))

    if not out:
        cfg = project.get("repo") or {}
        raw = cfg.get("name_with_owner") or ""
        urls = [u.get("url", "") for u in (project.get("urls") or [])]
        parts = re.split(r"[;,\n]+", str(raw))
        for i, part in enumerate(parts):
            add(part, urls[i] if i < len(urls) else "")
    return out


def clone_one(job, nwo: str, dest: Path, ref: str, force: bool) -> None:
    if dest.exists() and (dest / ".git").is_dir() and not force:
        job.add_log(f"  {nwo} — 이미 있음, fetch")
        _git(dest, ["fetch", "--depth", "60", "origin"])
        _git(dest, ["reset", "--hard", "FETCH_HEAD"])
        return
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = _gh(["repo", "clone", nwo, str(dest), "--",
             "--depth", "60", "--branch", ref], timeout=600)
    if r.returncode != 0:
        # 기본 브랜치 이름이 다를 수 있다 — 브랜치 지정 없이 재시도
        r = _gh(["repo", "clone", nwo, str(dest), "--", "--depth", "60"], timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"{nwo} clone 실패: {(r.stderr or r.stdout)[-240:]}")


def read_one(job, nwo: str, dest: Path) -> Dict[str, Any]:
    """레포 하나를 읽어 트리·커밋·README·스택을 뽑는다."""
    removed = strip_secrets(dest)
    if removed:
        job.add_log(f"  비밀 파일 {len(removed)}개 제거: {', '.join(removed[:4])}")
    tree = walk_tree(dest)

    commits: List[Dict[str, Any]] = []
    r = _git(dest, ["log", "-n", "40", "--date=iso-strict",
                    "--pretty=format:%H%x1f%h%x1f%ad%x1f%s"])
    if r.returncode == 0:
        for line in (r.stdout or "").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append({"sha": parts[0], "short_sha": parts[1],
                                "date": parts[2], "subject": parts[3],
                                "repo": nwo,
                                "url": f"https://github.com/{nwo}/commit/{parts[0]}"})
    head = _git(dest, ["rev-parse", "HEAD"]).stdout.strip()
    branch = _git(dest, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    readme = ""
    for name in ("README.md", "readme.md", "README.MD", "docs/README.md"):
        f = dest / name
        if f.is_file():
            readme = f.read_text(encoding="utf-8", errors="replace")[:20000]
            break

    paths = {x["path"] for x in tree}
    stack = sorted({label for marker, label in STACK_HINTS
                    if marker in paths or any(p.endswith("/" + marker) for p in paths)})
    docs = [x["path"] for x in tree
            if x["path"].lower().endswith(".md") and x["bytes"] > 400][:40]

    job.add_log(f"  {nwo} — 파일 {len(tree)}개 · 커밋 {len(commits)}건 "
                f"· HEAD {head[:8]} ({branch})")
    return {"name_with_owner": nwo, "url": f"https://github.com/{nwo}",
            "head_sha": head, "branch": branch, "file_count": len(tree),
            "tree": tree, "commits": commits, "commit_count": len(commits),
            "readme": readme, "docs": docs, "stack": stack,
            "secrets_removed": removed, "clone_dir": str(dest)}


def run(job, pid: int, slug: str, project: Dict[str, Any], *, force: bool = False):
    stage = STAGES["s2-repo"]
    all_src = parse_sources(project)
    # ★ 사이트만 있는 줄을 갈라 낸다. 릴레이 서버처럼 **코드는 다른 레포 안에 있고
    #   주소만 따로**인 경우가 있다(같은 레포의 하위 폴더를 배포한 것). 받을 것은
    #   없지만 발표에서는 보여 줘야 하므로, 클론 루프에서만 빼고 자료로는 남긴다.
    sources = [s for s in all_src if s["repo"]]
    site_only = [s for s in all_src if not s["repo"] and s["url"]]
    if not sources:
        job.add_log("레포가 지정되지 않았습니다 — 건너뜁니다")
        return write_cache(pid, slug, "s2-repo",
                           input_hash=stage.input_hash(pid, slug, project),
                           data={"skipped": True}, code_version=stage.code_version,
                           status="skipped")

    ref = (project.get("repo") or {}).get("ref") or "main"
    root = ws.sub_dir(pid, slug, "repo", ws.REPO)
    job.add_log(f"레포 {len(sources)}개: "
                + ", ".join(s["repo"] + (f" ({s['url']})" if s["url"] else "")
                            for s in sources))
    for s in site_only:
        job.add_log(f"사이트만: {s['url']} — 받을 레포 없음, 자료로만 씁니다")

    # ★ 레포가 하나면 예전처럼 `repo/` 에 바로 둔다. 여럿이면 이름별 하위 폴더다 —
    #   Claude 가 `cwd=repo/` 에서 Read/Grep 할 때 경로가 자연스럽게 갈린다.
    multi = len(sources) > 1
    repos: List[Dict[str, Any]] = []
    warn: List[str] = []
    for i, src in enumerate(sources, 1):
        nwo = src["repo"]
        sub = ws.ascii_slug(nwo.split("/")[-1])
        dest = root / sub if multi else root
        job.progress(i - 1, len(sources) + 1, nwo)
        try:
            clone_one(job, nwo, dest, ref, force)
            one = read_one(job, nwo, dest)
            one["live_url"] = src["url"]
            one["label"] = src["label"] or nwo.split("/")[-1]
            one["prefix"] = sub + "/" if multi else ""
            repos.append(one)
        except Exception as e:  # noqa: BLE001
            warn.append(f"{nwo}: {type(e).__name__}: {str(e)[:120]}")
            job.add_log(f"  {nwo} 실패 — 계속")
    if not repos:
        raise RuntimeError("레포를 하나도 받지 못했습니다: " + "; ".join(warn))

    # ★ 아래 단계는 **합친 것**을 본다. 레포가 여럿이면 트리 경로 앞에 레포 이름을
    #   붙여 어느 레포 파일인지 알 수 있게 한다.
    tree: List[Dict[str, Any]] = []
    for r in repos:
        tree += [{**x, "path": r["prefix"] + x["path"],
                  "repo": r["name_with_owner"]} for x in r["tree"]]
    commits = sorted((c for r in repos for c in r["commits"]),
                     key=lambda c: c.get("date") or "", reverse=True)[:60]
    readme = "\n\n".join(
        (f"## [{r['name_with_owner']}]"
         + (f"  라이브: {r['live_url']}" if r["live_url"] else "  (라이브 없음)")
         + f"\n{r['readme']}") if multi else r["readme"]
        for r in repos if r["readme"])
    docs = [r["prefix"] + d for r in repos for d in r["docs"]][:60]
    stack = sorted({s for r in repos for s in r["stack"]})

    data = {
        "name_with_owner": " · ".join(r["name_with_owner"] for r in repos),
        "repos": repos,
        "url": next((r["live_url"] for r in repos if r["live_url"]), repos[0]["url"]),
        "head_sha": repos[0]["head_sha"],
        "branch": repos[0]["branch"],
        "file_count": len(tree),
        "tree": tree,
        "commits": commits,
        "commit_count": len(commits),
        "readme": readme,
        "docs": docs,
        "stack": stack,
        "secrets_removed": [x for r in repos for x in r["secrets_removed"]],
        "clone_dir": str(root),
        # 레포 없이 주소만 있는 것들 — 브리프가 "이 사이트도 같이 있다" 로 읽는다
        "extra_sites": [{"url": s["url"], "label": s["label"]} for s in site_only],
    }
    job.progress(len(sources) + 1, len(sources) + 1, "완료")
    job.add_log(f"합계 파일 {len(tree)}개 · 커밋 {len(commits)}건 "
                f"· 스택 {', '.join(stack) or '미상'}")

    return write_cache(pid, slug, "s2-repo",
                       input_hash=stage.input_hash(pid, slug, project),
                       data=data, code_version=stage.code_version,
                       status="degraded" if warn else "ok", warnings=warn)


STAGES["s2-repo"].run = run
