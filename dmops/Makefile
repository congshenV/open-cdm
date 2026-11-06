.PHONY: help venv install run lint test clean

# dmops 需要 Python 3.11+，macOS 自带的 python3 往往还是 3.9。
# 用 make venv PYTHON=/path/to/python3.11 指定解释器。
PYTHON ?= python3
MIN_VERSION := 3.11

VENV := .venv
PY := $(VENV)/bin/python

help:
	@echo "make venv     创建虚拟环境（PYTHON=python3.12 可指定解释器）"
	@echo "make install  安装依赖"
	@echo "make run      本地启动"
	@echo "make lint     语法与风格检查"
	@echo "make test     运行测试"
	@echo "make clean    清理缓存"

# --clear: 已存在的 .venv 会被复用，bin/python 可能还指向旧解释器
venv:
	@$(PYTHON) -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' || { \
		echo "ERROR: dmops 需要 Python $(MIN_VERSION)+，$(PYTHON) 实际是 $$($(PYTHON) -V 2>&1)"; \
		echo "       换一个解释器：make venv PYTHON=python3.12"; \
		exit 1; \
	}
	$(PYTHON) -m venv --clear $(VENV)
	@$(PY) -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' || { \
		echo "ERROR: .venv 实际是 $$($(PY) -V 2>&1)，可能复用了旧环境，执行 rm -rf $(VENV) 后重试"; \
		exit 1; \
	}
	@echo "venv ready: $$($(PY) -V 2>&1)"

install:
	$(PY) -m pip install -r requirements.txt

# 自动加载 .env：身份 secret、数据库口令都放在这里，避免每个终端手工 export 漏掉某项
run:
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	exec $(PY) main.py

lint:
	$(PY) -m compileall -q app main.py

test:
	$(PY) -m pytest tests -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
