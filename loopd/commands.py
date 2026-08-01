"""loopd.commands — 统一 JSON 输出辅助 + 退出码常量（W1-1）。

loopd/loopd.py 是单文件 CLI，为保持 `python3 loopd/loopd.py` 独立可运行，
其中已内联同名定义（exit code 常量 + _emit）。本模块供以包方式 import 时复用。
"""
import json

EXIT_OK = 0
EXIT_REFUSED = 10
EXIT_GATE = 11
EXIT_UNKNOWN_VERB = 64
EXIT_CRASH = 70
EXIT_ENV = 78


def _emit(obj, code=EXIT_OK):
    """统一 JSON 输出：print(json.dumps(obj, ensure_ascii=False)) 并返回退出码。"""
    print(json.dumps(obj, ensure_ascii=False))
    return code