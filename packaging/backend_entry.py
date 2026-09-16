"""Entry point do backend quando empacotado pelo PyInstaller.

Em dev o backend sobe via `uvicorn app.backend.main:app --port 8000`. No app
instalado nao da para fixar a porta: a 8000 e disputada (outro Jupyter, outra
copia do proprio app, qualquer coisa), e se ela estiver ocupada o app abre numa
tela branca sem explicacao.

Entao aqui o proprio processo escolhe uma porta livre, imprime
`DSSE_BACKEND_PORT=<porta>` no stdout e o Electron le essa linha para saber
onde conectar. O socket ja vem ligado antes do uvicorn comecar, entao nao ha
janela de corrida entre "achei a porta livre" e "escutei nela".
"""

from __future__ import annotations

import os
import socket
import sys

import uvicorn

from app.backend.main import app


def _bind() -> socket.socket:
    """Socket ja escutando. `DSSE_BACKEND_PORT` fixa a porta, para debug."""
    forced = os.environ.get("DSSE_BACKEND_PORT")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Sem SO_REUSEADDR de proposito: no Windows ele permite ligar numa porta ja
    # em uso em vez de dar erro, que e exatamente o diagnostico que queremos.
    sock.bind(("127.0.0.1", int(forced) if forced else 0))
    sock.listen(128)
    return sock


def _diagnose() -> None:
    """Despeja como o pandapower resolve seus arquivos de dados, de dentro do
    bundle. Ativado por `DSSE_DIAG=1`; existe porque esse caminho so quebra
    congelado e nao ha como inspecionar de fora."""
    import os

    import pandapower
    from pandapower.__init__ import pp_dir as pp_dir_via_init
    from pandapower import pp_dir as pp_dir_via_pkg

    print("frozen           :", getattr(sys, "frozen", False))
    print("_MEIPASS         :", getattr(sys, "_MEIPASS", None))
    print("pandapower.__file__:", getattr(pandapower, "__file__", None))
    print("pp_dir (pandapower):", pp_dir_via_pkg)
    print("pp_dir (__init__)  :", pp_dir_via_init)
    print("mesmo objeto?      :", pp_dir_via_pkg == pp_dir_via_init)
    print("alias aplicado?    :", sys.modules.get("pandapower.__init__") is pandapower)

    alvos = {
        "mv_oberrhein": os.path.join(pp_dir_via_pkg, "networks", "mv_oberrhein.json"),
        "lv_schutterwald": os.path.join(pp_dir_via_pkg, "networks", "lv_schutterwald.json"),
        "case9": os.path.join(pp_dir_via_init, "networks", "power_system_test_case_jsons", "case9.json"),
    }
    for nome, caminho in alvos.items():
        existe = os.path.isfile(caminho)
        print(f"[{nome}] isfile={existe}")
        print("   ", caminho)
        if existe:
            with open(caminho, "r") as fp:
                head = fp.read(60)
            print("    primeiros 60 chars:", repr(head))


def main() -> None:
    if os.environ.get("DSSE_DIAG") == "1":
        _diagnose()
        return
    sock = _bind()
    port = sock.getsockname()[1]
    # Contrato com `app/electron/main.js` -- se mudar o formato, mude la tambem.
    print(f"DSSE_BACKEND_PORT={port}", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, log_level="info", access_log=False))
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
