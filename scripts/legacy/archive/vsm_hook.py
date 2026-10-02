"""
mkdocs hook — renders .vsm and .tex files as navigable pages.

Strategy: on_pre_build, walk docs_dir and generate a .vsm.md (or .tex.md)
wrapper for every .vsm / .tex file found. Each wrapper embeds the raw
content in a fenced code block. Generated files are cleaned up on_post_build.

Nav entries should reference the .vsm.md path (e.g. theory/vos_theory.vsm.md).
Registered in mkdocs.yml under `hooks:`.
"""

import os
import glob

_generated = []


def on_pre_build(config, **kwargs):
    """Walk docs_dir and generate .md wrappers for all .vsm and .tex files."""
    global _generated
    _generated = []

    docs_dir = config["docs_dir"]

    for ext, lang in [(".vsm", ""), (".tex", "latex")]:
        for src in glob.glob(os.path.join(docs_dir, "**", f"*{ext}"), recursive=True):
            md_path = src + ".md"
            title = os.path.basename(src)

            with open(src, encoding="utf-8") as f:
                content = f.read()

            md_content = f"# `{title}`\n\n```{lang}\n{content}\n```\n"

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

            _generated.append(md_path)


def on_post_build(config, **kwargs):
    """Remove generated .md wrappers after build."""
    for path in _generated:
        try:
            os.remove(path)
        except OSError:
            pass
    _generated.clear()
