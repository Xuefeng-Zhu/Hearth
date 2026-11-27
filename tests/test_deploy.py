import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class DeployTests(unittest.TestCase):
    def test_sprite_name_defaults_to_hearth_and_can_be_overridden(self):
        deploy = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            calls = directory / "calls"
            sprite = directory / "sprite.bash"
            sprite.write_text(r"""
sprite() {
  local arg
  for arg; do
    [[ "$arg" == -- ]] && break
    printf '%s\n' "$arg" >> "$SPRITE_CALLS"
  done
  case "$1" in
    info) printf '%s\n' 'URL: https://test-org.sprites.app/' ;;
    exec) cat >/dev/null ;;
    *) return 1 ;;
  esac
}
""")
            env = dict(os.environ, BASH_ENV=str(sprite), SPRITE_CALLS=str(calls))
            env.pop("HEARTH_SPRITE_NAME", None)
            env.pop("HEARTH_SPRITE_ORG", None)
            for name, org in ((None, None), ("my-hearth", "my-org")):
                with self.subTest(name=name, org=org):
                    calls.write_text("")
                    run_env = env.copy()
                    target = ["-s", "hearth"]
                    if name:
                        run_env.update(HEARTH_SPRITE_NAME=name, HEARTH_SPRITE_ORG=org)
                        target = ["-o", org, "-s", name]
                    subprocess.run([str(deploy)], env=run_env, check=True, timeout=30)
                    self.assertEqual(calls.read_text().splitlines(), [
                        "info", *target,
                        "exec", "--http-post", "--no-port-forward", "--stdin", *target,
                    ])
