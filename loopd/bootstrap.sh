#!/usr/bin/env bash
# loopd/bootstrap.sh —— 沙盒环境初始化（手册 2.2④ 调用）
# 做四件事：装 gh/mise/jq → 落地 loopd.py → clone product-x → 预热证据工具
# #52/#53：relay/filemode/run 远程命令通道已移除，loop shim 与 intents.yaml 不再部署。
set -euo pipefail

LOOP_ORG="${LOOP_ORG:?LOOP_ORG not set}"
LOOP_REPO="${LOOP_REPO:?LOOP_REPO not set}"
LOOP_WS="${LOOP_WS:?LOOP_WS not set}"
LOOP_BOOTSTRAP_REF="${LOOP_BOOTSTRAP_REF:-v0.1.0}"
RAW_BASE="https://raw.githubusercontent.com/${LOOP_ORG}/loop/${LOOP_BOOTSTRAP_REF}"

echo "=== [1/4] Install gh / mise / jq ==="
# gh：已装则跳过
if ! command -v gh >/dev/null 2>&1; then
  echo "Installing gh CLI..."
  # TODO: sha256 校验位由 loop upstream 流程现场填
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null || true
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq gh
fi
gh --version | head -1

# mise：已装则跳过
if ! command -v mise >/dev/null 2>&1; then
  echo "Installing mise..."
  # R11-3: 下载 https://mise.run 到临时文件 → 算 sha256 → 与 UPSTREAM.yaml 中
  # jdx/mise 的 sha256 比对 → 一致才 bash 执行；不一致或取不到期望哈希则报错并非零退出
  # （绝不盲跑未校验的安装脚本）。期望 sha256 优先读本地 UPSTREAM.yaml，否则从 bootstrap
  # ref 拉取（沙盒阶段 UPSTREAM.yaml 尚未落地，故走 RAW_BASE 远程读取）。
  MISE_INSTALL_URL="https://mise.run"
  export MISE_UPSTREAM_URL="${RAW_BASE}/UPSTREAM.yaml"
  if MISE_EXPECTED_SHA256="$(python3 - <<'PY'
import os, re, sys, urllib.request
data = None
try:
    with open("UPSTREAM.yaml", encoding="utf-8") as f:
        data = f.read()
except Exception:
    url = os.environ.get("MISE_UPSTREAM_URL", "")
    if url:
        try:
            data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")
        except Exception:
            data = None
if not data:
    sys.exit(1)
# 仅在 jdx/mise 条目块内（到下一个 `- name:` 之前）取首个 sha256 字段（64 位十六进制）
# 注意：Python re 不支持 POSIX [[:space:]]，故用 [ \t] 表示行首空白。
m = re.search(r'name:[ \t]*jdx/mise\b(?:(?!^[ \t]*- name:).)*?sha256:[ \t]*"?([0-9a-fA-F]{64})"?', data, re.S | re.M)
if not m:
    sys.exit(1)
print(m.group(1).lower())
PY
)"; then
    :
  else
    MISE_EXPECTED_SHA256=""
  fi
  MISE_TMP="$(mktemp)"
  if ! curl -fsSL "$MISE_INSTALL_URL" -o "$MISE_TMP"; then
    echo "ERROR: failed to download mise.run install script" >&2
    rm -f "$MISE_TMP"
    exit 1
  fi
  MISE_ACTUAL_SHA256="$(sha256sum "$MISE_TMP" | awk '{print $1}')"
  if [ -z "$MISE_EXPECTED_SHA256" ]; then
    echo "ERROR: mise sha256 unavailable in UPSTREAM.yaml (could not read expected hash for jdx/mise); refusing to run unverified install script" >&2
    rm -f "$MISE_TMP"
    exit 1
  fi
  if [ "$MISE_ACTUAL_SHA256" != "$MISE_EXPECTED_SHA256" ]; then
    echo "ERROR: mise.run sha256 mismatch (expected ${MISE_EXPECTED_SHA256}, got ${MISE_ACTUAL_SHA256}); refusing to run install script" >&2
    rm -f "$MISE_TMP"
    exit 1
  fi
  echo "  mise.run sha256 OK (${MISE_ACTUAL_SHA256})"
  bash "$MISE_TMP"
  rm -f "$MISE_TMP"
  export PATH="$HOME/.local/bin:$PATH"
