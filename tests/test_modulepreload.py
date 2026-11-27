from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts.gen_modulepreload import BEGIN, END, render_index


class ModulePreloadTests(unittest.TestCase):
    def test_index_preloads_are_current(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts/gen_modulepreload.py"), "--check"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_static_graph_follows_imports_and_reexports(self):
        index = ('<script type="importmap">{"imports":{"package":"/vendor.mjs"}}</script>\n'
                 + BEGIN + END + '\n<script type="module" src="/app.js"></script>\n')
        sources = {
            "app.js": 'import "./side-effect.js";\n'
                      'export {\n  value\n} from "package";\n'
                      'void import("./lazy.js");\n'
                      '// import "./comment.js";\n',
            "side-effect.js": 'export * from "./shared.js";',
            "vendor.mjs": 'export{value}from"./shared.js";',
            "shared.js": 'import "./app.js"; export const value = 1;',
        }
        with TemporaryDirectory() as directory:
            web = Path(directory)
            for name, source in sources.items():
                (web / name).write_text(source, encoding="utf-8")
            rendered = render_index(web, index)

        links = "".join(f'  <link rel="modulepreload" href="/{name}">\n' for name in sources)
        self.assertEqual(rendered, index.replace(BEGIN, BEGIN + links))
