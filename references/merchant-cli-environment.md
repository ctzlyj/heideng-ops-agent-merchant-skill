# Agent 内部：商家隔离环境与目录外官方能力

本页不是商家命令清单，也不是一个新通用执行器。已经存在的 `child_environment`、`OfficialClient` 和 `FileLock` 足以支持宿主在任务目录直调官方CLI；本轮只补用法，不改执行保护。

## 原成熟包装器

在实际Skill目录运行：

```text
python scripts/merchant.py status
python scripts/merchant.py run [--entry scripts/已登记入口.py] <capability> -- <原参数>
```

capability choices 与 entry/provenance 界定此包装器能执行的包内来源。不能把未登记脚本塞进 --entry、修改快照/哈希、启用旧builtin；目录外真实官方能力由宿主另按当前官方契约执行，不受该choices充当全局白名单。

源码：[包装器](../heideng_merchant/cli.py)、[环境与来源保护](../heideng_merchant/mature_runtime.py)、[官方工具与文档获取](../heideng_merchant/official.py)。不要单独直接运行 mature_entry 来绕过来源登记。

## 直调官方 CLI 的前提

1. Agent 用同一商家状态根；运行过自定义 `--state` 时不能另取默认HOME。已有连接器 ready/verify 的Profile和真实目标身份属于本次任务，未知授权先核对原Profile。
2. 从 `OfficialClient(state).executable()` 获取受本包回执/哈希保护的实际官方二进制，不能从宿主默认PATH随便找另一份CLI。
3. `child_environment(state)` 提供商家 HOME/USERPROFILE、JDO_HOME/JDO_CLI_HOME、JINGMAI_LINKER_HOME和安全OS变量；保持官方凭据管理，不导出Token，不改用员工HOME。
4. 通过 `OfficialClient(state).document(skill_id, refresh=True)` 读取官方当前Skill/必要reference（原方法核对公开来源hash）；目录外能力是否可用看真实官方目录、权限与契约，不只看黑灯registry。
5. 每次invoke带正确非default `--profile`、官方 `--request-identity vender`。写入前实时核店/商品对应，并复用原范围批准；未知状态恢复沿原业务回执，不换工具重提。
6. Windows大JSON请求优先复用原 `jdo_listing_mvp.run_jdo_large` / 已登记桥接与其版本兼容检查，不为绕命令长度自行导出官方凭据或猜内部协议。工具没覆盖的新接口在本任务里按官方契约做最小调用，不新造通用业务引擎。

## 只读例子（由Agent在任务目录编写，不是本轮执行）

下例展示已有环境怎样供宿主使用。替换真实路径和**已核验**Profile，不能把占位值当身份。商家只需交办目标，不需填这些字段。读取库存等目录外能力时，先读对应当前官方Skill，再用其真实参数替换；示例本身只读取venderinfo，不写店铺。

```python
import json
import subprocess
import sys
from pathlib import Path

PACKAGE = Path("<Skill实际绝对安装目录>").resolve()
sys.path.insert(0, str(PACKAGE))
from heideng_merchant.mature_runtime import child_environment, checked_command
from heideng_merchant.official import OfficialClient, validate_profile
from heideng_merchant.safety import redact
from heideng_merchant.state import FileLock, merchant_home

state = merchant_home()  # 自定义状态时改为本任务实际状态根，不能换HOME
profile = validate_profile("<连接器已核验的Profile>")
task = Path("<商家任务输出目录>").resolve()
task.mkdir(parents=True, exist_ok=True)
client = OfficialClient(state)
# 需要时先读取该路径的完整官方文档，不把缓存说明当当前永恒契约。
document_path = client.document("jdo-seller-info", refresh=True)
# Agent先读document_path，并确认本任务店铺/Profile；不输出账户凭据。
with FileLock(state / "install.lock", shared=True):
    executable = client.executable()
    environment = child_environment(state)
    environment["JDO_CLI_PATH"] = str(executable)
    environment.pop("HEIDENG_MERCHANT_LTS4AI_API_KEY", None)  # 只读官方调用不需要图片Key
    arguments = [str(executable), "invoke", "--skill-id", "jdo-seller-info",
                 "--url", "/rest/sp-seller/v0/venderinfo", "--method", "GET",
                 "--params", json.dumps({"scopeSet": "baseInfo"}),
                 "--profile", profile, "--request-identity", "vender"]
    checked_command(arguments)
    result = subprocess.run(arguments, cwd=task, env=environment,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=90, check=False)
    # 按官方格式解析实际响应并比对预期店铺；不把returncode==0直接当核店成功。
    print(redact(result.stdout))
    if result.returncode:
        print(redact(result.stderr))
```

例子只公开环境桥接方式。每项写入仍需要原/官方业务核店、用户实际批准、提交前持久回执和未知结果恢复；不能把这段只读例子改成无保护任意POST执行器。

## 宿主工具、记忆与异常

宿主可以读取商家已授权网页、计算/整理表格或编写本任务局部脚本，但目录外工具不意味着可以换店、换模型、超预算或重复提交。商家私有结果、报表、记忆和凭据不写Skill安装目录/发布包。更新前后的任务恢复读取原状态，不因为更新删回执或重复业务。

没有当前文档/权限/可靠身份/所需服务时报告具体缺项；只读资料整理与其他可行部分继续。不会为一次读取要求商家配置生图/AI视频，也不会因用户没交办而主动跑上述示例。


## 解释器与浏览器元数据适配（0.4.1）

默认安装准备原成熟核心依赖，不只安装更新组件。任务入口只在缺失时补齐；不借宿主个人 site-packages。3.12 发现发生在 HOME 隔离之前，传入成熟 `JDO_PYTHON312` 后仍按原探针核验真实版本/CLI接口；可显式设置商家命名的 `HEIDENG_MERCHANT_PYTHON312`，这只是解释器路径，不是凭据。

原 HostBrowser 的真实 report 可以同时提供 owned `profileDir` 和 `browserChannel`，二者必须是本会话本店的实际值；新连接将其登记到商家自己的店铺记录。既有登记缺类型时由宿主补充实际浏览器类型，不新扫码、不抄 Cookie；原默认Chrome只用于原Chrome资料，不宣称检测到了每个旧profile类型。
