"""Capability-restricted subprocess for synthetic code probes; no bank calls."""
import sys
sys.dont_write_bytecode = True
import builtins
import json
import resource
import ast
import datetime
import re


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    payload = json.load(sys.stdin)
    modules = {'json': json, 'datetime': datetime, 're': re}
    def limited_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in modules or level:
            raise ImportError('Module not permitted')
        return modules[name]
    names = ('str int float bool dict list tuple set len range enumerate zip sorted min max sum abs round isinstance all any next iter repr Exception ValueError TypeError KeyError IndexError ZeroDivisionError StopIteration').split()
    safe = {name: getattr(builtins, name) for name in names}
    safe['__import__'] = limited_import
    variables = payload['variables']
    namespace = {'__builtins__': safe, 'vars': variables}
    for code in payload['code']:
        exec(compile(code, '<workflow-probe>', 'exec'), namespace, namespace)
    json.dump(variables, sys.stdout, allow_nan=False)


if __name__ == '__main__':
    main()
