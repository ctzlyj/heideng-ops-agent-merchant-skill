"""WorkBuddy's declared stdio MCP dependency. Protocol I/O is isolated from merchant commands."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys


KEY_ENV = 'HEIDENG_WORKBUDDY_INVITE_KEY'
VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
TOOL = {
    'name': 'merchant_command',
    'description': '运行黑灯商家业务入口，查询本机已授权任务或按本次交办执行，返回原始业务回执。',
    'inputSchema': {
        'type': 'object', 'properties': {
            'arguments': {'type':'array', 'items':{'type':'string'}, 'minItems':1,
                          'description':'原商家入口的业务参数数组，按技能经验提供。'}
        }, 'required':['arguments'], 'additionalProperties':False
    }
}


def merchant_output(text):
    """Ignore progress lines and keep the final complete business document."""
    decoder = json.JSONDecoder()
    rest = text.strip()
    while rest:
        try:
            value, end = decoder.raw_decode(rest)
        except ValueError:
            _, _, rest = rest.partition('\n')
        else:
            rest = rest[end:]
            if not rest.strip() and isinstance(value, (dict, list)):
                return value
        rest = rest.lstrip()
    return None


class MerchantService:
    def __init__(self, beta, key):
        self.beta = beta
        self.key = key
        self.config = json.loads((beta.SKILL/'expert-distribution.json').read_bytes())
        self.version = self.config['version']

    def connect(self):
        if not self.key or self.key == '${' + KEY_ENV + '}':
            raise ValueError('WorkBuddy 连接凭证尚未就绪。')
        self.beta.qualify(self.key, self.config['inviteDigests'])

    def call(self, argv):
        from heideng_merchant.safety import redact

        if any(self.key in item for item in argv):
            raise ValueError('凭证只能通过连接配置提供。')
        business = None
        def run(cmd, *, env):
            nonlocal business
            proc = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding='utf-8', errors='replace')
            if len(cmd) >= 4 and Path(cmd[3]).name == 'merchant.py':
                business = merchant_output(proc.stdout)
            return proc
        # argparse usage and command diagnostics must never become protocol output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                result = self.beta.invoke(argv, key=self.key, run=run)
            except self.beta.EligibilityError as error:
                # These are fixed, local eligibility/connector messages. No raw upstream errors.
                return {'status':'blocked','message':redact(str(error),secrets=(self.key,)),
                        'businessExecuted':False}, True
        if isinstance(result, dict):
            return redact(result, secrets=(self.key,)), False
        if business is None:
            return {'status':'needs-reconciliation','message':'未取得完整业务回执，请从原任务核对进度。'}, True
        return redact(business, secrets=(self.key,)), result != 0


def load_service():
    path = Path(__file__).with_name('beta.py')
    spec = importlib.util.spec_from_file_location('heideng_expert_entry', path)
    beta = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(beta)
    sys.path.insert(0, str(beta.checked_core(beta.SKILL)))
    return MerchantService(beta, os.environ.get(KEY_ENV, ''))


class Session:
    def __init__(self, service):
        self.service = service
        self.phase = 'new'

    def respond(self, request):
        def error(code, message):
            return {'jsonrpc':'2.0', 'id':rid, 'error':{'code':code, 'message':message}}
        rid = request.get('id') if isinstance(request, dict) else None
        if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
                or not isinstance(request.get('method'), str)
                or 'id' in request and type(rid) not in (str,int)):
            rid = None
            return error(-32600, 'Invalid Request')
        method = request['method']
        if 'id' not in request:
            if method == 'notifications/initialized' and self.phase == 'connecting':
                self.phase = 'ready'
            return None
        params = request.get('params', {})
        if not isinstance(params, dict):
            return error(-32602, 'Invalid params')
        if method == 'initialize':
            if self.phase != 'new' or not isinstance(params.get('protocolVersion'), str):
                return error(-32602, 'Invalid initialization')
            try:
                self.service.connect()
            except Exception:
                return error(-32001, 'WorkBuddy 未取得有效的受邀连接，请检查连接状态。')
            version = params['protocolVersion']
            result = {'protocolVersion':version if version in VERSIONS else VERSIONS[0],
                      'capabilities':{'tools':{}}, 'serverInfo':{'name':'heideng-member','version':self.service.version}}
            self.phase = 'connecting'
        elif method == 'ping':
            result = {}
        elif self.phase != 'ready':
            return error(-32002, 'MCP session is not initialized')
        elif method == 'tools/list':
            result = {'tools':[TOOL]}
        elif method == 'tools/call':
            args = params.get('arguments')
            if (params.get('name') != TOOL['name'] or not isinstance(args, dict)
                    or set(args) != {'arguments'} or not isinstance(args['arguments'], list)
                    or not args['arguments'] or not all(isinstance(s,str) and '\0' not in s for s in args['arguments'])):
                return error(-32602, 'Invalid merchant command')
            try:
                value, failed = self.service.call(args['arguments'])
            except (Exception, SystemExit):
                value, failed = {'status':'blocked', 'message':'调用未取得可核验结果，请核对原连接和任务回执。'}, True
            result = {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':failed}
        else:
            return error(-32601, 'Method not found')
        return {'jsonrpc':'2.0','id':rid,'result':result}


def serve(source, destination, service):
    session = Session(service)
    for line in source:
        try:
            request = json.loads(line)
        except ValueError:
            response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        else:
            response = session.respond(request)
        if response is not None:
            destination.write(json.dumps(response, ensure_ascii=False, allow_nan=False)+'\n')
            destination.flush()


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        serve(sys.stdin, sys.stdout, load_service())
    except (OSError, ValueError, KeyError):
        raise SystemExit(2) from None
