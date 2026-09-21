# tests/conftest.py
"""
pytest 共享夹具（pytest 主跑器，Issue #10 / #22）

- i18n 语言隔离：autouse 保存/恢复 ``hawarma.i18n.translator`` 的全局
  语言状态。部分用例（如 test_i18n.py）直接 ``set_language`` 且不恢复，
  没有本夹具时会跨文件污染后续用例看到的默认语言。
"""

from __future__ import annotations

import pytest

from hawarma.i18n import translator as _i18n_translator


@pytest.fixture(autouse=True)
def _restore_i18n_language():
    """每个测试结束后，把 i18n 全局语言恢复为进入前的状态。"""
    saved = _i18n_translator._current
    yield
    _i18n_translator._current = saved
