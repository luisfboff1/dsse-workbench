"""Runtime hook: faz `pandapower.__init__` resolver para o modulo `pandapower`.

O pandapower localiza seus arquivos de dados por
`pp_dir = os.path.dirname(os.path.realpath(__file__))`, definido na segunda
linha do `__init__.py`. Varios modulos o importam como
`from pandapower.__init__ import pp_dir` (`power_system_test_cases.py`,
`lv_schutterwald.py`) enquanto outros usam `from pandapower import pp_dir`
(`mv_oberrhein.py`).

Congelado, `pandapower.__init__` vira um modulo SEPARADO de `pandapower`, com
`__file__` proprio e portanto `pp_dir` apontando para um diretorio que nao
existe. O `from_json` do pandapower entao acha que o caminho nao e arquivo e
silenciosamente trata A STRING DO CAMINHO como se fosse o conteudo JSON,
falhando com `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` --
mensagem que nao lembra em nada a causa. O sintoma engana por ser parcial:
`mv_oberrhein` carrega normalmente enquanto todo `caseXX` quebra.

**Por que um alias simples nao resolve.** A versao obvia --
`import pandapower; sys.modules["pandapower.__init__"] = pandapower` -- chega
tarde: `import pandapower` ja importa `pandapower.networks`, que importa
`power_system_test_cases`, que naquele momento executa
`from pandapower.__init__ import pp_dir` e congela o valor errado numa
variavel de modulo. Corrigir `sys.modules` depois nao reescreve esse nome ja
ligado.

Por isso a interceptacao acontece no `sys.meta_path`, antes de qualquer
import: quando um submodulo pede `pandapower.__init__`, devolvemos o proprio
`pandapower` que ja esta em `sys.modules`. Ele pode estar parcialmente
inicializado nesse ponto, o que nao e problema -- `pp_dir` e definido logo na
abertura do `__init__.py`, antes de qualquer import de submodulo.
"""

import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader

_ALIAS = "pandapower.__init__"


class _PandapowerInitAlias(MetaPathFinder, Loader):
    def find_spec(self, fullname, path=None, target=None):
        # So intervem se `pandapower` ja existe: assim um import direto e
        # isolado de `pandapower.__init__` segue o caminho normal em vez de
        # receber None de `create_module`.
        if fullname != _ALIAS or "pandapower" not in sys.modules:
            return None
        return spec_from_loader(fullname, self)

    def create_module(self, spec):
        return sys.modules["pandapower"]

    def exec_module(self, module):
        pass  # o modulo real ja foi executado como `pandapower`


sys.meta_path.insert(0, _PandapowerInitAlias())
