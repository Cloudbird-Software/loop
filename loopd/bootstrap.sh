#!/usr/bin/env bash
# loopd/bootstrap.sh —— 沙盒环境初始化（手册 2.2④ 调用）
# 做四件事：装 gh/mise/jq → 落地 loopd.py/loop → clone product-x → 预热证据工具
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
  # TODO: sha256 校验位由 loop upstream 流程现场填
  curl -fsSL https://mise.run | bash
  export PATH="$HOME/.local/bin:$PATH"
fi
mise --version

# jq：已装则跳过
if ! command -v jq >/dev/null 2>&1; then
  sudo apt-get install -y -qq jq
fi
jq --version

echo "=== [2/4] Deploy loopd + loop shim + intents.yaml ==="
# 落地 intents.yaml 目录
sudo mkdir -p /usr/local/etc/loopd
# 拉 loopd.py → /usr/local/bin/loopd（以 loopd 为名安装，使 loopd --daemon --role X 可直接执行）
python3 -c "import urllib.request; urllib.request.urlretrieve('${RAW_BASE}/loopd/loopd.py', '/tmp/loopd.py')"
sudo install -m 0755 /tmp/loopd.py /usr/local/bin/loopd
# 拉 loop shim → /usr/local/bin/loop
python3 -c "import urllib.request; urllib.request.urlretrieve('${RAW_BASE}/loopd/loop', '/tmp/loop')"
sudo install -m 0755 /tmp/loop /usr/local/bin/loop
# 拉 intents.yaml → /usr/local/etc/loopd/intents.yaml
python3 -c "import urllib.request; urllib.request.urlretrieve('${RAW_BASE}/loopd/intents.yaml', '/tmp/intents.yaml')"
sudo install -m 0644 /tmp/intents.yaml /usr/local/etc/loopd/intents.yaml
# 直接检查 /usr/local/bin/loopd 存在且可执行（不再用 import loopd 探测，那依赖 cwd/PYTHONPATH 不可靠）
if [ -x /usr/local/bin/loopd ]; then
  echo "loopd -> /usr/local/bin/loopd (executable)"
else
  echo "ERROR: /usr/local/bin/loopd not installed or not executable" >&2
  exit 1
fi
echo "loop -> $(command -v loop)"
echo "intents.yaml -> /usr/local/etc/loopd/intents.yaml"

echo "=== [3/4] Clone ${LOOP_REPO} to ${LOOP_WS} ==="
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
OPENCODE_VERSION="${OPENCODE_VERSION:-v0.0.0}"                       # pin：E 包填真实 release tag
OPENCODE_SHA256="${OPENCODE_SHA256:-PLACEHOLDER_FILL_BY_UPSTREAM}"  # 校验占位，E 包填
if ! command -v opencode >/dev/null 2>&1; then
  echo "Installing opencode ${OPENCODE_VERSION}..."
  OPENCODE_URL="https://github.com/sst/opencode/releases/download/${OPENCODE_VERSION}/opencode-linux-amd64"
  OPENCODE_TMP="/tmp/opencode"
  if python3 -c "import urllib.request; urllib.request.urlretrieve('${OPENCODE_URL}', '${OPENCODE_TMP}')" 2>/dev/null; then
    ACTUAL=$(sha256sum "${OPENCODE_TMP}" 2>/dev/null | awk '{print $1}' || echo "")
    if [ "${OPENCODE_SHA256}" = "PLACEHOLDER_FILL_BY_UPSTREAM" ]; then
      echo "  opencode sha256 still PLACEHOLDER — verify disabled until E package fills UPSTREAM.yaml (actual=${ACTUAL})"
      chmod +x "${OPENCODE_TMP}" 2>/dev/null && mv "${OPENCODE_TMP}" "/usr/local/bin/opencode" 2>/dev/null || echo "  WARNING: opencode move failed"
    elif [ -n "${ACTUAL}" ] && [ "${ACTUAL}" = "${OPENCODE_SHA256}" ]; then
      echo "  opencode sha256 OK (${ACTUAL})"
      chmod +x "${OPENCODE_TMP}" 2>/dev/null && mv "${OPENCODE_TMP}" "/usr/local/bin/opencode" 2>/dev/null || echo "  WARNING: opencode move failed"
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