fi
mise --version

# jq：已装则跳过
if ! command -v jq >/dev/null 2>&1; then
  sudo apt-get install -y -qq jq
fi
jq --version

echo "=== [2/4] Deploy loopd ==="
# #52/#53：loop shim（relay 客户端）与 intents.yaml（run 白名单）已随远程命令通道移除，
# 不再下载/安装。loopd 只作为守护进程部署（心跳/自动落盘/僵尸回收）。
# 拉 loopd.py → /usr/local/bin/loopd（以 loopd 为名安装，使 loopd --daemon --role X 可直接执行）
python3 -c "import urllib.request; urllib.request.urlretrieve('${RAW_BASE}/loopd/loopd.py', '/tmp/loopd.py')"
sudo install -m 0755 /tmp/loopd.py /usr/local/bin/loopd
# 直接检查 /usr/local/bin/loopd 存在且可执行（不再用 import loopd 探测，那依赖 cwd/PYTHONPATH 不可靠）
if [ -x /usr/local/bin/loopd ]; then
  echo "loopd -> /usr/local/bin/loopd (executable)"
else
  echo "ERROR: /usr/local/bin/loopd not installed or not executable" >&2
  exit 1
fi

echo "=== [3/4] Clone ${LOOP_REPO} to ${LOOP_WS} ==="
# W3-2 AC-5: 注入 scoped token 供 loopd/后续 git 命令使用。
# 若上一级 workflow（scoped-token.yml）已把短效 installation token 注入为
# GH_TOKEN/GITHUB_TOKEN，则此处导出到当前 shell，供后续守护进程消费。
# 注意：绝不把 token 写进 .git/config（会静默持久化，N15 红线）。
if [ -n "${GH_TOKEN:-$GITHUB_TOKEN}" ]; then
  export GITHUB_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"
  echo "scoped-token: injected short-lived token into bootstrap env (LOOP_SCOPED_TOKEN instr)"
fi
if [ -d "${LOOP_WS}/.git" ]; then
  echo "Workspace exists, calibrating remote..."
  cd "${LOOP_WS}"
  git remote set-url origin "https://github.com/${LOOP_ORG}/${LOOP_REPO}.git"
  git fetch origin --prune
else
  git clone "https://github.com/${LOOP_ORG}/${LOOP_REPO}.git" "${LOOP_WS}"
  cd "${LOOP_WS}"
fi
# 对齐 .tool-versions
if [ -f ".tool-versions" ]; then
  mise install
fi

echo "=== [4/4] Pre-warm evidence tools ==="
# 每个工具：已装则跳过；二进制 sha256 校验位留 TODO，由 loop upstream 流程现场填
install_tool() {
  local name="$1" url="$2"
  if command -v "${name}" >/dev/null 2>&1; then
    echo "${name}: already installed"
    return
  fi
  echo "Installing ${name}..."
  # TODO: sha256=$(curl -fsSL ${url}.sha256) ; verify after download
  local tmpbin="/tmp/${name}"
  python3 -c "import urllib.request; urllib.request.urlretrieve('${url}', '${tmpbin}')" || {
    echo "WARNING: ${name} download failed, skipping (will retry on first use)"
    return
  }
  chmod +x "${tmpbin}" && sudo mv "${tmpbin}" "/usr/local/bin/${name}"
}

# zizmor (pip)
if ! command -v zizmor >/dev/null 2>&1; then
  pip install zizmor 2>/dev/null || echo "WARNING: zizmor install failed"
fi

# gitleaks
install_tool gitleaks "https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks-linux-amd64"

