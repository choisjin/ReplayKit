import os, sys, importlib.util
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
_spec = importlib.util.spec_from_file_location("server", os.path.join(_dir, "server.cp310-win_amd64.pyd"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_mod.main()
