# Tauri project audit

The read-only auditor and its regression tests are vendored from
[pinkpixel-dev/tauri-skills](https://github.com/pinkpixel-dev/tauri-skills/tree/99697aa3006bec7d65bb2a8f8be0d294407186da/skills/tauri-app-builder/scripts),
commit `99697aa3006bec7d65bb2a8f8be0d294407186da`.
Both Python files are unchanged. The upstream Apache-2.0 license is in [LICENSE](LICENSE).

CI keeps this tool in the repository so checks do not depend on locally installed
agent skills. Run it from the project root with `npm run audit`.

Run its regression tests with:

```sh
python3 -m unittest discover -s scripts/ci/tauri-audit -p 'test_*.py' -v
```