# osv-scanner
install_tool osv-scanner "https://github.com/google/osv-scanner/releases/latest/download/osv-scanner-linux-amd64"

# syft
install_tool syft "https://github.com/anchore/syft/releases/latest/download/syft-linux-amd64"

# grype
install_tool grype "https://github.com/anchore/grype/releases/latest/download/grype-linux-amd64"

# opencode（接缝 B 执行体，异构验证工；pin 版本 + SHA256 校验，卡包 A2/A4）
# 校验值以注释占位，由 E 包统一登记进 UPSTREAM.yaml 后回填真实值；
# A 包已先在 UPSTREAM.yaml 追加 opencode 条目（格式照 OPC-v4 P9）。
# 在占位值未回填前，sha256 校验降级为"打印 actual + 警告"，不阻断 bootstrap；
# E 包填入真实 sha256 后自动启用硬校验（不匹配即跳过安装）。
OPENCODE_VERSION="${OPENCODE_VERSION:-v1.18.4}"                                            # pin：v1.18.4 (2026-07-20 发布，已过 7 天冷静期)
OPENCODE_SHA256="${OPENCODE_SHA256:-bab463c3fb3224d388bb7cfad63f38703df9cf0be2cfd2ce8cb49d886b53a174}"  # opencode-linux-x64.tar.gz 真实 sha256
if ! command -v opencode >/dev/null 2>&1; then
  echo "Installing opencode ${OPENCODE_VERSION}..."
  OPENCODE_URL="https://github.com/sst/opencode/releases/download/${OPENCODE_VERSION}/opencode-linux-x64.tar.gz"
  OPENCODE_TMP="/tmp/opencode-linux-x64.tar.gz"
  OPENCODE_EXTRACT="/tmp/opencode-extract"
  if python3 -c "import urllib.request; urllib.request.urlretrieve('${OPENCODE_URL}', '${OPENCODE_TMP}')" 2>/dev/null; then
    ACTUAL=$(sha256sum "${OPENCODE_TMP}" 2>/dev/null | awk '{print $1}' || echo "")
    if [ "${OPENCODE_SHA256}" = "PLACEHOLDER_FILL_BY_UPSTREAM" ]; then
      echo "  opencode sha256 still PLACEHOLDER — verify disabled until E package fills UPSTREAM.yaml (actual=${ACTUAL})"
      rm -rf "${OPENCODE_EXTRACT}" && mkdir -p "${OPENCODE_EXTRACT}" && tar xzf "${OPENCODE_TMP}" -C "${OPENCODE_EXTRACT}" 2>/dev/null && chmod +x "${OPENCODE_EXTRACT}/opencode" 2>/dev/null && mv "${OPENCODE_EXTRACT}/opencode" "/usr/local/bin/opencode" 2>/dev/null || echo "  WARNING: opencode extract/move failed"
    elif [ -n "${ACTUAL}" ] && [ "${ACTUAL}" = "${OPENCODE_SHA256}" ]; then
      echo "  opencode sha256 OK (${ACTUAL})"
      rm -rf "${OPENCODE_EXTRACT}" && mkdir -p "${OPENCODE_EXTRACT}" && tar xzf "${OPENCODE_TMP}" -C "${OPENCODE_EXTRACT}" 2>/dev/null && chmod +x "${OPENCODE_EXTRACT}/opencode" 2>/dev/null && mv "${OPENCODE_EXTRACT}/opencode" "/usr/local/bin/opencode" 2>/dev/null || echo "  WARNING: opencode extract/move failed"
    else
      echo "  WARNING: opencode sha256 mismatch (expected ${OPENCODE_SHA256}, got ${ACTUAL}), skipping install"
    fi
  else
    echo "WARNING: opencode download failed, skipping (will retry on first use)"
  fi
else
  echo "opencode: already installed"
fi
opencode --version 2>/dev/null || echo "  (opencode --version not available yet)"

echo "=== bootstrap.sh complete ==="
